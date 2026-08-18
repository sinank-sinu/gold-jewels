from odoo import models, fields, api, _
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


def _s(val):
    """Safely extract a plain string from a PostgreSQL value.
    Odoo 17 stores translatable char fields as JSONB dicts in the DB.
    Raw cr.execute() returns them as Python dicts like {'en_US': 'Weight'}.
    """
    if val is None:
        return ''
    if isinstance(val, dict):
        return (val.get('en_US') or next(iter(val.values()), '') or '').strip()
    return str(val).strip()


class StockSummaryReportWizard(models.TransientModel):
    _name = 'stock.summary.report.wizard'
    _description = 'Stock Summary Report Wizard'

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True, default=fields.Date.today)
    branch_ids = fields.Many2many('res.branch', string='Branches')

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _action_result(self):
        return {
            'name': _('Stock Summary Report'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.summary.report.line',
            'view_mode': 'tree',
            'context': {'search_default_group_by_product': 1},
        }

    # ------------------------------------------------------------------
    # DB index helper — called once per report run (no-op if already exist)
    # ------------------------------------------------------------------

    def _ensure_report_indexes(self):
        """Create indexes on the key columns our CTE queries filter on.
        CREATE INDEX IF NOT EXISTS is instant when the index already exists.
        All indexes are partial where possible to keep them small.
        """
        cr = self.env.cr
        indexes = [
            # ── product_label ────────────────────────────────────────────
            # relevant_labels CTE: WHERE create_date >= ? AND create_date <= ?
            """
            CREATE INDEX IF NOT EXISTS idx_pl_create_date
            ON product_label (create_date)
            """,
            # relevant_labels CTE: WHERE create_date < ? AND active = TRUE
            """
            CREATE INDEX IF NOT EXISTS idx_pl_active_create_date
            ON product_label (active, create_date)
            WHERE active = TRUE
            """,
            # branch filter on product_label
            """
            CREATE INDEX IF NOT EXISTS idx_pl_branch_id
            ON product_label (branch_id)
            WHERE branch_id IS NOT NULL
            """,

            # ── stock_move ───────────────────────────────────────────────
            # EXISTS subquery in relevant_labels: label_id, state, date
            """
            CREATE INDEX IF NOT EXISTS idx_sm_label_state_date
            ON stock_move (label_id, state, date)
            WHERE label_id IS NOT NULL AND state = 'done'
            """,
            # sold_before / moved_out_before CTEs: label_id + date + locs
            """
            CREATE INDEX IF NOT EXISTS idx_sm_label_date_locs
            ON stock_move (label_id, date, location_id, location_dest_id)
            WHERE label_id IS NOT NULL AND state = 'done'
            """,
            # no-label moves: state + date + location columns
            """
            CREATE INDEX IF NOT EXISTS idx_sm_nolabel_state_date_loc
            ON stock_move (state, date, location_id, location_dest_id)
            WHERE label_id IS NULL AND state = 'done'
            """,

            # ── sale_order_line ──────────────────────────────────────────
            # sold_before / sold_in CTEs: label_id + state
            """
            CREATE INDEX IF NOT EXISTS idx_sol_label_state
            ON sale_order_line (label_id, state)
            WHERE label_id IS NOT NULL
            """,

            # ── sale_order ───────────────────────────────────────────────
            # sold_before / sold_in CTEs: date_order
            """
            CREATE INDEX IF NOT EXISTS idx_so_date_order
            ON sale_order (date_order)
            """,
            # branch filter on sale_order
            """
            CREATE INDEX IF NOT EXISTS idx_so_branch_date_order
            ON sale_order (branch_id, date_order)
            WHERE branch_id IS NOT NULL
            """,

            # ── stock_warehouse_orderpoint ───────────────────────────────
            # min_stock CTE: location_id + product_id
            """
            CREATE INDEX IF NOT EXISTS idx_swo_loc_product
            ON stock_warehouse_orderpoint (location_id, product_id)
            """,
        ]
        for sql in indexes:
            try:
                cr.execute(sql)
            except Exception as e:
                _logger.warning("Could not create report index: %s", e)

    # ------------------------------------------------------------------
    # Main report generator — everything computed in PostgreSQL
    # ------------------------------------------------------------------

    def action_generate_report(self):
        self.ensure_one()
        cr = self.env.cr
        uid = self.env.uid

        # ── 0. Ensure DB indexes exist (no-op if already created) ───────
        self._ensure_report_indexes()

        start_dt = datetime.combine(self.start_date, datetime.min.time())
        end_dt = datetime.combine(self.end_date, datetime.max.time())
        no_of_days = (self.end_date - self.start_date).days + 1
        today_date = fields.Date.today()
        branch_ids = self.branch_ids.ids or None

        # ── 1. Delete previous results for this user ────────────────────
        cr.execute(
            "DELETE FROM stock_summary_report_line WHERE create_uid = %s",
            (uid,)
        )

        # ── 2. Internal locations ───────────────────────────────────────
        if branch_ids:
            cr.execute(
                "SELECT id FROM stock_location WHERE usage = 'internal' AND branch_id = ANY(%s)",
                (branch_ids,)
            )
        else:
            cr.execute("SELECT id FROM stock_location WHERE usage = 'internal'")
        internal_loc_ids = [r[0] for r in cr.fetchall()]
        if not internal_loc_ids:
            return self._action_result()

        # ── 3. Weight / Unit UoM category IDs ──────────────────────────
        #    (handles Odoo 17 JSONB translation via _s() helper)
        cr.execute("SELECT id, name FROM uom_category")
        weight_cat_ids, unit_cat_ids = [], []
        for (cid, name) in cr.fetchall():
            n = _s(name)
            if n == 'Weight':
                weight_cat_ids.append(cid)
            elif n in ('Unit', 'Units', 'Working Time'):
                unit_cat_ids.append(cid)

        # ── 4. Product attribute map (batch, handles JSONB) ─────────────
        cr.execute(
            """
            SELECT ptav.product_tmpl_id,
                   pa.name  AS attr_name,
                   pav.name AS val_name
            FROM product_template_attribute_value ptav
            JOIN product_attribute        pa  ON pa.id  = ptav.attribute_id
            JOIN product_attribute_value  pav ON pav.id = ptav.product_attribute_value_id
            """
        )
        tmpl_attr_map = {}   # tmpl_id → {attr_lower: val}
        for (tmpl_id, a_name, v_name) in cr.fetchall():
            key = _s(a_name).lower()
            val = _s(v_name)
            if key:
                tmpl_attr_map.setdefault(tmpl_id, {})[key] = val

        # ── 5. Build branch filter clauses ──────────────────────────────
        bl = "AND pl.branch_id = ANY(%(branch_ids)s)"  if branch_ids else ""
        bs = "AND so.branch_id = ANY(%(branch_ids)s)"  if branch_ids else ""
        bs2 = "AND so2.branch_id = ANY(%(branch_ids)s)" if branch_ids else ""

        params = {
            'start_dt':    start_dt,
            'end_dt':      end_dt,
            'iloc_ids':    internal_loc_ids,
            'branch_ids':  branch_ids,
            'no_of_days':  no_of_days,
            'today':       today_date,
            'uid':         uid,
            'now':         fields.Datetime.now(),
            'weight_cats': weight_cat_ids or [0],
            'unit_cats':   unit_cat_ids or [0],
        }

        # ── 6. LABELED items: one big CTE computes everything in DB ─────
        labeled_sql = f"""
        WITH
        -- 6a. All relevant label IDs (four criteria, UNION deduplicates)
        relevant_labels AS (
            SELECT DISTINCT pl.id,
                   pl.product_id,
                   pl.purity_id,
                   COALESCE(pl.purchase_gross_weight, 0.0) AS gross,
                   COALESCE(pl.purchase_net_weight,   0.0) AS net,
                   pl.create_date,
                   COALESCE(pl.age_import, 0)              AS age_import
            FROM product_label pl
            WHERE (
                (pl.create_date >= %(start_dt)s AND pl.create_date <= %(end_dt)s)
                OR (pl.create_date < %(start_dt)s AND pl.active = TRUE)
                OR EXISTS (
                    SELECT 1 FROM stock_move sm2
                    WHERE sm2.label_id = pl.id
                      AND sm2.state = 'done'
                      AND sm2.date >= %(start_dt)s
                      AND sm2.date <= %(end_dt)s
                )
                OR EXISTS (
                    SELECT 1 FROM sale_order_line sol2
                    JOIN sale_order so2 ON so2.id = sol2.order_id
                    WHERE sol2.label_id = pl.id
                      AND sol2.state IN ('sale','done')
                      AND so2.date_order >= %(start_dt)s
                      AND so2.date_order <= %(end_dt)s
                      {bs2}
                )
            )
            {bl}
        ),

        -- 6b. Labels sold BEFORE the period (excluded from opening stock)
        sold_before AS (
            SELECT DISTINCT sol.label_id
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            JOIN relevant_labels rl ON rl.id = sol.label_id
            WHERE sol.state IN ('sale','done')
              AND so.date_order < %(start_dt)s
        ),

        -- 6c. Labels moved OUT of internal locations before period
        moved_out_before AS (
            SELECT DISTINCT sm.label_id
            FROM stock_move sm
            JOIN relevant_labels rl ON rl.id = sm.label_id
            WHERE sm.state = 'done'
              AND sm.date < %(start_dt)s
              AND sm.location_id      = ANY(%(iloc_ids)s)
              AND NOT (sm.location_dest_id = ANY(%(iloc_ids)s))
        ),

        -- 6d. Labels sold IN the period (these are 'out')
        sold_in AS (
            SELECT DISTINCT sol.label_id
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            JOIN relevant_labels rl ON rl.id = sol.label_id
            WHERE sol.state IN ('sale','done')
              AND so.date_order >= %(start_dt)s
              AND so.date_order <= %(end_dt)s
              {bs}
        ),

        -- 6e. Compute opening / in / out flags per label (0 or 1)
        label_flags AS (
            SELECT
                rl.id              AS label_id,
                rl.product_id,
                rl.purity_id,
                rl.gross,
                rl.net,
                rl.create_date,
                rl.age_import,
                -- Opening: existed before period and NOT sold/moved out
                CASE WHEN rl.create_date < %(start_dt)s
                          AND sb.label_id IS NULL
                          AND mob.label_id IS NULL
                     THEN 1.0 ELSE 0.0 END AS o_flag,
                -- In: created within the period
                CASE WHEN rl.create_date >= %(start_dt)s
                          AND rl.create_date <= %(end_dt)s
                     THEN 1.0 ELSE 0.0 END AS in_flag,
                -- Out: sold within the period
                CASE WHEN si.label_id IS NOT NULL
                     THEN 1.0 ELSE 0.0 END AS out_flag
            FROM relevant_labels rl
            LEFT JOIN sold_before    sb  ON sb.label_id  = rl.id
            LEFT JOIN moved_out_before mob ON mob.label_id = rl.id
            LEFT JOIN sold_in        si  ON si.label_id  = rl.id
        ),

        -- 6f. Pre-compute gross/net values and average inventory
        label_kpis AS (
            SELECT
                lf.*,
                lf.o_flag   * lf.gross  AS o_gross,
                lf.o_flag   * lf.net    AS o_net,
                lf.in_flag  * lf.gross  AS in_gross,
                lf.in_flag  * lf.net    AS in_net,
                lf.out_flag * lf.gross  AS out_gross,
                lf.out_flag * lf.net    AS out_net,
                (lf.o_flag + lf.in_flag - lf.out_flag) * lf.gross AS c_gross,
                (lf.o_flag + lf.in_flag - lf.out_flag) * lf.net   AS c_net,
                -- avg_inventory with fallback when both opening and closing are 0
                CASE
                    WHEN ((lf.o_flag + (lf.o_flag + lf.in_flag - lf.out_flag)) * lf.gross) / 2.0 <= 0
                         AND (lf.in_flag > 0 OR lf.out_flag > 0)
                    THEN (lf.in_flag + lf.out_flag) * lf.gross / 4.0
                    ELSE ((lf.o_flag + (lf.o_flag + lf.in_flag - lf.out_flag)) * lf.gross) / 2.0
                END AS avg_inv
            FROM label_flags lf
            WHERE lf.o_flag > 0 OR lf.in_flag > 0 OR lf.out_flag > 0
        ),

        -- 6g. Min-stock rules per product (single pre-aggregated subquery)
        min_stock AS (
            SELECT product_id, MIN(product_min_qty) AS min_qty
            FROM stock_warehouse_orderpoint
            WHERE location_id = ANY(%(iloc_ids)s)
            GROUP BY product_id
        )

        -- Final SELECT: all KPIs computed in SQL
        SELECT
            lk.label_id,
            lk.product_id,
            pp.product_tmpl_id,
            lk.purity_id,
            -- Opening
            lk.o_flag    AS opening_pcs,
            lk.o_gross   AS opening_gross_weight,
            lk.o_net     AS opening_net_weight,
            -- In
            lk.in_flag   AS in_pcs,
            lk.in_gross  AS in_gross_weight,
            lk.in_net    AS in_net_weight,
            -- Out
            lk.out_flag  AS out_pcs,
            lk.out_gross AS out_gross_weight,
            lk.out_net   AS out_net_weight,
            -- Closing
            lk.o_flag + lk.in_flag - lk.out_flag AS closing_pcs,
            lk.c_gross  AS closing_gross_weight,
            lk.c_net    AS closing_net_weight,
            -- KPIs
            lk.avg_inv  AS average_inventory,
            CASE WHEN lk.avg_inv > 0.0001
                 THEN lk.out_gross / lk.avg_inv ELSE 0.0
            END AS turnover_ratio,
            CASE
                WHEN lk.avg_inv > 0.0001
                     AND (lk.out_gross / lk.avg_inv) > 0.0001
                THEN ROUND(%(no_of_days)s::float / (lk.out_gross / lk.avg_inv))
                WHEN lk.avg_inv > 0.0001 THEN %(no_of_days)s::float
                ELSE 0.0
            END AS dio,
            COALESCE(ms.min_qty, 0.0)              AS min_stock_level,
            lk.c_gross - COALESCE(ms.min_qty, 0.0) AS stock_gap,
            -- Ageing
            CASE
                WHEN lk.age_import != 0
                THEN lk.age_import + (%(today)s::date - lk.create_date::date)
                ELSE (%(today)s::date - lk.create_date::date) + 1
            END AS ageing
        FROM label_kpis lk
        JOIN product_product pp ON pp.id = lk.product_id AND pp.active = TRUE
        LEFT JOIN min_stock ms ON ms.product_id = lk.product_id
        """

        cr.execute(labeled_sql, params)
        # cols: label_id, product_id, tmpl_id, purity_id,
        #        opening_pcs, opening_gross, opening_net,
        #        in_pcs, in_gross, in_net,
        #        out_pcs, out_gross, out_net,
        #        closing_pcs, closing_gross, closing_net,
        #        avg_inv, turnover_ratio, dio,
        #        min_stock_level, stock_gap, ageing
        labeled_rows = cr.fetchall()

        # ── 7. NO-LABEL moves: aggregated in SQL by product ─────────────
        #    Opening  = net in/out before start_dt
        #    In       = 0  (matching original behaviour: label creation = "in")
        #    Out      = outgoing moves during the period
        labeled_product_ids = list({r[1] for r in labeled_rows if r[1]})

        no_label_sql = """
        SELECT
            sm.product_id,
            pp.product_tmpl_id,
            pp.purity_id,
            -- Opening pcs (unit-cat, net movement before period)
            SUM(CASE
                WHEN sm.date < %(start_dt)s
                     AND sm.location_dest_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(unit_cats)s)
                THEN sm.product_uom_qty
                WHEN sm.date < %(start_dt)s
                     AND sm.location_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_dest_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(unit_cats)s)
                THEN -sm.product_uom_qty
                ELSE 0 END)  AS opening_pcs,
            -- Opening gross (weight-cat, net movement before period)
            SUM(CASE
                WHEN sm.date < %(start_dt)s
                     AND sm.location_dest_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(weight_cats)s)
                THEN sm.product_uom_qty
                WHEN sm.date < %(start_dt)s
                     AND sm.location_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_dest_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(weight_cats)s)
                THEN -sm.product_uom_qty
                ELSE 0 END)  AS opening_gross,
            -- Opening net  (gross x purity pct)
            SUM(CASE
                WHEN sm.date < %(start_dt)s
                     AND sm.location_dest_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(weight_cats)s)
                THEN sm.product_uom_qty
                         * COALESCE(gp.percentage, gp_p.percentage, 100.0) / 100.0
                WHEN sm.date < %(start_dt)s
                     AND sm.location_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_dest_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(weight_cats)s)
                THEN -sm.product_uom_qty
                         * COALESCE(gp.percentage, gp_p.percentage, 100.0) / 100.0
                ELSE 0 END)  AS opening_net,
            -- Out pcs (unit-cat, outgoing during period)
            SUM(CASE
                WHEN sm.date >= %(start_dt)s AND sm.date <= %(end_dt)s
                     AND sm.location_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_dest_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(unit_cats)s)
                THEN sm.product_uom_qty ELSE 0 END) AS out_pcs,
            -- Out gross (weight-cat, outgoing during period)
            SUM(CASE
                WHEN sm.date >= %(start_dt)s AND sm.date <= %(end_dt)s
                     AND sm.location_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_dest_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(weight_cats)s)
                THEN sm.product_uom_qty ELSE 0 END) AS out_gross,
            -- Out net
            SUM(CASE
                WHEN sm.date >= %(start_dt)s AND sm.date <= %(end_dt)s
                     AND sm.location_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_dest_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(weight_cats)s)
                THEN sm.product_uom_qty
                         * COALESCE(gp.percentage, gp_p.percentage, 100.0) / 100.0
                ELSE 0 END) AS out_net,
            COALESCE((
                SELECT MIN(swo.product_min_qty)
                FROM stock_warehouse_orderpoint swo
                WHERE swo.product_id = sm.product_id
                  AND swo.location_id = ANY(%(iloc_ids)s)
            ), 0.0) AS min_stock_level
        FROM stock_move sm
        JOIN product_product pp ON pp.id = sm.product_id AND pp.active = TRUE
        JOIN uom_uom u          ON u.id  = sm.product_uom
        LEFT JOIN gold_purity gp   ON gp.id  = sm.purity_id
        LEFT JOIN gold_purity gp_p ON gp_p.id = pp.purity_id
        WHERE sm.state   = 'done'
          AND sm.label_id IS NULL
          AND sm.date    <= %(end_dt)s
          AND (sm.location_id = ANY(%(iloc_ids)s) OR sm.location_dest_id = ANY(%(iloc_ids)s))
        GROUP BY sm.product_id, pp.product_tmpl_id, pp.purity_id
        HAVING ABS(SUM(CASE
                WHEN sm.date < %(start_dt)s
                     AND u.category_id = ANY(%(weight_cats)s)
                     AND (sm.location_dest_id = ANY(%(iloc_ids)s) OR sm.location_id = ANY(%(iloc_ids)s))
                THEN CASE WHEN sm.location_dest_id = ANY(%(iloc_ids)s) THEN sm.product_uom_qty ELSE -sm.product_uom_qty END
                ELSE 0 END)) > 0.0001
        OR ABS(SUM(CASE
                WHEN sm.date >= %(start_dt)s AND sm.date <= %(end_dt)s
                     AND sm.location_id = ANY(%(iloc_ids)s)
                     AND NOT (sm.location_dest_id = ANY(%(iloc_ids)s))
                     AND u.category_id = ANY(%(weight_cats)s)
                THEN sm.product_uom_qty ELSE 0 END)) > 0.0001
        """

        cr.execute(no_label_sql, params)
        no_label_rows = cr.fetchall()
        # cols: product_id, tmpl_id, purity_id,
        #        opening_pcs, opening_gross, opening_net,
        #        out_pcs, out_gross, out_net,
        #        min_stock_level

        # ── 8. Assemble report_lines (pure dict construction, no loops over records) ─
        report_lines = []

        for row in labeled_rows:
            (label_id, product_id, tmpl_id, purity_id,
             o_pcs, o_gross, o_net,
             in_pcs, in_gross, in_net,
             out_pcs, out_gross, out_net,
             c_pcs, c_gross, c_net,
             avg_inv, turnover_ratio, dio,
             min_stock, stock_gap, ageing) = row

            attr = tmpl_attr_map.get(tmpl_id, {})
            report_lines.append({
                'product_id':            product_id,
                'product_template_id':   tmpl_id,
                'label_id':              label_id,
                'purity_id':             purity_id,
                'opening_pcs':           float(o_pcs or 0),
                'opening_gross_weight':  float(o_gross or 0),
                'opening_net_weight':    float(o_net or 0),
                'in_pcs':                float(in_pcs or 0),
                'in_gross_weight':       float(in_gross or 0),
                'in_net_weight':         float(in_net or 0),
                'out_pcs':               float(out_pcs or 0),
                'out_gross_weight':      float(out_gross or 0),
                'out_net_weight':        float(out_net or 0),
                'closing_pcs':           float(c_pcs or 0),
                'closing_gross_weight':  float(c_gross or 0),
                'closing_net_weight':    float(c_net or 0),
                'average_inventory':     float(avg_inv or 0),
                'no_of_days':            no_of_days,
                'min_stock_level':       float(min_stock or 0),
                'turnover_ratio':        float(turnover_ratio or 0),
                'dio':                   float(dio or 0),
                'stock_gap':             float(stock_gap or 0),
                'ageing':                int(ageing or 0),
                'type_value':            attr.get('type', attr.get('item type', attr.get('product type', ''))),
                'variety_value':         attr.get('variety', attr.get('verity', '')),
                'design_value':          attr.get('design', ''),
                'size_value':            attr.get('size', ''),
                'stone_colour_value':    attr.get('stone colour', attr.get('stone color', '')),
                'metal_colour_value':    attr.get('metal colour', attr.get('metal color', '')),
            })

        for row in no_label_rows:
            (product_id, tmpl_id, purity_id,
             o_pcs, o_gross, o_net,
             out_pcs, out_gross, out_net,
             min_stock) = row

            o_pcs    = float(o_pcs or 0)
            o_gross  = float(o_gross or 0)
            o_net    = float(o_net or 0)
            out_pcs  = float(out_pcs or 0)
            out_gross = float(out_gross or 0)
            out_net  = float(out_net or 0)
            min_stock = float(min_stock or 0)

            c_gross  = o_gross - out_gross
            c_net    = o_net   - out_net
            c_pcs    = o_pcs   - out_pcs

            avg_inv = (o_gross + c_gross) / 2.0
            if avg_inv <= 0.0 and out_gross > 0.0:
                avg_inv = out_gross / 4.0
            turnover_ratio = (out_gross / avg_inv) if avg_inv > 0.0001 else 0.0
            dio = (
                round(no_of_days / turnover_ratio) if turnover_ratio > 0.0001
                else (no_of_days if avg_inv > 0.0001 else 0.0)
            )

            if not any([o_pcs, o_gross, out_pcs, out_gross, c_pcs, c_gross, min_stock]):
                continue

            attr = tmpl_attr_map.get(tmpl_id, {})
            report_lines.append({
                'product_id':            product_id,
                'product_template_id':   tmpl_id,
                'label_id':              False,
                'purity_id':             purity_id,
                'opening_pcs':           o_pcs,
                'opening_gross_weight':  o_gross,
                'opening_net_weight':    o_net,
                'in_pcs':                0.0,
                'in_gross_weight':       0.0,
                'in_net_weight':         0.0,
                'out_pcs':               out_pcs,
                'out_gross_weight':      out_gross,
                'out_net_weight':        out_net,
                'closing_pcs':           c_pcs,
                'closing_gross_weight':  c_gross,
                'closing_net_weight':    c_net,
                'average_inventory':     avg_inv,
                'no_of_days':            no_of_days,
                'min_stock_level':       min_stock,
                'turnover_ratio':        turnover_ratio,
                'dio':                   float(dio),
                'stock_gap':             c_gross - min_stock,
                'ageing':                0,
                'type_value':            attr.get('type', attr.get('item type', attr.get('product type', ''))),
                'variety_value':         attr.get('variety', attr.get('verity', '')),
                'design_value':          attr.get('design', ''),
                'size_value':            attr.get('size', ''),
                'stone_colour_value':    attr.get('stone colour', attr.get('stone color', '')),
                'metal_colour_value':    attr.get('metal colour', attr.get('metal color', '')),
            })

        # ── 9. Batch insert ─────────────────────────────────────────────
        if report_lines:
            self.env['stock.summary.report.line'].sudo().create(report_lines)

        return self._action_result()

    def action_print_xlsx(self):
        self.ensure_one()
        self.action_generate_report()
        branch_names = ', '.join(self.branch_ids.mapped('name')) if self.branch_ids else 'All Branches'
        return {
            'type': 'ir.actions.act_url',
            'url': (
                f'/metal_ledger/export_stock_summary'
                f'?start_date={self.start_date}'
                f'&end_date={self.end_date}'
                f'&branch_name={branch_names}'
            ),
            'target': 'new',
        }


class StockSummaryReportLine(models.TransientModel):
    _name = 'stock.summary.report.line'
    _description = 'Stock Summary Report Line'

    product_id = fields.Many2one('product.product', string='Product Variant')
    product_template_id = fields.Many2one('product.template', string='Product')
    label_id = fields.Many2one('product.label', string='Label')
    purity_id = fields.Many2one('gold.purity', string='Purity')
    ageing = fields.Integer(string='Ageing')
    opening_pcs = fields.Float(string='Opening PCs', digits=(16, 0))
    opening_gross_weight = fields.Float(string='Opening Gross', digits=(16, 3))
    opening_net_weight = fields.Float(string='Opening Net', digits=(16, 3))

    in_pcs = fields.Float(string='In PCs', digits=(16, 0))
    in_gross_weight = fields.Float(string='In Gross', digits=(16, 3))
    in_net_weight = fields.Float(string='In Net', digits=(16, 3))

    out_pcs = fields.Float(string='Out PCs', digits=(16, 0))
    out_gross_weight = fields.Float(string='Out Gross', digits=(16, 3))
    out_net_weight = fields.Float(string='Out Net', digits=(16, 3))

    closing_pcs = fields.Float(string='Closing PCs', digits=(16, 0))
    closing_gross_weight = fields.Float(string='Closing Gross', digits=(16, 3))
    closing_net_weight = fields.Float(string='Closing Net', digits=(16, 3))

    average_inventory = fields.Float(string='Avg Inventory', digits=(16, 3))
    no_of_days = fields.Integer(string='No. of Days')
    min_stock_level = fields.Float(string='Min Stock', digits=(16, 3))
    turnover_ratio = fields.Float(string='Turnover Ratio', digits=(16, 2))
    dio = fields.Float(string='DIO', digits=(16, 0))
    stock_gap = fields.Float(string='Stock Gap', digits=(16, 3))
    type_value = fields.Char(string="Type")
    variety_value = fields.Char(string="Variety")
    design_value = fields.Char(string="Design")
    size_value = fields.Char(string="Size")
    stone_colour_value = fields.Char(string="Stone Colour")
    metal_colour_value = fields.Char(string="Metal Colour")
