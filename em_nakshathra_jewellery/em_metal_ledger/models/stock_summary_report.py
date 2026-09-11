from odoo import models, fields, api, _
from datetime import datetime


class StockSummaryReportWizard(models.TransientModel):
    _name = 'stock.summary.report.wizard'
    _description = 'Stock Summary Report Wizard'

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True, default=fields.Date.today)
    branch_ids = fields.Many2many('res.branch', string='Branches')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _open_report_view(self):
        return {
            'name': _('Stock Summary Report'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.summary.report.line',
            'view_mode': 'tree',
            'context': {'search_default_group_by_product': 1},
        }

    def _ensure_indexes(self):
        """
        Create performance indexes for Stock Summary Report queries.
        Uses IF NOT EXISTS — safe to call on every run, only creates once.
        Each index targets a specific WHERE / JOIN column used in our SQL.
        """
        cr = self.env.cr
        indexes = [
            # ── stock_move ─────────────────────────────────────────────
            # Core filter: state='done' + date range
            ("idx_ssrpt_sm_state_date",
             "stock_move (state, date)"),
            # JOIN / filter on label
            ("idx_ssrpt_sm_label_id",
             "stock_move (label_id) WHERE label_id IS NOT NULL"),
            # JOIN / filter on product
            ("idx_ssrpt_sm_product_id",
             "stock_move (product_id)"),
            # Location filters (IN / OUT detection)
            ("idx_ssrpt_sm_location_id",
             "stock_move (location_id)"),
            ("idx_ssrpt_sm_location_dest_id",
             "stock_move (location_dest_id)"),
            # Composite: covers the main move query completely
            ("idx_ssrpt_sm_state_date_prod",
             "stock_move (state, date, product_id) WHERE state = 'done'"),

            # ── product_label ──────────────────────────────────────────
            # Opening-stock label lookup (created before period)
            ("idx_ssrpt_pl_create_date",
             "product_label (create_date)"),
            # active=True filter for pre-period labels
            ("idx_ssrpt_pl_active_create",
             "product_label (create_date) WHERE active = TRUE"),
            # Branch filter
            ("idx_ssrpt_pl_branch_id",
             "product_label (branch_id) WHERE branch_id IS NOT NULL"),
            # Product grouping
            ("idx_ssrpt_pl_product_id",
             "product_label (product_id) WHERE product_id IS NOT NULL"),

            # ── sale_order_line ────────────────────────────────────────
            # label_id lookup (sold-before / sold-in-period checks)
            ("idx_ssrpt_sol_label_state",
             "sale_order_line (label_id, state) WHERE label_id IS NOT NULL"),
            # order_id JOIN
            ("idx_ssrpt_sol_order_id",
             "sale_order_line (order_id)"),

            # ── sale_order ─────────────────────────────────────────────
            # date_order range filter
            ("idx_ssrpt_so_date_order",
             "sale_order (date_order)"),
            # Branch filter on sale order
            ("idx_ssrpt_so_branch_id",
             "sale_order (branch_id) WHERE branch_id IS NOT NULL"),

            # ── stock_location ─────────────────────────────────────────
            ("idx_ssrpt_sl_usage_branch",
             "stock_location (usage, branch_id)"),

            # ── stock_warehouse_orderpoint ─────────────────────────────
            ("idx_ssrpt_swop_loc_prod",
             "stock_warehouse_orderpoint (location_id, product_id)"),

            # ── product_template_attribute_value ──────────────────────
            ("idx_ssrpt_ptav_tmpl_id",
             "product_template_attribute_value (product_tmpl_id)"),
        ]

        for idx_name, definition in indexes:
            cr.execute(
                "SELECT 1 FROM pg_indexes WHERE indexname = %s",
                (idx_name,)
            )
            if not cr.fetchone():
                try:
                    cr.execute(
                        f"CREATE INDEX IF NOT EXISTS {idx_name} ON {definition}"
                    )
                except Exception:
                    pass  # Non-fatal: skip if already exists or permission issue

    # ------------------------------------------------------------------
    # Main report generation - fully SQL-based for maximum performance
    # ------------------------------------------------------------------
    def action_generate_report(self):
        self.ensure_one()
        cr = self.env.cr

        # Create indexes on first run (no-op if already exist)
        self._ensure_indexes()

        # Delete previous lines for this user
        cr.execute(
            "DELETE FROM stock_summary_report_line WHERE create_uid = %s",
            (self.env.user.id,)
        )

        start_dt = datetime.combine(self.start_date, datetime.min.time())
        end_dt   = datetime.combine(self.end_date,   datetime.max.time())
        no_of_days = (self.end_date - self.start_date).days + 1

        # ---- Internal locations ----------------------------------------
        loc_sql  = "SELECT id FROM stock_location WHERE usage = 'internal'"
        loc_args = []
        if self.branch_ids:
            loc_sql += " AND branch_id = ANY(%s)"
            loc_args.append(self.branch_ids.ids)
        cr.execute(loc_sql, loc_args)
        internal_loc_ids = [r[0] for r in cr.fetchall()]
        if not internal_loc_ids:
            return self._open_report_view()

        # ---- Branch filter fragments ------------------------------------
        sol_branch = ""
        sol_branch_args = []
        if self.branch_ids:
            sol_branch = "AND so.branch_id = ANY(%s)"
            sol_branch_args = [self.branch_ids.ids]

        # ---- Labels created inside the period --------------------------
        if self.branch_ids:
            cr.execute(
                """
                SELECT pl.id FROM product_label pl
                WHERE pl.create_date >= %s AND pl.create_date <= %s
                  AND (pl.branch_location_id = ANY(%s) OR (pl.branch_location_id IS NULL AND pl.branch_id = ANY(%s)))
                """,
                [start_dt, end_dt, internal_loc_ids, self.branch_ids.ids]
            )
        else:
            cr.execute(
                """
                SELECT pl.id FROM product_label pl
                WHERE pl.create_date >= %s AND pl.create_date <= %s
                """,
                [start_dt, end_dt]
            )
        created_in_period_ids = {r[0] for r in cr.fetchall()}

        # ---- Labels active before the period start in selected locations ----
        cr.execute(
            """
            SELECT sm.label_id
            FROM stock_move sm
            WHERE sm.state = 'done'
              AND sm.date < %s
              AND sm.label_id IS NOT NULL
              AND (sm.location_id = ANY(%s) OR sm.location_dest_id = ANY(%s))
            GROUP BY sm.label_id
            HAVING SUM(CASE WHEN sm.location_dest_id = ANY(%s) THEN 1 WHEN sm.location_id = ANY(%s) THEN -1 ELSE 0 END) > 0
            """,
            [start_dt, internal_loc_ids, internal_loc_ids, internal_loc_ids, internal_loc_ids]
        )
        active_before_ids = {r[0] for r in cr.fetchall()}

        # Labels created before start_dt with NO moves that belong to these locations
        if self.branch_ids:
            cr.execute(
                """
                SELECT pl.id FROM product_label pl
                LEFT JOIN stock_move sm ON sm.label_id = pl.id
                WHERE pl.create_date < %s AND pl.active = TRUE
                  AND sm.id IS NULL
                  AND (pl.branch_location_id = ANY(%s) OR (pl.branch_location_id IS NULL AND pl.branch_id = ANY(%s)))
                """,
                [start_dt, internal_loc_ids, self.branch_ids.ids]
            )
        else:
            cr.execute(
                """
                SELECT pl.id FROM product_label pl
                LEFT JOIN stock_move sm ON sm.label_id = pl.id
                WHERE pl.create_date < %s AND pl.active = TRUE
                  AND sm.id IS NULL
                """,
                [start_dt]
            )
        active_before_ids |= {r[0] for r in cr.fetchall()}

        # ---- Labels moved in period (only touching selected locations) --
        cr.execute(
            """
            SELECT DISTINCT sm.label_id
            FROM stock_move sm
            WHERE sm.state = 'done'
              AND sm.date >= %s AND sm.date <= %s
              AND sm.label_id IS NOT NULL
              AND (sm.location_id = ANY(%s) OR sm.location_dest_id = ANY(%s))
            """,
            [start_dt, end_dt, internal_loc_ids, internal_loc_ids]
        )
        moved_label_ids = {r[0] for r in cr.fetchall()}

        # ---- Labels sold in period -------------------------------------
        cr.execute(
            """
            SELECT DISTINCT sol.label_id
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            WHERE sol.state IN ('sale','done')
              AND sol.label_id IS NOT NULL
              AND so.date_order >= %s AND so.date_order <= %s
            """ + sol_branch,
            [start_dt, end_dt] + sol_branch_args
        )
        sold_label_ids_period = {r[0] for r in cr.fetchall()}

        active_label_ids = list(
            created_in_period_ids | active_before_ids |
            moved_label_ids       | sold_label_ids_period
        )

        # ---- Product IDs from active labels + unlabelled moves in locations ---
        prod_id_set = set()
        if active_label_ids:
            cr.execute(
                "SELECT DISTINCT product_id FROM product_label WHERE id = ANY(%s) AND product_id IS NOT NULL",
                [active_label_ids]
            )
            prod_id_set.update(r[0] for r in cr.fetchall())

        cr.execute(
            """
            SELECT DISTINCT product_id FROM stock_move
            WHERE state = 'done' AND date <= %s AND label_id IS NULL
              AND (location_id = ANY(%s) OR location_dest_id = ANY(%s))
            """,
            [end_dt, internal_loc_ids, internal_loc_ids]
        )
        prod_id_set.update(r[0] for r in cr.fetchall())
        relevant_product_ids = list(prod_id_set)
        if not relevant_product_ids:
            return self._open_report_view()

        # ---- All stock moves (one query, fetched into dicts) -----------
        cr.execute(
            """
            SELECT
                sm.id,
                sm.label_id,
                sm.product_id,
                sm.location_id,
                sm.location_dest_id,
                sm.date,
                sm.product_uom_qty,
                COALESCE(sm.grams, 0)         AS grams,
                sm.purity_id,
                COALESCE(
                    uom_cat.name->>'en_US',
                    uom_cat.name->>'en_GB',
                    uom_cat.name::text
                )                             AS uom_cat_name,
                pl.purchase_gross_weight      AS label_gross,
                pl.purchase_net_weight        AS label_net,
                pl_purity.percentage          AS label_purity_pct,
                p_purity.percentage           AS product_purity_pct,
                move_purity.percentage        AS move_purity_pct
            FROM stock_move sm
            JOIN uom_uom uom ON uom.id = sm.product_uom
            JOIN uom_category uom_cat ON uom_cat.id = uom.category_id
            LEFT JOIN product_label pl ON pl.id = sm.label_id
            LEFT JOIN gold_purity pl_purity ON pl_purity.id = pl.purity_id
            LEFT JOIN product_product pp ON pp.id = sm.product_id
            LEFT JOIN gold_purity p_purity ON p_purity.id = pp.purity_id
            LEFT JOIN gold_purity move_purity ON move_purity.id = sm.purity_id
            WHERE sm.state = 'done'
              AND sm.date <= %s
              AND sm.product_id = ANY(%s)
              AND (sm.label_id = ANY(%s) OR sm.label_id IS NULL)
              AND (sm.location_id = ANY(%s) OR sm.location_dest_id = ANY(%s))
            ORDER BY sm.date ASC, sm.id ASC
            """,
            [end_dt, relevant_product_ids, active_label_ids if active_label_ids else [0],
             internal_loc_ids, internal_loc_ids]
        )
        move_cols = [
            'id', 'label_id', 'product_id', 'location_id', 'location_dest_id',
            'date', 'product_uom_qty', 'grams', 'purity_id', 'uom_cat_name',
            'label_gross', 'label_net', 'label_purity_pct',
            'product_purity_pct', 'move_purity_pct'
        ]
        loc_set = set(internal_loc_ids)
        moves_by_label   = {}   # label_id -> [move_dict]
        moves_by_product = {}   # product_id -> [move_dict]  (no-label moves)
        for row in cr.fetchall():
            m = dict(zip(move_cols, row))
            if m['label_id']:
                moves_by_label.setdefault(m['label_id'], []).append(m)
            else:
                moves_by_product.setdefault(m['product_id'], []).append(m)

        # ---- Labels metadata -------------------------------------------
        labels_by_id = {}
        labels_by_product = {}
        if active_label_ids:
            cr.execute(
                """
                SELECT pl.id, pl.product_id, pl.create_date,
                       pl.purchase_gross_weight, pl.purchase_net_weight,
                       COALESCE(pl.age_import, 0) AS age_import,
                       pl.purity_id, pl.branch_id, pl.branch_location_id
                FROM product_label pl
                WHERE pl.id = ANY(%s)
                """,
                [active_label_ids]
            )
            label_cols = ['id', 'product_id', 'create_date', 'gross', 'net', 'age_import', 'purity_id', 'branch_id', 'branch_location_id']
            for row in cr.fetchall():
                lbl = dict(zip(label_cols, row))
                labels_by_id[lbl['id']] = lbl
                if lbl['product_id']:
                    labels_by_product.setdefault(lbl['product_id'], []).append(lbl['id'])

        # ---- Labels sold BEFORE period ---------------------------------
        sold_before_label_ids = set()
        if active_label_ids:
            cr.execute(
                """
                SELECT DISTINCT sol.label_id
                FROM sale_order_line sol
                JOIN sale_order so ON so.id = sol.order_id
                WHERE sol.state IN ('sale','done')
                  AND sol.label_id = ANY(%s)
                  AND so.date_order < %s
                """,
                [active_label_ids, start_dt]
            )
            sold_before_label_ids = {r[0] for r in cr.fetchall()}

        # ---- Min stock rules -------------------------------------------
        cr.execute(
            """
            SELECT product_id, MIN(product_min_qty)
            FROM stock_warehouse_orderpoint
            WHERE location_id = ANY(%s)
              AND product_id = ANY(%s)
            GROUP BY product_id
            """,
            [internal_loc_ids, relevant_product_ids]
        )
        min_stock_by_product = {r[0]: r[1] for r in cr.fetchall()}

        # ---- Product attribute values ----------------------------------
        cr.execute(
            """
            SELECT
                pp.id AS product_id,
                COALESCE(
                    pa.name->>'en_US',
                    pa.name->>'en_GB',
                    pa.name::text
                ) AS attr_name,
                COALESCE(
                    pav.name->>'en_US',
                    pav.name->>'en_GB',
                    pav.name::text
                ) AS attr_value
            FROM product_product pp
            JOIN product_template_attribute_value ptav
                  ON ptav.product_tmpl_id = pp.product_tmpl_id
            JOIN product_attribute_value pav
                  ON pav.id = ptav.product_attribute_value_id
            JOIN product_attribute pa
                  ON pa.id = pav.attribute_id
            WHERE pp.id = ANY(%s)
              AND pp.active = TRUE
            """,
            [relevant_product_ids]
        )

        def _extract_str(val):
            """Safely extract a plain string from a possibly-jsonb translated field value."""
            if isinstance(val, dict):
                return (val.get('en_US') or val.get('en_GB') or next(iter(val.values()), '')) or ''
            return (val or '')

        attr_by_product = {}
        for prod_id, attr_name, attr_value in cr.fetchall():
            name_str = _extract_str(attr_name).strip().lower()
            val_str  = _extract_str(attr_value)
            attr_by_product.setdefault(prod_id, {})[name_str] = val_str

        # ---- Product purity + template ---------------------------------
        cr.execute(
            """
            SELECT pp.id, gp.id AS purity_id, pp.product_tmpl_id
            FROM product_product pp
            LEFT JOIN gold_purity gp ON gp.id = pp.purity_id
            WHERE pp.id = ANY(%s) AND pp.active = TRUE
            """,
            [relevant_product_ids]
        )
        product_meta = {}   # product_id -> {purity_id, product_tmpl_id}
        active_product_ids = []
        for row in cr.fetchall():
            product_meta[row[0]] = {'purity_id': row[1], 'product_tmpl_id': row[2]}
            active_product_ids.append(row[0])

        today_date = fields.Date.today()

        # ================================================================
        # Helper: compute stats from a list of move-dicts
        # ================================================================
        def get_stats(move_list, mode='in'):
            pcs = gross = net = 0.0
            for m in move_list:
                dest_in = m['location_dest_id'] in loc_set
                src_in  = m['location_id']      in loc_set

                if mode == 'opening':
                    coef = (1 if dest_in else 0) - (1 if src_in else 0)
                elif mode == 'in':
                    coef = 1 if (dest_in and not src_in) else 0
                elif mode == 'out':
                    coef = 1 if (src_in and not dest_in) else 0
                else:
                    coef = 0

                if coef == 0:
                    continue

                if m['label_id']:
                    m_pcs   = 1.0
                    m_gross = m['label_gross'] or 0.0
                    m_net   = m['label_net']   or 0.0
                else:
                    cat     = m['uom_cat_name'] or ''
                    m_pcs   = m['product_uom_qty'] if cat in ('Unit', 'Working Time') else 0.0
                    m_gross = m['grams'] or (m['product_uom_qty'] if cat == 'Weight' else 0.0)
                    pct     = m['move_purity_pct'] or m['product_purity_pct'] or 0.0
                    m_net   = m_gross * (pct / 100.0) if pct else m_gross

                pcs   += m_pcs   * coef
                gross += m_gross * coef
                net   += m_net   * coef
            return pcs, gross, net

        # ================================================================
        # Build report lines
        # ================================================================
        report_lines = []
        create_uid   = self.env.user.id
        now_str      = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for prod_id in active_product_ids:
            amap          = attr_by_product.get(prod_id, {})
            label_ids_for = labels_by_product.get(prod_id, [])
            no_label_mvs  = moves_by_product.get(prod_id, [])
            meta          = product_meta.get(prod_id, {})

            labels_to_process = list(label_ids_for)
            if no_label_mvs or not labels_to_process:
                labels_to_process.append(None)

            type_val  = amap.get('type',        amap.get('item type',   amap.get('product type', '')))
            variety   = amap.get('variety',      amap.get('verity',      ''))
            design    = amap.get('design',       '')
            size      = amap.get('size',         '')
            stone_col = amap.get('stone colour', amap.get('stone color', ''))
            metal_col = amap.get('metal colour', amap.get('metal color', ''))

            for label_id in labels_to_process:
                lbl         = labels_by_id.get(label_id) if label_id else None
                label_moves = moves_by_label.get(label_id, []) if label_id else no_label_mvs

                opening_moves = [m for m in label_moves if m['date'] < start_dt]
                period_moves  = [m for m in label_moves if m['date'] >= start_dt]

                # ---- Opening, In, Out, Closing stock ----
                if lbl:
                    gross = lbl['gross'] or 0.0
                    net   = lbl['net']   or 0.0

                    # 1. Opening stock for label
                    if opening_moves:
                        last_op_move = opening_moves[-1]
                        o_pcs = 1.0 if last_op_move['location_dest_id'] in loc_set else 0.0
                    else:
                        created_before = lbl['create_date'] and lbl['create_date'] < start_dt
                        in_branch = (lbl.get('branch_location_id') in loc_set) or (
                            not lbl.get('branch_location_id') and (not self.branch_ids or lbl.get('branch_id') in self.branch_ids.ids)
                        )
                        if created_before and in_branch and not moves_by_label.get(label_id) and (label_id not in sold_before_label_ids):
                            o_pcs = 1.0
                        else:
                            o_pcs = 0.0

                    # 2. Closing stock for label
                    if label_moves:
                        last_move = label_moves[-1]
                        c_pcs = 1.0 if (last_move['location_dest_id'] in loc_set and label_id not in sold_label_ids_period) else 0.0
                    else:
                        in_branch = (lbl.get('branch_location_id') in loc_set) or (
                            not lbl.get('branch_location_id') and (not self.branch_ids or lbl.get('branch_id') in self.branch_ids.ids)
                        )
                        if in_branch and (label_id not in sold_before_label_ids) and (label_id not in sold_label_ids_period):
                            c_pcs = 1.0
                        else:
                            c_pcs = 0.0

                    # 3. In and Out flow for label
                    if o_pcs == 1.0 and c_pcs == 1.0:
                        in_pcs  = 0.0
                        out_pcs = 0.0
                    elif o_pcs == 0.0 and c_pcs == 1.0:
                        in_pcs  = 1.0
                        out_pcs = 0.0
                    elif o_pcs == 1.0 and c_pcs == 0.0:
                        in_pcs  = 0.0
                        out_pcs = 1.0
                    else:  # o_pcs == 0.0 and c_pcs == 0.0
                        entered = any(m['location_dest_id'] in loc_set and m['location_id'] not in loc_set for m in period_moves)
                        if entered or (label_id in sold_label_ids_period):
                            in_pcs  = 1.0
                            out_pcs = 1.0
                        else:
                            in_pcs  = 0.0
                            out_pcs = 0.0

                    o_gross,   o_net   = (gross * o_pcs,   net * o_pcs)
                    in_gross,  in_net  = (gross * in_pcs,  net * in_pcs)
                    out_gross, out_net = (gross * out_pcs, net * out_pcs)
                    c_gross,   c_net   = (gross * c_pcs,   net * c_pcs)

                else:
                    o_pcs,   o_gross,   o_net   = get_stats(opening_moves, mode='opening')
                    in_pcs,  in_gross,  in_net  = get_stats(period_moves,  mode='in')
                    out_pcs, out_gross, out_net = get_stats(period_moves,  mode='out')
                    c_pcs   = max(0.0, o_pcs   + in_pcs   - out_pcs)
                    c_gross = max(0.0, o_gross + in_gross - out_gross)
                    c_net   = max(0.0, o_net   + in_net   - out_net)

                avg_inv  = (o_gross + c_gross) / 2.0
                if avg_inv <= 0.0 and (in_gross > 0.0 or out_gross > 0.0):
                    avg_inv = (in_gross + out_gross) / 4.0
                turnover = (out_gross / avg_inv) if avg_inv > 0.0001 else 0.0
                dio      = round(no_of_days / turnover) if turnover > 0.0001 else (no_of_days if avg_inv > 0.0001 else 0.0)

                min_stock = min_stock_by_product.get(prod_id, 0.0)
                stock_gap = c_gross - min_stock

                purity_id = (
                    (lbl['purity_id'] if lbl and lbl['purity_id'] else None) or
                    meta.get('purity_id')
                )

                if lbl:
                    days_since = (today_date - lbl['create_date'].date()).days if lbl['create_date'] else 0
                    age_imp    = lbl['age_import'] or 0
                    ageing     = (age_imp + days_since) if age_imp != 0 else (days_since + 1)
                else:
                    ageing = 0

                if not any([o_pcs, o_gross, o_net,
                            in_pcs, in_gross, in_net,
                            out_pcs, out_gross, out_net,
                            c_pcs, c_gross, c_net, min_stock]):
                    continue

                report_lines.append((
                    prod_id,
                    meta.get('product_tmpl_id'),
                    label_id,
                    purity_id,
                    ageing,
                    o_pcs,   o_gross,   o_net,
                    in_pcs,  in_gross,  in_net,
                    out_pcs, out_gross, out_net,
                    c_pcs,   c_gross,   c_net,
                    avg_inv, no_of_days, min_stock,
                    turnover, dio, stock_gap,
                    type_val, variety, design, size, stone_col, metal_col,
                    create_uid, create_uid, now_str, now_str,
                ))

        # ================================================================
        # Bulk insert via executemany (fastest possible)
        # ================================================================
        if report_lines:
            cr.executemany(
                """
                INSERT INTO stock_summary_report_line (
                    product_id, product_template_id, label_id, purity_id,
                    ageing,
                    opening_pcs,  opening_gross_weight,  opening_net_weight,
                    in_pcs,       in_gross_weight,       in_net_weight,
                    out_pcs,      out_gross_weight,      out_net_weight,
                    closing_pcs,  closing_gross_weight,  closing_net_weight,
                    average_inventory, no_of_days, min_stock_level,
                    turnover_ratio, dio, stock_gap,
                    type_value, variety_value, design_value, size_value,
                    stone_colour_value, metal_colour_value,
                    create_uid, write_uid, create_date, write_date
                ) VALUES (
                    %s, %s, %s, %s,
                    %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s
                )
                """,
                report_lines
            )

        return self._open_report_view()

    def action_print_xlsx(self):
        self.ensure_one()
        self.action_generate_report()
        branch_names = ', '.join(self.branch_ids.mapped('name')) if self.branch_ids else 'All Branches'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/metal_ledger/export_stock_summary?start_date={self.start_date}&end_date={self.end_date}&branch_name={branch_names}',
            'target': 'self',
        }

    def action_print_grouped_xlsx(self):
        self.ensure_one()
        self.action_generate_report()
        branch_names = ', '.join(self.branch_ids.mapped('name')) if self.branch_ids else 'All Branches'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/metal_ledger/export_stock_summary_grouped?start_date={self.start_date}&end_date={self.end_date}&branch_name={branch_names}',
            'target': 'self',
        }


