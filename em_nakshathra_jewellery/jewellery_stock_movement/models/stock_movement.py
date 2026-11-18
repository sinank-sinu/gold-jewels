# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StockMovementReport(models.Model):
    """Dynamic Opening / In / Out / Closing stock movement report.

    Rows are regenerated per user by :meth:`compute_report_data` for the
    selected branch, warehouse, location and date range.

    * Opening  = net movement (in - out) of done moves strictly before Date From
    * In / Out = moves entering / leaving the scope between Date From and Date To
    * Closing  = Opening + In - Out
    """
    _name = 'stock.movement.report'
    _description = 'Stock Movement Report (Opening / Closing)'
    _order = 'product_tmpl_id asc, product_id asc'

    branch_id = fields.Many2one('res.branch', string='Branch', readonly=True, index=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', readonly=True, index=True)
    product_tmpl_id = fields.Many2one('product.template', string='Product', readonly=True, index=True)
    product_id = fields.Many2one('product.product', string='Variant / Product', readonly=True, index=True)
    categ_id = fields.Many2one('product.category', string='Category', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', readonly=True)

    opening_qty = fields.Float(string='Opening Qty', digits=(16, 3), readonly=True)
    opening_weight = fields.Float(string='Opening Wt (g)', digits=(16, 3), readonly=True)
    qty_in = fields.Float(string='In Qty', digits=(16, 3), readonly=True)
    weight_in = fields.Float(string='In Wt (g)', digits=(16, 3), readonly=True)
    qty_out = fields.Float(string='Out Qty', digits=(16, 3), readonly=True)
    weight_out = fields.Float(string='Out Wt (g)', digits=(16, 3), readonly=True)
    closing_qty = fields.Float(string='Closing Qty', digits=(16, 3), readonly=True)
    closing_weight = fields.Float(string='Closing Wt (g)', digits=(16, 3), readonly=True)

    # ------------------------------------------------------------------
    # Access helpers
    # ------------------------------------------------------------------
    def _is_admin_user(self):
        user = self.env.user
        return user._is_admin() or user.has_group('base.group_erp_manager')

    def _get_allowed_branch_ids(self):
        """None = every branch allowed (administrators)."""
        if self._is_admin_user():
            return None
        user = self.env.user
        if user.branch_ids:
            return user.branch_ids.ids
        if user.branch_id:
            return [user.branch_id.id]
        return []

    @api.model
    def get_filter_options(self):
        """Branches / warehouses / locations available to the current user."""
        allowed = self._get_allowed_branch_ids()
        branch_domain = [] if allowed is None else [('id', 'in', allowed)]
        branches = self.env['res.branch'].search_read(branch_domain, ['id', 'name'], order='name asc')

        wh_domain = [('company_id', 'in', self.env.companies.ids)]
        if allowed is not None:
            wh_domain.append(('branch_id', 'in', allowed))
        warehouses = self.env['stock.warehouse'].search_read(
            wh_domain, ['id', 'name', 'code', 'branch_id'], order='name asc')

        locations = self.env['stock.location'].search_read(
            [('usage', '=', 'internal'),
             ('warehouse_id', 'in', [w['id'] for w in warehouses])],
            ['id', 'complete_name', 'warehouse_id'], order='complete_name asc')

        default_branch = False
        if allowed is not None and len(branches) == 1:
            default_branch = branches[0]['id']
        elif self.env.user.branch_id and any(b['id'] == self.env.user.branch_id.id for b in branches):
            default_branch = self.env.user.branch_id.id

        return {
            'branches': branches,
            'warehouses': [{
                'id': w['id'], 'name': w['name'], 'code': w['code'],
                'branch_id': w['branch_id'][0] if w['branch_id'] else False,
            } for w in warehouses],
            'locations': [{
                'id': l['id'], 'name': l['complete_name'],
                'warehouse_id': l['warehouse_id'][0] if l['warehouse_id'] else False,
            } for l in locations],
            'default_branch_id': default_branch,
            'branch_locked': allowed is not None and len(branches) <= 1,
        }

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------
    def _to_utc_bound(self, date_str, end_of_day=False):
        """Convert a local 'YYYY-MM-DD' (user tz) into a naive UTC datetime bound."""
        day = fields.Date.to_date(date_str)
        if end_of_day:
            day = day + timedelta(days=1)  # exclusive upper bound
        tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
        local_dt = tz.localize(datetime.combine(day, time.min))
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)

    @staticmethod
    def _to_int(value):
        if value in (False, None, '', 'all'):
            return False
        return int(value)

    @api.model
    def compute_report_data(self, branch_id=False, warehouse_id=False, location_id=False,
                            date_from=False, date_to=False):
        """Regenerate the current user's report rows and return KPI totals."""
        branch_id = self._to_int(branch_id)
        warehouse_id = self._to_int(warehouse_id)
        location_id = self._to_int(location_id)

        if date_from and date_to and fields.Date.to_date(date_from) > fields.Date.to_date(date_to):
            raise UserError(_("'From Date' cannot be later than 'To Date'."))

        allowed_branches = self._get_allowed_branch_ids()
        if branch_id and allowed_branches is not None and branch_id not in allowed_branches:
            raise UserError(_("You are not allowed to view stock of this branch."))

        dt_from = self._to_utc_bound(date_from) if date_from else None
        dt_to = self._to_utc_bound(date_to, end_of_day=True) if date_to else None

        cr = self.env.cr
        uid = self.env.uid
        cr.execute("DELETE FROM stock_movement_report WHERE create_uid = %s", [uid])

        # -------- Scope locations (internal locations included in the report)
        scope_where = ["sl.usage = 'internal'", "sl.warehouse_id IS NOT NULL", "sw.company_id IN %(company_ids)s"]
        params = {
            'company_ids': tuple(self.env.companies.ids),
            'uid': uid,
            'dt_from': dt_from,
            'dt_to': dt_to,
        }
        if location_id:
            loc = self.env['stock.location'].browse(location_id)
            scope_where.append("sl.parent_path LIKE %(loc_path)s")
            params['loc_path'] = f"{loc.parent_path}%"
        if warehouse_id:
            scope_where.append("sl.warehouse_id = %(warehouse_id)s")
            params['warehouse_id'] = warehouse_id
        if branch_id:
            scope_where.append("sw.branch_id = %(branch_id)s")
            params['branch_id'] = branch_id
        elif allowed_branches is not None:
            scope_where.append("sw.branch_id IN %(allowed_branches)s")
            params['allowed_branches'] = tuple(allowed_branches or [-1])

        date_to_clause = "AND sml.date < %(dt_to)s" if dt_to else ""
        # Moves before dt_from feed the Opening balance; others are period In/Out.
        is_opening = "sm.date < %(dt_from)s" if dt_from else "FALSE"

        insert_sql = f"""
            INSERT INTO stock_movement_report (
                branch_id, warehouse_id, product_tmpl_id, product_id, categ_id, uom_id,
                opening_qty, opening_weight, qty_in, weight_in, qty_out, weight_out,
                closing_qty, closing_weight,
                create_uid, write_uid, create_date, write_date
            )
            WITH scope AS (
                SELECT sl.id, sl.warehouse_id, sw.branch_id
                FROM stock_location sl
                JOIN stock_warehouse sw ON sw.id = sl.warehouse_id
                WHERE {' AND '.join(scope_where)}
            ),
            ml AS (
                -- Done move lines carry the real done quantity (product UoM) and exact
                -- sub-locations. Weight: label gross weight (pro-rata for split lines),
                -- else the quantity itself for gram UoM products, else qty * product weight.
                SELECT sml.date, sml.location_id, sml.location_dest_id, sml.product_id,
                       sml.quantity_product_uom AS qty,
                       CASE
                           WHEN sm.label_id IS NOT NULL AND COALESCE(sm.quantity, 0) <> 0
                               THEN COALESCE(sm.label_weight, 0.0) * sml.quantity / sm.quantity
                           WHEN COALESCE(uom.name->>'en_US', uom.name::text) ILIKE '%%gm%%'
                             OR COALESCE(uom.name->>'en_US', uom.name::text) ILIKE '%%gram%%'
                             OR COALESCE(uom.name->>'en_US', uom.name::text) = 'g'
                               THEN sml.quantity_product_uom
                           ELSE sml.quantity_product_uom * COALESCE(pt.weight, 0.0)
                       END AS wt
                FROM stock_move_line sml
                JOIN stock_move sm ON sm.id = sml.move_id
                JOIN product_product pp ON pp.id = sml.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                JOIN uom_uom uom ON uom.id = pt.uom_id
                WHERE sml.state = 'done' {date_to_clause}
            ),
            mv AS (
                -- Incoming: destination inside scope, source outside the same warehouse scope
                SELECT dst.warehouse_id, dst.branch_id, sm.product_id,
                       ({is_opening}) AS is_opening, 1 AS dir, sm.qty, sm.wt
                FROM ml sm
                JOIN scope dst ON dst.id = sm.location_dest_id
                LEFT JOIN scope src ON src.id = sm.location_id AND src.warehouse_id = dst.warehouse_id
                WHERE src.id IS NULL
                UNION ALL
                -- Outgoing: source inside scope, destination outside the same warehouse scope
                SELECT src.warehouse_id, src.branch_id, sm.product_id,
                       ({is_opening}) AS is_opening, -1 AS dir, sm.qty, sm.wt
                FROM ml sm
                JOIN scope src ON src.id = sm.location_id
                LEFT JOIN scope dst ON dst.id = sm.location_dest_id AND dst.warehouse_id = src.warehouse_id
                WHERE dst.id IS NULL
            ),
            agg AS (
                SELECT warehouse_id, branch_id, product_id,
                    SUM(CASE WHEN is_opening THEN dir * qty ELSE 0 END) AS opening_qty,
                    SUM(CASE WHEN is_opening THEN dir * wt  ELSE 0 END) AS opening_weight,
                    SUM(CASE WHEN NOT is_opening AND dir = 1  THEN qty ELSE 0 END) AS qty_in,
                    SUM(CASE WHEN NOT is_opening AND dir = 1  THEN wt  ELSE 0 END) AS weight_in,
                    SUM(CASE WHEN NOT is_opening AND dir = -1 THEN qty ELSE 0 END) AS qty_out,
                    SUM(CASE WHEN NOT is_opening AND dir = -1 THEN wt  ELSE 0 END) AS weight_out
                FROM mv
                GROUP BY warehouse_id, branch_id, product_id
            )
            SELECT a.branch_id, a.warehouse_id, pp.product_tmpl_id, a.product_id, pt.categ_id, pt.uom_id,
                   ROUND(a.opening_qty::numeric, 3), ROUND(a.opening_weight::numeric, 3),
                   ROUND(a.qty_in::numeric, 3), ROUND(a.weight_in::numeric, 3),
                   ROUND(a.qty_out::numeric, 3), ROUND(a.weight_out::numeric, 3),
                   ROUND((a.opening_qty + a.qty_in - a.qty_out)::numeric, 3),
                   ROUND((a.opening_weight + a.weight_in - a.weight_out)::numeric, 3),
                   %(uid)s, %(uid)s, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'
            FROM agg a
            JOIN product_product pp ON pp.id = a.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE ROUND(a.opening_qty::numeric, 3) <> 0
               OR ROUND(a.opening_weight::numeric, 3) <> 0
               OR a.qty_in <> 0 OR a.qty_out <> 0
               OR a.weight_in <> 0 OR a.weight_out <> 0
        """
        cr.execute(insert_sql, params)
        self.invalidate_model()

        cr.execute("""
            SELECT COUNT(DISTINCT product_tmpl_id), COUNT(DISTINCT product_id),
                   COALESCE(SUM(opening_qty), 0), COALESCE(SUM(opening_weight), 0),
                   COALESCE(SUM(qty_in), 0), COALESCE(SUM(weight_in), 0),
                   COALESCE(SUM(qty_out), 0), COALESCE(SUM(weight_out), 0),
                   COALESCE(SUM(closing_qty), 0), COALESCE(SUM(closing_weight), 0)
            FROM stock_movement_report WHERE create_uid = %s
        """, [uid])
        r = cr.fetchone()
        keys = ['total_products', 'total_variants', 'opening_qty', 'opening_weight',
                'qty_in', 'weight_in', 'qty_out', 'weight_out', 'closing_qty', 'closing_weight']
        return {k: (round(float(v), 3) if i > 1 else v) for i, (k, v) in enumerate(zip(keys, r))}
