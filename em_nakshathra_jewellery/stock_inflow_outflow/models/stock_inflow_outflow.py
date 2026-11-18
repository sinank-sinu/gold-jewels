# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError


FLOW_CATEGORIES = {
    'purchase_in': {'label': 'Purchase Receipts', 'dir': 'in', 'icon': 'fa-shopping-bag'},
    'transfer_in': {'label': 'Transfer In (Branch)', 'dir': 'in', 'icon': 'fa-sign-in'},
    'sales_return': {'label': 'Sales Returns', 'dir': 'in', 'icon': 'fa-reply'},
    'other_in': {'label': 'Mfg / Adjustment In', 'dir': 'in', 'icon': 'fa-plus-circle'},
    'sales_out': {'label': 'Sales Delivery', 'dir': 'out', 'icon': 'fa-shopping-cart'},
    'transfer_out': {'label': 'Transfer Out (Branch)', 'dir': 'out', 'icon': 'fa-sign-out'},
    'purchase_return': {'label': 'Purchase Returns', 'dir': 'out', 'icon': 'fa-undo'},
    'other_out': {'label': 'Mfg / Adjustment Out', 'dir': 'out', 'icon': 'fa-minus-circle'},
}


class StockInflowOutflowReport(models.TransientModel):
    _name = 'stock.inflow.outflow.report'
    _description = 'Stock Inflow Outflow & Vendor-Wise Label Analytics'

    # ------------------------------------------------------------------
    # Access & Filter Helpers
    # ------------------------------------------------------------------
    def _is_admin_or_manager(self):
        """Return True if current user can access all allowed-company branches."""
        user = self.env.user
        return (
            user._is_admin()
            or user.has_group('base.group_system')
            or user.has_group('base.group_erp_manager')
            or user.has_group('em_jewellery_management.group_jewellery_manager')
        )

    def _get_allowed_branch_ids(self):
        """Return None for admins/managers, or list of allowed branch IDs."""
        if self._is_admin_or_manager():
            return None
        user = self.env.user
        if hasattr(user, 'branch_ids') and user.branch_ids:
            return user.branch_ids.ids
        if hasattr(user, 'branch_id') and user.branch_id:
            return [user.branch_id.id]
        if hasattr(user, 'allowed_branch_ids') and user.allowed_branch_ids:
            return user.allowed_branch_ids.ids
        return [-1]

    def _get_allowed_company_ids(self):
        """Return company IDs the current user is permitted to query."""
        cids = self.env.user.company_ids.ids or [self.env.company.id]
        return tuple(cids)

    def _resolve_branch_filter(self, branch_id):
        """Validate requested branch against user permissions and return filter tuple."""
        allowed_branches = self._get_allowed_branch_ids()
        allowed_cids = self._get_allowed_company_ids()

        branch_ids_filter = None
        selected_branch_name = _('All Branches')

        is_all = branch_id in (False, None, '', 'all')
        if allowed_branches is not None:
            if is_all:
                branch_ids_filter = allowed_branches
                if len(allowed_branches) == 1 and allowed_branches[0] != -1:
                    b_rec = self.env['res.branch'].sudo().browse(allowed_branches[0])
                    if b_rec.exists():
                        selected_branch_name = b_rec.name
                elif len(allowed_branches) > 1:
                    selected_branch_name = _('All Allowed Branches')
            else:
                try:
                    bid = int(branch_id)
                except (ValueError, TypeError):
                    raise UserError(_("Invalid branch selection."))
                if bid not in allowed_branches:
                    raise UserError(_("You are not authorized to view data for this branch."))
                branch_ids_filter = [bid]
                b_rec = self.env['res.branch'].sudo().browse(bid)
                if b_rec.exists():
                    selected_branch_name = b_rec.name
        else:
            if not is_all:
                try:
                    bid = int(branch_id)
                except (ValueError, TypeError):
                    raise UserError(_("Invalid branch selection."))
                b_rec = self.env['res.branch'].sudo().browse(bid)
                if not b_rec.exists() or (b_rec.company_id and b_rec.company_id.id not in allowed_cids):
                    raise UserError(_("Branch not found or not accessible in your companies."))
                branch_ids_filter = [bid]
                selected_branch_name = b_rec.name

        return branch_ids_filter, selected_branch_name, allowed_cids

    def _get_user_tz(self):
        return pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'Asia/Kolkata')

    def _parse_date_bounds(self, date_from, date_to):
        """Parse YYYY-MM-DD bounds into local dates and naive UTC datetime bounds."""
        today = fields.Date.context_today(self)
        d_from = fields.Date.to_date(date_from) if date_from else today.replace(day=1)
        d_to = fields.Date.to_date(date_to) if date_to else today
        if d_from > d_to:
            raise UserError(_("'From Date' cannot be later than 'To Date'."))

        tz = self._get_user_tz()
        dt_from_local = tz.localize(datetime.combine(d_from, time.min))
        dt_to_local_excl = tz.localize(datetime.combine(d_to + timedelta(days=1), time.min))

        dt_from_utc = dt_from_local.astimezone(pytz.utc).replace(tzinfo=None)
        dt_to_utc = dt_to_local_excl.astimezone(pytz.utc).replace(tzinfo=None)
        return d_from, d_to, dt_from_utc, dt_to_utc

    def _format_utc_to_local(self, dt_val):
        if not dt_val:
            return ''
        if isinstance(dt_val, str):
            dt_val = fields.Datetime.from_string(dt_val)
        tz = self._get_user_tz()
        utc_dt = pytz.utc.localize(dt_val)
        return utc_dt.astimezone(tz).strftime('%d-%m-%Y %I:%M %p')

    def _lang(self):
        return self.env.lang or 'en_US'

    def _extract_json_name(self, val):
        if isinstance(val, dict):
            return val.get(self._lang()) or val.get('en_US') or next(iter(val.values()), '')
        return val or ''

    # ------------------------------------------------------------------
    # Shared SQL Building Blocks
    # ------------------------------------------------------------------
    @staticmethod
    def _branch_loc_cte():
        """Map every internal location to its effective branch_id."""
        return """
            branch_loc AS (
                SELECT sl.id,
                       sl.usage,
                       sl.complete_name,
                       sl.warehouse_id,
                       COALESCE(sw.branch_id, lot.branch_id, sl.branch_id) AS branch_id
                FROM stock_location sl
                LEFT JOIN stock_warehouse sw ON sw.id = sl.warehouse_id
                LEFT JOIN stock_location lot ON lot.id = sw.lot_stock_id
                WHERE sl.usage = 'internal'
                  AND (sl.company_id IS NULL OR sl.company_id IN %(company_ids)s)
            )
        """

    @staticmethod
    def _weight_sql_expr():
        """Consistent gram-weight expression matching Odoo stock_quant & label weights."""
        return """
            CASE
                WHEN COALESCE(uom.name->>'en_US', uom.name::text) ILIKE '%%gm%%'
                  OR COALESCE(uom.name->>'en_US', uom.name::text) ILIKE '%%gram%%'
                  OR COALESCE(uom.name->>'en_US', uom.name::text) = 'g'
                    THEN sml.quantity_product_uom
                WHEN sm.label_id IS NOT NULL AND COALESCE(sm.quantity, 0) <> 0 AND COALESCE(sm.label_weight, 0) > 0
                    THEN sm.label_weight * sml.quantity / sm.quantity
                ELSE sml.quantity_product_uom * COALESCE(pt.weight, 0.0)
            END
        """

    def _scoped_moves_cte(self, branch_ids_filter):
        """Return SQL CTEs (branch_loc, scoped_mv) for branch inflow & outflow move lines."""
        branch_in_clause = ""
        branch_out_clause = ""
        if branch_ids_filter is not None:
            branch_in_clause = "AND b_scope.branch_id IN %(branch_ids)s"
            branch_out_clause = "AND b_scope.branch_id IN %(branch_ids)s"

        wt_expr = self._weight_sql_expr()
        return f"""
            {self._branch_loc_cte()},
            scoped_mv AS (
                SELECT
                    sml.id AS sml_id,
                    sm.id AS move_id,
                    sml.date AS move_date,
                    sm.picking_id,
                    sm.reference,
                    sm.origin,
                    sm.label_id,
                    sml.product_id,
                    pp.product_tmpl_id,
                    pt.categ_id,
                    pt.uom_id,
                    b_scope.branch_id,
                    sml.location_id,
                    sml.location_dest_id,
                    (sml.date < %(dt_from)s) AS is_opening,
                    1 AS dir,
                    CASE
                        WHEN src_loc.usage = 'supplier' THEN 'purchase_in'
                        WHEN src_bl.branch_id IS NOT NULL THEN 'transfer_in'
                        WHEN src_loc.usage = 'customer' THEN 'sales_return'
                        ELSE 'other_in'
                    END AS category,
                    sml.quantity_product_uom AS qty,
                    {wt_expr} AS wt
                FROM stock_move_line sml
                JOIN stock_move sm ON sm.id = sml.move_id
                JOIN product_product pp ON pp.id = sml.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                JOIN uom_uom uom ON uom.id = pt.uom_id
                JOIN branch_loc b_scope ON b_scope.id = sml.location_dest_id
                JOIN stock_location src_loc ON src_loc.id = sml.location_id
                LEFT JOIN branch_loc src_bl ON src_bl.id = sml.location_id
                WHERE sml.state = 'done'
                  AND sml.date < %(dt_to)s
                  AND sml.quantity_product_uom <> 0
                  AND b_scope.branch_id IS NOT NULL
                  AND (src_bl.branch_id IS DISTINCT FROM b_scope.branch_id)
                  {branch_in_clause}

                UNION ALL

                SELECT
                    sml.id AS sml_id,
                    sm.id AS move_id,
                    sml.date AS move_date,
                    sm.picking_id,
                    sm.reference,
                    sm.origin,
                    sm.label_id,
                    sml.product_id,
                    pp.product_tmpl_id,
                    pt.categ_id,
                    pt.uom_id,
                    b_scope.branch_id,
                    sml.location_id,
                    sml.location_dest_id,
                    (sml.date < %(dt_from)s) AS is_opening,
                    -1 AS dir,
                    CASE
                        WHEN dst_loc.usage = 'customer' THEN 'sales_out'
                        WHEN dst_bl.branch_id IS NOT NULL THEN 'transfer_out'
                        WHEN dst_loc.usage = 'supplier' THEN 'purchase_return'
                        ELSE 'other_out'
                    END AS category,
                    sml.quantity_product_uom AS qty,
                    {wt_expr} AS wt
                FROM stock_move_line sml
                JOIN stock_move sm ON sm.id = sml.move_id
                JOIN product_product pp ON pp.id = sml.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                JOIN uom_uom uom ON uom.id = pt.uom_id
                JOIN branch_loc b_scope ON b_scope.id = sml.location_id
                JOIN stock_location dst_loc ON dst_loc.id = sml.location_dest_id
                LEFT JOIN branch_loc dst_bl ON dst_bl.id = sml.location_dest_id
                WHERE sml.state = 'done'
                  AND sml.date < %(dt_to)s
                  AND sml.quantity_product_uom <> 0
                  AND b_scope.branch_id IS NOT NULL
                  AND (dst_bl.branch_id IS DISTINCT FROM b_scope.branch_id)
                  {branch_out_clause}
            )
        """

    def _resolve_product_names(self, product_ids):
        if not product_ids:
            return {}
        products = self.env['product.product'].sudo().browse(list(set(product_ids)))
        return {
            p.id: {
                'display_name': p.display_name,
                'default_code': p.default_code or '',
                'barcode': p.barcode or '',
            }
            for p in products
        }

    @staticmethod
    def _effective_vendor_sql():
        return "COALESCE(pl.partner_id, po.partner_id, jw.job_worker_id, 0)"

    # ------------------------------------------------------------------
    # Initial Metadata RPC
    # ------------------------------------------------------------------
    @api.model
    def get_initial_metadata(self):
        """Return accessible branches, editability, default branch, and default period."""
        is_admin = self._is_admin_or_manager()
        allowed_branches = self._get_allowed_branch_ids()
        allowed_cids = self._get_allowed_company_ids()

        branch_domain = [('company_id', 'in', list(allowed_cids))]
        if allowed_branches is not None:
            branch_domain.append(('id', 'in', allowed_branches))

        branches = self.env['res.branch'].sudo().search_read(
            branch_domain, ['id', 'name', 'branch_code', 'company_id'], order='name asc'
        )
        branch_ids_set = {b['id'] for b in branches}

        user_branch = self.env.user.branch_id.id if getattr(self.env.user, 'branch_id', False) else False
        if not is_admin:
            if user_branch and user_branch in branch_ids_set:
                default_branch_id = user_branch
            elif len(branches) == 1:
                default_branch_id = branches[0]['id']
            elif len(branches) > 1:
                default_branch_id = 'all'
            else:
                default_branch_id = user_branch or 'all'
        else:
            default_branch_id = user_branch if (user_branch and user_branch in branch_ids_set) else 'all'

        today = fields.Date.context_today(self)
        first_of_month = today.replace(day=1)

        is_branch_editable = is_admin or len(branches) > 1
        return {
            'branches': [
                {
                    'id': b['id'],
                    'name': b['name'],
                    'branch_code': b.get('branch_code') or '',
                    'company_name': b['company_id'][1] if b.get('company_id') else '',
                }
                for b in branches
            ],
            'default_branch_id': default_branch_id,
            'is_branch_editable': is_branch_editable,
            'date_from': first_of_month.strftime('%Y-%m-%d'),
            'date_to': today.strftime('%Y-%m-%d'),
            'company_name': self.env.company.name,
            'currency_symbol': self.env.company.currency_id.symbol or '₹',
        }

    # ------------------------------------------------------------------
    # Tab 1: Stock Inflow & Outflow RPCs
    # ------------------------------------------------------------------
    @api.model
    def get_inflow_outflow_summary(
        self,
        branch_id='all',
        date_from=None,
        date_to=None,
        only_with_movement=False,
        search_query=None,
        product_limit=100,
        product_offset=0,
    ):
        """Return KPI equation, category breakdown, branch breakdown, and product-wise rows."""
        branch_ids_filter, selected_branch_name, allowed_cids = self._resolve_branch_filter(branch_id)
        d_from, d_to, dt_from, dt_to = self._parse_date_bounds(date_from, date_to)

        params = {
            'company_ids': allowed_cids,
            'dt_from': dt_from,
            'dt_to': dt_to,
            'lang': self._lang(),
            'limit': int(product_limit or 100),
            'offset': int(product_offset or 0),
        }
        if branch_ids_filter is not None:
            params['branch_ids'] = tuple(branch_ids_filter or [-1])

        ctes = self._scoped_moves_cte(branch_ids_filter)
        cr = self.env.cr

        # 1. KPI Summary + Category Breakdown
        cr.execute(f"""
            WITH {ctes}
            SELECT
                is_opening,
                dir,
                category,
                COUNT(*) AS move_count,
                COALESCE(SUM(qty), 0.0) AS sum_qty,
                COALESCE(SUM(wt), 0.0) AS sum_wt
            FROM scoped_mv
            GROUP BY is_opening, dir, category
        """, params)

        opening_qty = opening_wt = 0.0
        inflow_qty = inflow_wt = 0.0
        outflow_qty = outflow_wt = 0.0
        inflow_count = outflow_count = 0

        categories = {
            key: {
                'key': key,
                'label': meta['label'],
                'dir': meta['dir'],
                'icon': meta['icon'],
                'wt': 0.0,
                'qty': 0.0,
                'count': 0,
                'share_pct': 0.0,
            }
            for key, meta in FLOW_CATEGORIES.items()
        }

        for is_open, direction, cat, cnt, sqty, swt in cr.fetchall():
            sqty = float(sqty or 0.0)
            swt = float(swt or 0.0)
            cnt = int(cnt or 0)
            if is_open:
                opening_qty += direction * sqty
                opening_wt += direction * swt
            else:
                if direction == 1:
                    inflow_qty += sqty
                    inflow_wt += swt
                    inflow_count += cnt
                else:
                    outflow_qty += sqty
                    outflow_wt += swt
                    outflow_count += cnt
                if cat in categories:
                    categories[cat]['wt'] = round(categories[cat]['wt'] + swt, 3)
                    categories[cat]['qty'] = round(categories[cat]['qty'] + sqty, 3)
                    categories[cat]['count'] += cnt

        for key, cdata in categories.items():
            denom = inflow_wt if cdata['dir'] == 'in' else outflow_wt
            cdata['share_pct'] = round((cdata['wt'] / denom) * 100.0, 1) if denom > 0 else 0.0

        closing_qty = opening_qty + inflow_qty - outflow_qty
        closing_wt = opening_wt + inflow_wt - outflow_wt
        net_qty = inflow_qty - outflow_qty
        net_wt = inflow_wt - outflow_wt

        # 2. Intra-branch counter moves count (informational)
        intra_branch_clause = ""
        if branch_ids_filter is not None:
            intra_branch_clause = "AND src_bl.branch_id IN %(branch_ids)s"
        cr.execute(f"""
            WITH {self._branch_loc_cte()}
            SELECT COUNT(*),
                   COALESCE(SUM({self._weight_sql_expr()}), 0.0)
            FROM stock_move_line sml
            JOIN stock_move sm ON sm.id = sml.move_id
            JOIN product_product pp ON pp.id = sml.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN uom_uom uom ON uom.id = pt.uom_id
            JOIN branch_loc src_bl ON src_bl.id = sml.location_id
            JOIN branch_loc dst_bl ON dst_bl.id = sml.location_dest_id
            WHERE sml.state = 'done'
              AND sml.date >= %(dt_from)s
              AND sml.date < %(dt_to)s
              AND sml.quantity_product_uom <> 0
              AND src_bl.branch_id IS NOT NULL
              AND src_bl.branch_id = dst_bl.branch_id
              {intra_branch_clause}
        """, params)
        intra_row = cr.fetchone()
        intra_count = int(intra_row[0] or 0)
        intra_wt = round(float(intra_row[1] or 0.0), 3)

        # 3. Branch-wise Summary
        cr.execute(f"""
            WITH {ctes}
            SELECT
                rb.id AS branch_id,
                rb.name AS branch_name,
                rb.branch_code,
                ROUND(COALESCE(SUM(CASE WHEN smv.is_opening THEN smv.dir * smv.wt ELSE 0 END), 0)::numeric, 3) AS opening_wt,
                ROUND(COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.category = 'purchase_in' THEN smv.wt ELSE 0 END), 0)::numeric, 3) AS purchase_in_wt,
                ROUND(COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.category = 'transfer_in' THEN smv.wt ELSE 0 END), 0)::numeric, 3) AS transfer_in_wt,
                ROUND(COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.category IN ('sales_return', 'other_in') THEN smv.wt ELSE 0 END), 0)::numeric, 3) AS other_in_wt,
                ROUND(COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.dir = 1 THEN smv.wt ELSE 0 END), 0)::numeric, 3) AS inflow_wt,
                COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.dir = 1 THEN 1 ELSE 0 END), 0) AS inflow_count,
                ROUND(COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.category = 'sales_out' THEN smv.wt ELSE 0 END), 0)::numeric, 3) AS sales_out_wt,
                ROUND(COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.category = 'transfer_out' THEN smv.wt ELSE 0 END), 0)::numeric, 3) AS transfer_out_wt,
                ROUND(COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.category IN ('purchase_return', 'other_out') THEN smv.wt ELSE 0 END), 0)::numeric, 3) AS other_out_wt,
                ROUND(COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.dir = -1 THEN smv.wt ELSE 0 END), 0)::numeric, 3) AS outflow_wt,
                COALESCE(SUM(CASE WHEN NOT smv.is_opening AND smv.dir = -1 THEN 1 ELSE 0 END), 0) AS outflow_count
            FROM scoped_mv smv
            JOIN res_branch rb ON rb.id = smv.branch_id
            GROUP BY rb.id, rb.name, rb.branch_code
            ORDER BY inflow_wt DESC, outflow_wt DESC, rb.name ASC
        """, params)

        branch_summary = []
        for r in cr.fetchall():
            op = float(r[3] or 0.0)
            in_tot = float(r[7] or 0.0)
            out_tot = float(r[12] or 0.0)
            branch_summary.append({
                'branch_id': r[0],
                'branch_name': r[1],
                'branch_code': r[2] or '',
                'opening_wt': round(op, 3),
                'purchase_in_wt': float(r[4] or 0.0),
                'transfer_in_wt': float(r[5] or 0.0),
                'other_in_wt': float(r[6] or 0.0),
                'inflow_wt': round(in_tot, 3),
                'inflow_count': int(r[8] or 0),
                'sales_out_wt': float(r[9] or 0.0),
                'transfer_out_wt': float(r[10] or 0.0),
                'other_out_wt': float(r[11] or 0.0),
                'outflow_wt': round(out_tot, 3),
                'outflow_count': int(r[13] or 0),
                'net_wt': round(in_tot - out_tot, 3),
                'closing_wt': round(op + in_tot - out_tot, 3),
            })

        # 4. Product-wise Flow (paginated + searchable)
        having_clauses = [
            "(ROUND(agg.opening_wt::numeric, 3) <> 0 OR ROUND(agg.inflow_wt::numeric, 3) <> 0 OR ROUND(agg.outflow_wt::numeric, 3) <> 0)"
        ]
        if only_with_movement:
            having_clauses.append("(ROUND(agg.inflow_wt::numeric, 3) <> 0 OR ROUND(agg.outflow_wt::numeric, 3) <> 0)")

        prod_search_clause = ""
        if search_query and search_query.strip():
            params['psearch'] = f"%{search_query.strip()}%"
            prod_search_clause = """
                AND (
                    COALESCE(pt.name->>%(lang)s, pt.name->>'en_US', pt.name::text) ILIKE %(psearch)s
                    OR COALESCE(pp.default_code, '') ILIKE %(psearch)s
                    OR COALESCE(pp.barcode, '') ILIKE %(psearch)s
                    OR COALESCE(pc.complete_name, '') ILIKE %(psearch)s
                )
            """

        prod_base_sql = f"""
            WITH {ctes},
            agg AS (
                SELECT
                    smv.product_id,
                    SUM(CASE WHEN smv.is_opening THEN smv.dir * smv.qty ELSE 0 END) AS opening_qty,
                    SUM(CASE WHEN smv.is_opening THEN smv.dir * smv.wt ELSE 0 END) AS opening_wt,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.category = 'purchase_in' THEN smv.wt ELSE 0 END) AS purchase_in_wt,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.category = 'transfer_in' THEN smv.wt ELSE 0 END) AS transfer_in_wt,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.category IN ('sales_return', 'other_in') THEN smv.wt ELSE 0 END) AS other_in_wt,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.dir = 1 THEN smv.qty ELSE 0 END) AS inflow_qty,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.dir = 1 THEN smv.wt ELSE 0 END) AS inflow_wt,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.category = 'sales_out' THEN smv.wt ELSE 0 END) AS sales_out_wt,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.category = 'transfer_out' THEN smv.wt ELSE 0 END) AS transfer_out_wt,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.category IN ('purchase_return', 'other_out') THEN smv.wt ELSE 0 END) AS other_out_wt,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.dir = -1 THEN smv.qty ELSE 0 END) AS outflow_qty,
                    SUM(CASE WHEN NOT smv.is_opening AND smv.dir = -1 THEN smv.wt ELSE 0 END) AS outflow_wt
                FROM scoped_mv smv
                GROUP BY smv.product_id
            )
            SELECT
                agg.product_id,
                pc.complete_name AS category_name,
                COALESCE(uom.name->>%(lang)s, uom.name->>'en_US', uom.name::text) AS uom_name,
                ROUND(agg.opening_qty::numeric, 3),
                ROUND(agg.opening_wt::numeric, 3),
                ROUND(agg.purchase_in_wt::numeric, 3),
                ROUND(agg.transfer_in_wt::numeric, 3),
                ROUND(agg.other_in_wt::numeric, 3),
                ROUND(agg.inflow_qty::numeric, 3),
                ROUND(agg.inflow_wt::numeric, 3),
                ROUND(agg.sales_out_wt::numeric, 3),
                ROUND(agg.transfer_out_wt::numeric, 3),
                ROUND(agg.other_out_wt::numeric, 3),
                ROUND(agg.outflow_qty::numeric, 3),
                ROUND(agg.outflow_wt::numeric, 3),
                COUNT(*) OVER() AS full_count
            FROM agg
            JOIN product_product pp ON pp.id = agg.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            LEFT JOIN uom_uom uom ON uom.id = pt.uom_id
            WHERE {' AND '.join(having_clauses)}
              {prod_search_clause}
            ORDER BY (agg.inflow_wt + agg.outflow_wt) DESC, agg.opening_wt DESC, agg.product_id ASC
            LIMIT %(limit)s OFFSET %(offset)s
        """
        cr.execute(prod_base_sql, params)
        prod_raw = cr.fetchall()
        product_total_count = int(prod_raw[0][15]) if prod_raw else 0
        prod_info = self._resolve_product_names([r[0] for r in prod_raw])

        product_rows = []
        for r in prod_raw:
            pid = r[0]
            info = prod_info.get(pid, {})
            op_q, op_w = float(r[3] or 0.0), float(r[4] or 0.0)
            in_q, in_w = float(r[8] or 0.0), float(r[9] or 0.0)
            out_q, out_w = float(r[13] or 0.0), float(r[14] or 0.0)
            product_rows.append({
                'product_id': pid,
                'product_name': info.get('display_name') or f'Product #{pid}',
                'default_code': info.get('default_code') or '',
                'category_name': r[1] or '',
                'uom_name': self._extract_json_name(r[2]),
                'opening_qty': round(op_q, 3),
                'opening_wt': round(op_w, 3),
                'purchase_in_wt': float(r[5] or 0.0),
                'transfer_in_wt': float(r[6] or 0.0),
                'other_in_wt': float(r[7] or 0.0),
                'inflow_qty': round(in_q, 3),
                'inflow_wt': round(in_w, 3),
                'sales_out_wt': float(r[10] or 0.0),
                'transfer_out_wt': float(r[11] or 0.0),
                'other_out_wt': float(r[12] or 0.0),
                'outflow_qty': round(out_q, 3),
                'outflow_wt': round(out_w, 3),
                'net_wt': round(in_w - out_w, 3),
                'closing_qty': round(op_q + in_q - out_q, 3),
                'closing_wt': round(op_w + in_w - out_w, 3),
            })

        return {
            'selected_branch_name': selected_branch_name,
            'date_from': d_from.strftime('%Y-%m-%d'),
            'date_to': d_to.strftime('%Y-%m-%d'),
            'kpis': {
                'opening_qty': round(opening_qty, 3),
                'opening_wt': round(opening_wt, 3),
                'inflow_qty': round(inflow_qty, 3),
                'inflow_wt': round(inflow_wt, 3),
                'inflow_count': inflow_count,
                'outflow_qty': round(outflow_qty, 3),
                'outflow_wt': round(outflow_wt, 3),
                'outflow_count': outflow_count,
                'net_qty': round(net_qty, 3),
                'net_wt': round(net_wt, 3),
                'closing_qty': round(closing_qty, 3),
                'closing_wt': round(closing_wt, 3),
                'intra_count': intra_count,
                'intra_wt': intra_wt,
            },
            'categories': categories,
            'branch_summary': branch_summary,
            'product_rows': product_rows,
            'product_total_count': product_total_count,
        }

    @api.model
    def get_inflow_outflow_ledger(
        self,
        branch_id='all',
        date_from=None,
        date_to=None,
        direction=None,
        category=None,
        product_id=None,
        search_query=None,
        limit=50,
        offset=0,
    ):
        """Return paginated individual inflow/outflow stock move lines."""
        branch_ids_filter, selected_branch_name, allowed_cids = self._resolve_branch_filter(branch_id)
        d_from, d_to, dt_from, dt_to = self._parse_date_bounds(date_from, date_to)

        params = {
            'company_ids': allowed_cids,
            'dt_from': dt_from,
            'dt_to': dt_to,
            'lang': self._lang(),
            'limit': int(limit or 50),
            'offset': int(offset or 0),
        }
        if branch_ids_filter is not None:
            params['branch_ids'] = tuple(branch_ids_filter or [-1])

        ctes = self._scoped_moves_cte(branch_ids_filter)
        where_clauses = ["NOT smv.is_opening"]

        if direction == 'in':
            where_clauses.append("smv.dir = 1")
        elif direction == 'out':
            where_clauses.append("smv.dir = -1")

        if category and category in FLOW_CATEGORIES:
            where_clauses.append("smv.category = %(category)s")
            params['category'] = category

        if product_id:
            where_clauses.append("smv.product_id = %(product_id)s")
            params['product_id'] = int(product_id)

        if search_query and search_query.strip():
            params['lsearch'] = f"%{search_query.strip()}%"
            where_clauses.append("""
                (
                    COALESCE(sp.name, smv.reference, '') ILIKE %(lsearch)s
                    OR COALESCE(smv.origin, '') ILIKE %(lsearch)s
                    OR COALESCE(pt.name->>%(lang)s, pt.name->>'en_US', pt.name::text) ILIKE %(lsearch)s
                    OR COALESCE(pp.default_code, '') ILIKE %(lsearch)s
                    OR COALESCE(pl.name, '') ILIKE %(lsearch)s
                    OR COALESCE(pl.barcode, '') ILIKE %(lsearch)s
                    OR COALESCE(rp.name, '') ILIKE %(lsearch)s
                    OR COALESCE(src_l.complete_name, '') ILIKE %(lsearch)s
                    OR COALESCE(dst_l.complete_name, '') ILIKE %(lsearch)s
                )
            """)

        vendor_expr = self._effective_vendor_sql()
        where_sql = " AND ".join(where_clauses)

        cr = self.env.cr
        cr.execute(f"""
            WITH {ctes}
            SELECT
                COUNT(*),
                COALESCE(SUM(smv.wt), 0.0),
                COALESCE(SUM(smv.qty), 0.0)
            FROM scoped_mv smv
            LEFT JOIN stock_picking sp ON sp.id = smv.picking_id
            JOIN product_product pp ON pp.id = smv.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_label pl ON pl.id = smv.label_id
            LEFT JOIN purchase_order po ON po.id = pl.purchase_id
            LEFT JOIN jewellery_job_work jw ON jw.id = pl.job_work_id
            LEFT JOIN res_partner rp ON rp.id = COALESCE(sp.partner_id, NULLIF({vendor_expr}, 0))
            JOIN stock_location src_l ON src_l.id = smv.location_id
            JOIN stock_location dst_l ON dst_l.id = smv.location_dest_id
            WHERE {where_sql}
        """, params)
        tot_row = cr.fetchone()
        total_count = int(tot_row[0] or 0)
        filtered_wt = round(float(tot_row[1] or 0.0), 3)
        filtered_qty = round(float(tot_row[2] or 0.0), 3)

        cr.execute(f"""
            WITH {ctes}
            SELECT
                smv.sml_id,
                smv.move_id,
                smv.move_date,
                smv.picking_id,
                COALESCE(sp.name, smv.reference, '') AS ref_name,
                COALESCE(smv.origin, sp.origin, '') AS origin,
                smv.dir,
                smv.category,
                smv.branch_id,
                rb.name AS branch_name,
                src_l.complete_name AS src_loc,
                dst_l.complete_name AS dst_loc,
                smv.product_id,
                smv.label_id,
                pl.name AS label_name,
                pl.barcode AS label_barcode,
                rp.id AS partner_id,
                rp.name AS partner_name,
                ROUND(smv.wt::numeric, 3) AS wt,
                ROUND(smv.qty::numeric, 3) AS qty,
                COALESCE(uom.name->>%(lang)s, uom.name->>'en_US', uom.name::text) AS uom_name
            FROM scoped_mv smv
            LEFT JOIN stock_picking sp ON sp.id = smv.picking_id
            JOIN res_branch rb ON rb.id = smv.branch_id
            JOIN stock_location src_l ON src_l.id = smv.location_id
            JOIN stock_location dst_l ON dst_l.id = smv.location_dest_id
            JOIN product_product pp ON pp.id = smv.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN uom_uom uom ON uom.id = pt.uom_id
            LEFT JOIN product_label pl ON pl.id = smv.label_id
            LEFT JOIN purchase_order po ON po.id = pl.purchase_id
            LEFT JOIN jewellery_job_work jw ON jw.id = pl.job_work_id
            LEFT JOIN res_partner rp ON rp.id = COALESCE(sp.partner_id, NULLIF({vendor_expr}, 0))
            WHERE {where_sql}
            ORDER BY smv.move_date DESC, smv.sml_id DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """, params)

        rows = cr.fetchall()
        prod_info = self._resolve_product_names([r[12] for r in rows])

        lines = []
        for r in rows:
            cat_key = r[7]
            cat_meta = FLOW_CATEGORIES.get(cat_key, {'label': cat_key})
            pid = r[12]
            lines.append({
                'id': r[0],
                'move_id': r[1],
                'date_str': self._format_utc_to_local(r[2]),
                'picking_id': r[3] or False,
                'ref_name': r[4] or '-',
                'origin': r[5] or '',
                'direction': 'in' if r[6] == 1 else 'out',
                'category': cat_key,
                'category_label': cat_meta['label'],
                'branch_id': r[8],
                'branch_name': r[9] or '',
                'src_location': r[10] or '',
                'dst_location': r[11] or '',
                'product_id': pid,
                'product_name': prod_info.get(pid, {}).get('display_name') or f'Product #{pid}',
                'label_id': r[13] or False,
                'label_name': r[14] or '',
                'label_barcode': r[15] or '',
                'partner_id': r[16] or False,
                'partner_name': r[17] or '',
                'wt': float(r[18] or 0.0),
                'qty': float(r[19] or 0.0),
                'uom_name': self._extract_json_name(r[20]),
            })

        return {
            'lines': lines,
            'total_count': total_count,
            'filtered_wt': filtered_wt,
            'filtered_qty': filtered_qty,
        }

    # ------------------------------------------------------------------
    # Tab 2: Vendor-Wise Labels RPCs (Same Branch & Date Setup)
    # ------------------------------------------------------------------
    def _label_movement_ctes(self, branch_ids_filter):
        """Return CTEs tracking label inflows, outflows, opening, and closing per (branch_id, label_id)."""
        branch_in_clause = ""
        branch_out_clause = ""
        if branch_ids_filter is not None:
            branch_in_clause = "AND om.dst_branch IN %(branch_ids)s"
            branch_out_clause = "AND om.src_branch IN %(branch_ids)s"

        wt_expr = self._weight_sql_expr()
        return f"""
            {self._branch_loc_cte()},
            ordered_label_mv AS (
                SELECT
                    sm.label_id,
                    sml.date AS move_date,
                    src_loc.usage AS src_usage,
                    dst_loc.usage AS dst_usage,
                    src_bl.branch_id AS src_branch,
                    dst_bl.branch_id AS dst_branch,
                    {wt_expr} AS wt,
                    ROW_NUMBER() OVER (PARTITION BY sm.label_id ORDER BY sml.date ASC, sml.id ASC) AS rn
                FROM stock_move_line sml
                JOIN stock_move sm ON sm.id = sml.move_id
                JOIN product_product pp ON pp.id = sml.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                JOIN uom_uom uom ON uom.id = pt.uom_id
                JOIN stock_location src_loc ON src_loc.id = sml.location_id
                JOIN stock_location dst_loc ON dst_loc.id = sml.location_dest_id
                LEFT JOIN branch_loc src_bl ON src_bl.id = sml.location_id
                LEFT JOIN branch_loc dst_bl ON dst_bl.id = sml.location_dest_id
                WHERE sml.state = 'done'
                  AND sm.label_id IS NOT NULL
                  AND sml.quantity_product_uom <> 0
            ),
            label_mv AS (
                SELECT
                    om.dst_branch AS branch_id,
                    om.label_id,
                    om.move_date,
                    (om.move_date < %(dt_from)s) AS is_opening,
                    1 AS dir,
                    CASE
                        WHEN om.src_usage = 'supplier' THEN 'purchase_in'
                        WHEN om.src_branch IS NOT NULL AND om.src_branch IS DISTINCT FROM om.dst_branch THEN 'transfer_in'
                        WHEN om.src_usage = 'customer' THEN 'sales_return'
                        WHEN om.rn = 1 THEN 'purchase_in'
                        ELSE 'other_in'
                    END AS category,
                    om.wt
                FROM ordered_label_mv om
                WHERE om.move_date < %(dt_to)s
                  AND om.dst_branch IS NOT NULL
                  AND (om.rn = 1 OR om.src_branch IS DISTINCT FROM om.dst_branch)
                  {branch_in_clause}

                UNION ALL

                SELECT
                    om.src_branch AS branch_id,
                    om.label_id,
                    om.move_date,
                    (om.move_date < %(dt_from)s) AS is_opening,
                    -1 AS dir,
                    CASE
                        WHEN om.dst_usage = 'customer' THEN 'sales_out'
                        WHEN om.dst_branch IS NOT NULL THEN 'transfer_out'
                        WHEN om.dst_usage = 'supplier' THEN 'purchase_return'
                        ELSE 'other_out'
                    END AS category,
                    om.wt
                FROM ordered_label_mv om
                WHERE om.move_date < %(dt_to)s
                  AND om.rn > 1
                  AND om.src_branch IS NOT NULL
                  AND (om.dst_branch IS DISTINCT FROM om.src_branch)
                  {branch_out_clause}
            ),
            per_branch_label AS (
                SELECT
                    lm.branch_id,
                    lm.label_id,
                    SUM(CASE WHEN lm.is_opening THEN lm.dir ELSE 0 END) AS open_dir,
                    SUM(CASE WHEN lm.is_opening THEN lm.dir * lm.wt ELSE 0 END) AS open_wt,
                    MAX(CASE WHEN NOT lm.is_opening AND lm.dir = 1 THEN 1 ELSE 0 END) AS has_in,
                    SUM(CASE WHEN NOT lm.is_opening AND lm.dir = 1 THEN 1 ELSE 0 END) AS in_moves,
                    SUM(CASE WHEN NOT lm.is_opening AND lm.dir = 1 THEN lm.wt ELSE 0 END) AS in_wt,
                    MAX(CASE WHEN NOT lm.is_opening AND lm.category = 'purchase_in' THEN 1 ELSE 0 END) AS has_purchase_in,
                    MAX(CASE WHEN NOT lm.is_opening AND lm.category = 'transfer_in' THEN 1 ELSE 0 END) AS has_transfer_in,
                    MAX(CASE WHEN NOT lm.is_opening AND lm.dir = -1 THEN 1 ELSE 0 END) AS has_out,
                    SUM(CASE WHEN NOT lm.is_opening AND lm.dir = -1 THEN 1 ELSE 0 END) AS out_moves,
                    SUM(CASE WHEN NOT lm.is_opening AND lm.dir = -1 THEN lm.wt ELSE 0 END) AS out_wt,
                    MAX(CASE WHEN NOT lm.is_opening AND lm.category = 'sales_out' THEN 1 ELSE 0 END) AS has_sales_out,
                    MAX(CASE WHEN NOT lm.is_opening AND lm.category = 'transfer_out' THEN 1 ELSE 0 END) AS has_transfer_out,
                    SUM(lm.dir) AS close_dir,
                    SUM(lm.dir * lm.wt) AS close_wt,
                    MAX(lm.move_date) AS last_move_date
                FROM label_mv lm
                GROUP BY lm.branch_id, lm.label_id
            )
        """

    @staticmethod
    def _direct_label_where_clause(mode, branch_ids_filter, active_filter, include_no_vendor, search_query, params):
        """Build WHERE clauses for 'created' and 'closing' product.label modes."""
        eff_branch = "COALESCE(pl.branch_id, sw.branch_id, lot.branch_id, loc.branch_id)"
        eff_vendor = StockInflowOutflowReport._effective_vendor_sql()
        where = ["(pl.company_id IS NULL OR pl.company_id IN %(company_ids)s)"]

        if branch_ids_filter is not None:
            params['branch_ids'] = tuple(branch_ids_filter or [-1])
            where.append(f"{eff_branch} IN %(branch_ids)s")

        if mode == 'created':
            where.append("pl.create_date >= %(dt_from)s AND pl.create_date < %(dt_to)s")
        else:
            # closing mode: active labels created up to dt_to
            where.append("pl.create_date < %(dt_to)s")
            if active_filter == 'all':
                where.append("pl.active = TRUE")

        if active_filter == 'active':
            where.append("pl.active = TRUE")
        elif active_filter == 'inactive':
            where.append("pl.active = FALSE")

        if not include_no_vendor:
            where.append(f"{eff_vendor} <> 0")

        if search_query and search_query.strip():
            params['vsearch'] = f"%{search_query.strip()}%"
            where.append(f"""
                (
                    COALESCE(rp.name, 'Unassigned / No Vendor') ILIKE %(vsearch)s
                    OR COALESCE(pl.name, '') ILIKE %(vsearch)s
                    OR COALESCE(pl.barcode, '') ILIKE %(vsearch)s
                    OR COALESCE(pl.barcode2, '') ILIKE %(vsearch)s
                    OR COALESCE(po.name, '') ILIKE %(vsearch)s
                    OR COALESCE(pt.name->>%(lang)s, pt.name->>'en_US', pt.name::text, '') ILIKE %(vsearch)s
                )
            """)
        return eff_branch, eff_vendor, " AND ".join(where)

    @api.model
    def get_vendor_labels_summary(
        self,
        branch_id='all',
        date_from=None,
        date_to=None,
        mode='movement',
        include_no_vendor=True,
        only_period_activity=False,
        active_filter='all',
        search_query=None,
    ):
        """Return vendor-wise label KPIs and grouped vendor rows for the active Branch & Date."""
        branch_ids_filter, selected_branch_name, allowed_cids = self._resolve_branch_filter(branch_id)
        d_from, d_to, dt_from, dt_to = self._parse_date_bounds(date_from, date_to)
        mode = mode if mode in ('movement', 'created', 'closing') else 'movement'

        params = {
            'company_ids': allowed_cids,
            'dt_from': dt_from,
            'dt_to': dt_to,
            'lang': self._lang(),
        }
        if branch_ids_filter is not None:
            params['branch_ids'] = tuple(branch_ids_filter or [-1])

        cr = self.env.cr
        eff_vendor = self._effective_vendor_sql()

        if mode == 'movement':
            ctes = self._label_movement_ctes(branch_ids_filter)
            extra_where = ["(pbl.open_dir > 0 OR pbl.has_in = 1 OR pbl.has_out = 1 OR pbl.close_dir > 0)"]
            if not include_no_vendor:
                extra_where.append(f"{eff_vendor} <> 0")
            if only_period_activity:
                extra_where.append("(pbl.has_in = 1 OR pbl.has_out = 1)")
            if active_filter == 'active':
                extra_where.append("pl.active = TRUE")
            elif active_filter == 'inactive':
                extra_where.append("pl.active = FALSE")
            if search_query and search_query.strip():
                params['vsearch'] = f"%{search_query.strip()}%"
                extra_where.append("""
                    (
                        COALESCE(rp.name, 'Unassigned / No Vendor') ILIKE %(vsearch)s
                        OR COALESCE(pl.name, '') ILIKE %(vsearch)s
                        OR COALESCE(pl.barcode, '') ILIKE %(vsearch)s
                        OR COALESCE(po.name, '') ILIKE %(vsearch)s
                        OR COALESCE(pt.name->>%(lang)s, pt.name->>'en_US', pt.name::text, '') ILIKE %(vsearch)s
                    )
                """)

            sql = f"""
                WITH {ctes}
                SELECT
                    {eff_vendor} AS vendor_id,
                    COALESCE(rp.name, 'Unassigned / No Vendor') AS vendor_name,
                    COALESCE(rp.phone, rp.mobile, '') AS vendor_phone,
                    SUM(CASE WHEN pbl.open_dir > 0 THEN 1 ELSE 0 END) AS open_count,
                    ROUND(SUM(pbl.open_wt)::numeric, 3) AS open_wt,
                    SUM(pbl.has_in) AS in_count,
                    ROUND(SUM(pbl.in_wt)::numeric, 3) AS in_wt,
                    SUM(pbl.has_purchase_in) AS in_purchase_count,
                    SUM(pbl.has_transfer_in) AS in_transfer_count,
                    SUM(pbl.has_out) AS out_count,
                    ROUND(SUM(pbl.out_wt)::numeric, 3) AS out_wt,
                    SUM(pbl.has_sales_out) AS out_sale_count,
                    SUM(pbl.has_transfer_out) AS out_transfer_count,
                    SUM(CASE WHEN pbl.close_dir > 0 THEN 1 ELSE 0 END) AS close_count,
                    ROUND(SUM(pbl.close_wt)::numeric, 3) AS close_wt,
                    ROUND(SUM(CASE WHEN pbl.close_dir > 0 THEN COALESCE(pl.sale_net_weight, 0) ELSE 0 END)::numeric, 3) AS close_net_wt,
                    ROUND(SUM(CASE WHEN pbl.close_dir > 0 THEN COALESCE(pl.sale_net_weight, 0) * COALESCE(gp.percentage, 0) / 100.0 ELSE 0 END)::numeric, 3) AS close_fine_wt,
                    SUM(CASE WHEN pbl.close_dir > 0 AND pl.active THEN 1 ELSE 0 END) AS active_now_count,
                    SUM(CASE WHEN pbl.close_dir > 0 AND NOT pl.active THEN 1 ELSE 0 END) AS inactive_now_count
                FROM per_branch_label pbl
                JOIN product_label pl ON pl.id = pbl.label_id
                LEFT JOIN product_product pp ON pp.id = pl.product_id
                LEFT JOIN product_template pt ON pt.id = COALESCE(pp.product_tmpl_id, pl.product_template_id, pl.product_tmpl_id)
                LEFT JOIN gold_purity gp ON gp.id = pl.purity_id
                LEFT JOIN purchase_order po ON po.id = pl.purchase_id
                LEFT JOIN jewellery_job_work jw ON jw.id = pl.job_work_id
                LEFT JOIN res_partner rp ON rp.id = NULLIF({eff_vendor}, 0)
                WHERE {' AND '.join(extra_where)}
                GROUP BY 1, 2, 3
                ORDER BY ({eff_vendor} = 0), in_wt DESC, close_wt DESC, vendor_name ASC
            """
            cr.execute(sql, params)
            rows = cr.fetchall()

            vendors = []
            totals = {
                'vendor_count': 0,
                'open_count': 0, 'open_wt': 0.0,
                'in_count': 0, 'in_wt': 0.0,
                'out_count': 0, 'out_wt': 0.0,
                'net_wt': 0.0,
                'close_count': 0, 'close_wt': 0.0,
                'close_net_wt': 0.0, 'close_fine_wt': 0.0,
                'active_now_count': 0, 'inactive_now_count': 0,
            }
            for r in rows:
                vid = int(r[0] or 0)
                in_w = float(r[6] or 0.0)
                out_w = float(r[10] or 0.0)
                net_w = round(in_w - out_w, 3)
                v = {
                    'vendor_id': vid,
                    'vendor_name': r[1],
                    'vendor_phone': r[2] or '',
                    'is_unassigned': vid == 0,
                    'open_count': int(r[3] or 0),
                    'open_wt': float(r[4] or 0.0),
                    'in_count': int(r[5] or 0),
                    'in_wt': in_w,
                    'in_purchase_count': int(r[7] or 0),
                    'in_transfer_count': int(r[8] or 0),
                    'out_count': int(r[9] or 0),
                    'out_wt': out_w,
                    'out_sale_count': int(r[11] or 0),
                    'out_transfer_count': int(r[12] or 0),
                    'net_wt': net_w,
                    'close_count': int(r[13] or 0),
                    'close_wt': float(r[14] or 0.0),
                    'close_net_wt': float(r[15] or 0.0),
                    'close_fine_wt': float(r[16] or 0.0),
                    'active_now_count': int(r[17] or 0),
                    'inactive_now_count': int(r[18] or 0),
                }
                vendors.append(v)
                if not v['is_unassigned']:
                    totals['vendor_count'] += 1
                totals['open_count'] += v['open_count']
                totals['open_wt'] = round(totals['open_wt'] + v['open_wt'], 3)
                totals['in_count'] += v['in_count']
                totals['in_wt'] = round(totals['in_wt'] + v['in_wt'], 3)
                totals['out_count'] += v['out_count']
                totals['out_wt'] = round(totals['out_wt'] + v['out_wt'], 3)
                totals['net_wt'] = round(totals['net_wt'] + net_w, 3)
                totals['close_count'] += v['close_count']
                totals['close_wt'] = round(totals['close_wt'] + v['close_wt'], 3)
                totals['close_net_wt'] = round(totals['close_net_wt'] + v['close_net_wt'], 3)
                totals['close_fine_wt'] = round(totals['close_fine_wt'] + v['close_fine_wt'], 3)
                totals['active_now_count'] += v['active_now_count']
                totals['inactive_now_count'] += v['inactive_now_count']

            return {
                'mode': mode,
                'selected_branch_name': selected_branch_name,
                'date_from': d_from.strftime('%Y-%m-%d'),
                'date_to': d_to.strftime('%Y-%m-%d'),
                'kpis': totals,
                'vendors': vendors,
            }

        # Mode: 'created' or 'closing' (direct product_label aggregation)
        eff_branch, eff_vendor, where_sql = self._direct_label_where_clause(
            mode, branch_ids_filter, active_filter, include_no_vendor, search_query, params
        )
        sql = f"""
            SELECT
                {eff_vendor} AS vendor_id,
                COALESCE(rp.name, 'Unassigned / No Vendor') AS vendor_name,
                COALESCE(rp.phone, rp.mobile, '') AS vendor_phone,
                COUNT(*) AS total_count,
                SUM(CASE WHEN pl.active THEN 1 ELSE 0 END) AS active_count,
                ROUND(SUM(CASE WHEN pl.active THEN COALESCE(pl.sale_gross_weight, 0) ELSE 0 END)::numeric, 3) AS active_wt,
                SUM(CASE WHEN NOT pl.active THEN 1 ELSE 0 END) AS inactive_count,
                ROUND(SUM(CASE WHEN NOT pl.active THEN COALESCE(pl.sale_gross_weight, 0) ELSE 0 END)::numeric, 3) AS inactive_wt,
                ROUND(SUM(COALESCE(pl.sale_gross_weight, 0))::numeric, 3) AS gross_wt,
                ROUND(SUM(COALESCE(pl.sale_stone_weight, 0))::numeric, 3) AS stone_wt,
                ROUND(SUM(COALESCE(pl.sale_diamond_weight_gm, 0))::numeric, 3) AS diamond_wt,
                ROUND(SUM(COALESCE(pl.sale_net_weight, 0))::numeric, 3) AS net_wt,
                ROUND(SUM(COALESCE(pl.sale_net_weight, 0) * COALESCE(gp.percentage, 0) / 100.0)::numeric, 3) AS fine_wt
            FROM product_label pl
            LEFT JOIN stock_location loc ON loc.id = pl.branch_location_id
            LEFT JOIN stock_warehouse sw ON sw.id = loc.warehouse_id
            LEFT JOIN stock_location lot ON lot.id = sw.lot_stock_id
            LEFT JOIN product_product pp ON pp.id = pl.product_id
            LEFT JOIN product_template pt ON pt.id = COALESCE(pp.product_tmpl_id, pl.product_template_id, pl.product_tmpl_id)
            LEFT JOIN gold_purity gp ON gp.id = pl.purity_id
            LEFT JOIN purchase_order po ON po.id = pl.purchase_id
            LEFT JOIN jewellery_job_work jw ON jw.id = pl.job_work_id
            LEFT JOIN res_partner rp ON rp.id = NULLIF({eff_vendor}, 0)
            WHERE {where_sql}
            GROUP BY 1, 2, 3
            ORDER BY ({eff_vendor} = 0), gross_wt DESC, total_count DESC, vendor_name ASC
        """
        cr.execute(sql, params)
        rows = cr.fetchall()

        vendors = []
        totals = {
            'vendor_count': 0,
            'total_count': 0,
            'active_count': 0, 'active_wt': 0.0,
            'inactive_count': 0, 'inactive_wt': 0.0,
            'gross_wt': 0.0, 'stone_wt': 0.0, 'diamond_wt': 0.0,
            'net_wt': 0.0, 'fine_wt': 0.0,
        }
        for r in rows:
            vid = int(r[0] or 0)
            v = {
                'vendor_id': vid,
                'vendor_name': r[1],
                'vendor_phone': r[2] or '',
                'is_unassigned': vid == 0,
                'total_count': int(r[3] or 0),
                'active_count': int(r[4] or 0),
                'active_wt': float(r[5] or 0.0),
                'inactive_count': int(r[6] or 0),
                'inactive_wt': float(r[7] or 0.0),
                'gross_wt': float(r[8] or 0.0),
                'stone_wt': float(r[9] or 0.0),
                'diamond_wt': float(r[10] or 0.0),
                'net_wt': float(r[11] or 0.0),
                'fine_wt': float(r[12] or 0.0),
            }
            vendors.append(v)
            if not v['is_unassigned']:
                totals['vendor_count'] += 1
            totals['total_count'] += v['total_count']
            totals['active_count'] += v['active_count']
            totals['active_wt'] = round(totals['active_wt'] + v['active_wt'], 3)
            totals['inactive_count'] += v['inactive_count']
            totals['inactive_wt'] = round(totals['inactive_wt'] + v['inactive_wt'], 3)
            totals['gross_wt'] = round(totals['gross_wt'] + v['gross_wt'], 3)
            totals['stone_wt'] = round(totals['stone_wt'] + v['stone_wt'], 3)
            totals['diamond_wt'] = round(totals['diamond_wt'] + v['diamond_wt'], 3)
            totals['net_wt'] = round(totals['net_wt'] + v['net_wt'], 3)
            totals['fine_wt'] = round(totals['fine_wt'] + v['fine_wt'], 3)

        return {
            'mode': mode,
            'selected_branch_name': selected_branch_name,
            'date_from': d_from.strftime('%Y-%m-%d'),
            'date_to': d_to.strftime('%Y-%m-%d'),
            'kpis': totals,
            'vendors': vendors,
        }

    @api.model
    def get_vendor_label_lines(
        self,
        branch_id='all',
        date_from=None,
        date_to=None,
        vendor_id=None,
        mode='movement',
        flow_filter='all',
        include_no_vendor=True,
        active_filter='all',
        search_query=None,
        limit=50,
        offset=0,
    ):
        """Return paginated individual product.label rows for a vendor or all vendors."""
        branch_ids_filter, _, allowed_cids = self._resolve_branch_filter(branch_id)
        d_from, d_to, dt_from, dt_to = self._parse_date_bounds(date_from, date_to)
        mode = mode if mode in ('movement', 'created', 'closing') else 'movement'

        params = {
            'company_ids': allowed_cids,
            'dt_from': dt_from,
            'dt_to': dt_to,
            'lang': self._lang(),
            'limit': int(limit or 50),
            'offset': int(offset or 0),
        }
        if branch_ids_filter is not None:
            params['branch_ids'] = tuple(branch_ids_filter or [-1])

        cr = self.env.cr
        eff_vendor = self._effective_vendor_sql()

        if mode == 'movement':
            ctes = self._label_movement_ctes(branch_ids_filter)
            where = ["(pbl.open_dir > 0 OR pbl.has_in = 1 OR pbl.has_out = 1 OR pbl.close_dir > 0)"]
            if vendor_id is not None and vendor_id != '':
                params['vendor_id'] = int(vendor_id)
                where.append(f"{eff_vendor} = %(vendor_id)s")
            elif not include_no_vendor:
                where.append(f"{eff_vendor} <> 0")

            if flow_filter == 'inflow':
                where.append("pbl.has_in = 1")
            elif flow_filter == 'outflow':
                where.append("pbl.has_out = 1")
            elif flow_filter == 'closing':
                where.append("pbl.close_dir > 0")
            elif flow_filter == 'opening':
                where.append("pbl.open_dir > 0")

            if active_filter == 'active':
                where.append("pl.active = TRUE")
            elif active_filter == 'inactive':
                where.append("pl.active = FALSE")

            if search_query and search_query.strip():
                params['lsearch'] = f"%{search_query.strip()}%"
                where.append("""
                    (
                        COALESCE(pl.name, '') ILIKE %(lsearch)s
                        OR COALESCE(pl.barcode, '') ILIKE %(lsearch)s
                        OR COALESCE(pl.barcode2, '') ILIKE %(lsearch)s
                        OR COALESCE(rp.name, 'Unassigned / No Vendor') ILIKE %(lsearch)s
                        OR COALESCE(po.name, '') ILIKE %(lsearch)s
                        OR COALESCE(pt.name->>%(lang)s, pt.name->>'en_US', pt.name::text, '') ILIKE %(lsearch)s
                    )
                """)

            where_sql = " AND ".join(where)
            cr.execute(f"""
                WITH {ctes}
                SELECT COUNT(*),
                       ROUND(COALESCE(SUM(COALESCE(pl.sale_gross_weight, 0)), 0)::numeric, 3),
                       ROUND(COALESCE(SUM(COALESCE(pl.sale_net_weight, 0)), 0)::numeric, 3)
                FROM per_branch_label pbl
                JOIN product_label pl ON pl.id = pbl.label_id
                LEFT JOIN product_product pp ON pp.id = pl.product_id
                LEFT JOIN product_template pt ON pt.id = COALESCE(pp.product_tmpl_id, pl.product_template_id, pl.product_tmpl_id)
                LEFT JOIN purchase_order po ON po.id = pl.purchase_id
                LEFT JOIN jewellery_job_work jw ON jw.id = pl.job_work_id
                LEFT JOIN res_partner rp ON rp.id = NULLIF({eff_vendor}, 0)
                WHERE {where_sql}
            """, params)
            cnt_row = cr.fetchone()
            total_count = int(cnt_row[0] or 0)
            sum_gross = float(cnt_row[1] or 0.0)
            sum_net = float(cnt_row[2] or 0.0)

            cr.execute(f"""
                WITH {ctes}
                SELECT
                    pl.id AS label_id,
                    pl.name AS label_name,
                    COALESCE(pl.barcode, '') AS barcode,
                    COALESCE(pl.barcode2, '') AS barcode2,
                    {eff_vendor} AS vendor_id,
                    COALESCE(rp.name, 'Unassigned / No Vendor') AS vendor_name,
                    pl.product_id,
                    COALESCE(pt.name->>%(lang)s, pt.name->>'en_US', pt.name::text, '') AS tmpl_name,
                    COALESCE(gp.name, '') AS purity_name,
                    pl.purchase_id,
                    COALESCE(po.name, '') AS purchase_name,
                    pbl.branch_id,
                    rb.name AS branch_name,
                    COALESCE(loc.complete_name, '') AS location_name,
                    ROUND(COALESCE(pl.sale_gross_weight, 0)::numeric, 3) AS gross_wt,
                    ROUND(COALESCE(pl.sale_stone_weight, 0)::numeric, 3) AS stone_wt,
                    ROUND(COALESCE(pl.sale_diamond_weight_gm, 0)::numeric, 3) AS diamond_wt,
                    ROUND(COALESCE(pl.sale_diamond_weight_ct, 0)::numeric, 2) AS diamond_ct,
                    ROUND(COALESCE(pl.sale_net_weight, 0)::numeric, 3) AS net_wt,
                    ROUND((COALESCE(pl.sale_net_weight, 0) * COALESCE(gp.percentage, 0) / 100.0)::numeric, 3) AS fine_wt,
                    pl.create_date,
                    pbl.last_move_date,
                    pl.active,
                    pl.is_stocked_in,
                    pbl.open_dir,
                    pbl.has_in,
                    pbl.has_out,
                    pbl.close_dir,
                    ROUND(pbl.in_wt::numeric, 3) AS in_wt,
                    ROUND(pbl.out_wt::numeric, 3) AS out_wt,
                    ROUND(pbl.close_wt::numeric, 3) AS close_wt
                FROM per_branch_label pbl
                JOIN product_label pl ON pl.id = pbl.label_id
                JOIN res_branch rb ON rb.id = pbl.branch_id
                LEFT JOIN stock_location loc ON loc.id = pl.branch_location_id
                LEFT JOIN product_product pp ON pp.id = pl.product_id
                LEFT JOIN product_template pt ON pt.id = COALESCE(pp.product_tmpl_id, pl.product_template_id, pl.product_tmpl_id)
                LEFT JOIN gold_purity gp ON gp.id = pl.purity_id
                LEFT JOIN purchase_order po ON po.id = pl.purchase_id
                LEFT JOIN jewellery_job_work jw ON jw.id = pl.job_work_id
                LEFT JOIN res_partner rp ON rp.id = NULLIF({eff_vendor}, 0)
                WHERE {where_sql}
                ORDER BY pbl.last_move_date DESC, pl.id DESC
                LIMIT %(limit)s OFFSET %(offset)s
            """, params)
            rows = cr.fetchall()
            prod_info = self._resolve_product_names([r[6] for r in rows if r[6]])

            lines = []
            for r in rows:
                pid = r[6]
                has_in, has_out, close_dir = int(r[25] or 0), int(r[26] or 0), int(r[27] or 0)
                if has_in and has_out:
                    period_flow = 'in_out'
                    period_flow_label = 'In & Out'
                elif has_in:
                    period_flow = 'inflow'
                    period_flow_label = 'Inflow'
                elif has_out:
                    period_flow = 'outflow'
                    period_flow_label = 'Outflow'
                elif close_dir > 0:
                    period_flow = 'held'
                    period_flow_label = 'Opening / Held'
                else:
                    period_flow = 'other'
                    period_flow_label = 'Prior Out'

                lines.append({
                    'id': f"{r[0]}_{r[11]}",
                    'label_id': r[0],
                    'label_name': r[1] or '',
                    'barcode': r[2] or '',
                    'barcode2': r[3] or '',
                    'vendor_id': int(r[4] or 0),
                    'vendor_name': r[5],
                    'product_id': pid or False,
                    'product_name': prod_info.get(pid, {}).get('display_name') or self._extract_json_name(r[7]) or '-',
                    'purity_name': r[8] or '',
                    'purchase_id': r[9] or False,
                    'purchase_name': r[10] or '',
                    'branch_id': r[11],
                    'branch_name': r[12] or '',
                    'location_name': r[13] or '',
                    'gross_wt': float(r[14] or 0.0),
                    'stone_wt': float(r[15] or 0.0),
                    'diamond_wt': float(r[16] or 0.0),
                    'diamond_ct': float(r[17] or 0.0),
                    'net_wt': float(r[18] or 0.0),
                    'fine_wt': float(r[19] or 0.0),
                    'create_date': self._format_utc_to_local(r[20]),
                    'last_move_date': self._format_utc_to_local(r[21]),
                    'active': bool(r[22]),
                    'is_stocked_in': bool(r[23]),
                    'period_flow': period_flow,
                    'period_flow_label': period_flow_label,
                    'in_wt': float(r[28] or 0.0),
                    'out_wt': float(r[29] or 0.0),
                    'close_wt': float(r[30] or 0.0),
                })

            return {
                'lines': lines,
                'total_count': total_count,
                'sum_gross': sum_gross,
                'sum_net': sum_net,
            }

        # Direct product.label query ('created' or 'closing')
        eff_branch, eff_vendor, where_sql = self._direct_label_where_clause(
            mode, branch_ids_filter, active_filter, include_no_vendor, search_query, params
        )
        if vendor_id is not None and vendor_id != '':
            params['vendor_id'] = int(vendor_id)
            where_sql += f" AND {eff_vendor} = %(vendor_id)s"

        cr.execute(f"""
            SELECT COUNT(*),
                   ROUND(COALESCE(SUM(COALESCE(pl.sale_gross_weight, 0)), 0)::numeric, 3),
                   ROUND(COALESCE(SUM(COALESCE(pl.sale_net_weight, 0)), 0)::numeric, 3)
            FROM product_label pl
            LEFT JOIN stock_location loc ON loc.id = pl.branch_location_id
            LEFT JOIN stock_warehouse sw ON sw.id = loc.warehouse_id
            LEFT JOIN stock_location lot ON lot.id = sw.lot_stock_id
            LEFT JOIN product_product pp ON pp.id = pl.product_id
            LEFT JOIN product_template pt ON pt.id = COALESCE(pp.product_tmpl_id, pl.product_template_id, pl.product_tmpl_id)
            LEFT JOIN purchase_order po ON po.id = pl.purchase_id
            LEFT JOIN jewellery_job_work jw ON jw.id = pl.job_work_id
            LEFT JOIN res_partner rp ON rp.id = NULLIF({eff_vendor}, 0)
            WHERE {where_sql}
        """, params)
        cnt_row = cr.fetchone()
        total_count = int(cnt_row[0] or 0)
        sum_gross = float(cnt_row[1] or 0.0)
        sum_net = float(cnt_row[2] or 0.0)

        cr.execute(f"""
            SELECT
                pl.id AS label_id,
                pl.name AS label_name,
                COALESCE(pl.barcode, '') AS barcode,
                COALESCE(pl.barcode2, '') AS barcode2,
                {eff_vendor} AS vendor_id,
                COALESCE(rp.name, 'Unassigned / No Vendor') AS vendor_name,
                pl.product_id,
                COALESCE(pt.name->>%(lang)s, pt.name->>'en_US', pt.name::text, '') AS tmpl_name,
                COALESCE(gp.name, '') AS purity_name,
                pl.purchase_id,
                COALESCE(po.name, '') AS purchase_name,
                {eff_branch} AS branch_id,
                COALESCE(rb.name, '') AS branch_name,
                COALESCE(loc.complete_name, '') AS location_name,
                ROUND(COALESCE(pl.sale_gross_weight, 0)::numeric, 3) AS gross_wt,
                ROUND(COALESCE(pl.sale_stone_weight, 0)::numeric, 3) AS stone_wt,
                ROUND(COALESCE(pl.sale_diamond_weight_gm, 0)::numeric, 3) AS diamond_wt,
                ROUND(COALESCE(pl.sale_diamond_weight_ct, 0)::numeric, 2) AS diamond_ct,
                ROUND(COALESCE(pl.sale_net_weight, 0)::numeric, 3) AS net_wt,
                ROUND((COALESCE(pl.sale_net_weight, 0) * COALESCE(gp.percentage, 0) / 100.0)::numeric, 3) AS fine_wt,
                pl.create_date,
                pl.write_date,
                pl.active,
                pl.is_stocked_in
            FROM product_label pl
            LEFT JOIN stock_location loc ON loc.id = pl.branch_location_id
            LEFT JOIN stock_warehouse sw ON sw.id = loc.warehouse_id
            LEFT JOIN stock_location lot ON lot.id = sw.lot_stock_id
            LEFT JOIN res_branch rb ON rb.id = {eff_branch}
            LEFT JOIN product_product pp ON pp.id = pl.product_id
            LEFT JOIN product_template pt ON pt.id = COALESCE(pp.product_tmpl_id, pl.product_template_id, pl.product_tmpl_id)
            LEFT JOIN gold_purity gp ON gp.id = pl.purity_id
            LEFT JOIN purchase_order po ON po.id = pl.purchase_id
            LEFT JOIN jewellery_job_work jw ON jw.id = pl.job_work_id
            LEFT JOIN res_partner rp ON rp.id = NULLIF({eff_vendor}, 0)
            WHERE {where_sql}
            ORDER BY pl.create_date DESC, pl.id DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """, params)
        rows = cr.fetchall()
        prod_info = self._resolve_product_names([r[6] for r in rows if r[6]])

        lines = []
        for r in rows:
            pid = r[6]
            is_act = bool(r[22])
            lines.append({
                'id': str(r[0]),
                'label_id': r[0],
                'label_name': r[1] or '',
                'barcode': r[2] or '',
                'barcode2': r[3] or '',
                'vendor_id': int(r[4] or 0),
                'vendor_name': r[5],
                'product_id': pid or False,
                'product_name': prod_info.get(pid, {}).get('display_name') or self._extract_json_name(r[7]) or '-',
                'purity_name': r[8] or '',
                'purchase_id': r[9] or False,
                'purchase_name': r[10] or '',
                'branch_id': r[11] or False,
                'branch_name': r[12] or '',
                'location_name': r[13] or '',
                'gross_wt': float(r[14] or 0.0),
                'stone_wt': float(r[15] or 0.0),
                'diamond_wt': float(r[16] or 0.0),
                'diamond_ct': float(r[17] or 0.0),
                'net_wt': float(r[18] or 0.0),
                'fine_wt': float(r[19] or 0.0),
                'create_date': self._format_utc_to_local(r[20]),
                'last_move_date': self._format_utc_to_local(r[21]),
                'active': is_act,
                'is_stocked_in': bool(r[23]),
                'period_flow': 'active' if is_act else 'inactive',
                'period_flow_label': 'Active' if is_act else 'Sold / Inactive',
                'in_wt': float(r[14] or 0.0),
                'out_wt': 0.0,
                'close_wt': float(r[14] or 0.0) if is_act else 0.0,
            })

        return {
            'lines': lines,
            'total_count': total_count,
            'sum_gross': sum_gross,
            'sum_net': sum_net,
        }