class StockSummaryReportLine(models.TransientModel):
    _name = 'stock.summary.report.line'
    _description = 'Stock Summary Report Line'

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        res = super(StockSummaryReportLine, self).read_group(
            domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy
        )
        for line_data in res:
            o_gross   = line_data.get('opening_gross_weight', 0.0) or 0.0
            c_gross   = line_data.get('closing_gross_weight', 0.0) or 0.0
            out_gross = line_data.get('out_gross_weight',     0.0) or 0.0
            min_stock = line_data.get('min_stock_level',      0.0) or 0.0
            no_days   = line_data.get('no_of_days',           0)   or 0

            avg_inv  = (o_gross + c_gross) / 2.0
            if avg_inv <= 0.0 and out_gross > 0.0:
                avg_inv = out_gross / 4.0

            turnover = (out_gross / avg_inv) if avg_inv > 0.0001 else 0.0
            dio_val  = round(no_days / turnover) if turnover > 0.0001 else (no_days if avg_inv > 0.0001 else 0)
            gap      = c_gross - min_stock

            if 'average_inventory' in fields or 'average_inventory' in line_data:
                line_data['average_inventory'] = avg_inv
            if 'turnover_ratio' in fields or 'turnover_ratio' in line_data:
                line_data['turnover_ratio'] = turnover
            if 'dio' in fields or 'dio' in line_data:
                line_data['dio'] = dio_val
            if 'stock_gap' in fields or 'stock_gap' in line_data:
                line_data['stock_gap'] = gap

        return res

    product_id          = fields.Many2one('product.product',  string='Product Variant')
    product_template_id = fields.Many2one('product.template', string='Product')
    label_id            = fields.Many2one('product.label',    string='Label')
    purity_id           = fields.Many2one('gold.purity',      string='Purity')
    ageing              = fields.Integer(string='Ageing')

    opening_pcs          = fields.Float(string='Opening PCs',    digits=(16, 0))
    opening_gross_weight = fields.Float(string='Opening Gross',  digits=(16, 3))
    opening_net_weight   = fields.Float(string='Opening Net',    digits=(16, 3))

    in_pcs          = fields.Float(string='In PCs',   digits=(16, 0))
    in_gross_weight = fields.Float(string='In Gross', digits=(16, 3))
    in_net_weight   = fields.Float(string='In Net',   digits=(16, 3))

    out_pcs          = fields.Float(string='Out PCs',   digits=(16, 0))
    out_gross_weight = fields.Float(string='Out Gross', digits=(16, 3))
    out_net_weight   = fields.Float(string='Out Net',   digits=(16, 3))

    closing_pcs          = fields.Float(string='Closing PCs',   digits=(16, 0))
    closing_gross_weight = fields.Float(string='Closing Gross', digits=(16, 3))
    closing_net_weight   = fields.Float(string='Closing Net',   digits=(16, 3))

    average_inventory = fields.Float(string='Avg Inventory',  digits=(16, 3))
    no_of_days        = fields.Integer(string='No. of Days',  group_operator='avg')
    min_stock_level   = fields.Float(string='Min Stock',      digits=(16, 3))
    turnover_ratio    = fields.Float(string='Turnover Ratio', digits=(16, 2))
    dio               = fields.Float(string='DIO',            digits=(16, 0))
    stock_gap         = fields.Float(string='Stock Gap',      digits=(16, 3))

    type_value         = fields.Char(string='Type')
    variety_value      = fields.Char(string='Variety')
    design_value       = fields.Char(string='Design')
    size_value         = fields.Char(string='Size')
    stone_colour_value = fields.Char(string='Stone Colour')
    metal_colour_value = fields.Char(string='Metal Colour')
