from odoo import models, fields, api, _
from datetime import datetime


class StockSummaryReportWizard(models.TransientModel):
    _name = 'stock.summary.report.wizard'
    _description = 'Stock Summary Report Wizard'

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True, default=fields.Date.today)
    branch_ids = fields.Many2many('res.branch', string='Branches')

    def action_generate_report(self):
        self.ensure_one()
        cr = self.env.cr

        cr.execute("DELETE FROM stock_summary_report_line WHERE create_uid = %s", (self.env.uid,))

        start_dt = datetime.combine(self.start_date, datetime.min.time())
        end_dt = datetime.combine(self.end_date, datetime.max.time())
        no_of_days = (self.end_date - self.start_date).days + 1

        # Internal locations
        if self.branch_ids:
            cr.execute(
                "SELECT id FROM stock_location WHERE usage = 'internal' AND branch_id = ANY(%s)",
                (self.branch_ids.ids,)
            )
        else:
            cr.execute("SELECT id FROM stock_location WHERE usage = 'internal'")
        internal_loc_ids = [r[0] for r in cr.fetchall()]
        if not internal_loc_ids:
            return self._open_report_action()

        branch_label_sql = "AND pl.branch_id IN %s" if self.branch_ids else ""
        branch_so_sql = "AND so.branch_id IN %s" if self.branch_ids else ""
        # Use tuple for IN %s — psycopg2 reliably expands tuples as SQL IN (x, y, z)
        bp = [tuple(self.branch_ids.ids)] if self.branch_ids else []

        # 1a. Labels created during period
        cr.execute(f"""
            SELECT pl.id, pl.product_id, pl.purity_id,
                   pl.purchase_gross_weight, pl.purchase_net_weight,
                   pl.create_date, pl.active, pl.age_import
            FROM product_label pl
            WHERE pl.create_date BETWEEN %s AND %s
            {branch_label_sql}
        """, [start_dt, end_dt] + bp)
        labels_in_period = {r[0]: r for r in cr.fetchall()}

        # 1b. Active labels created before period
        cr.execute(f"""
            SELECT pl.id, pl.product_id, pl.purity_id,
                   pl.purchase_gross_weight, pl.purchase_net_weight,
                   pl.create_date, pl.active, pl.age_import
            FROM product_label pl
            WHERE pl.create_date < %s AND pl.active = true
            {branch_label_sql}
        """, [start_dt] + bp)
        labels_before = {r[0]: r for r in cr.fetchall()}

        # 1c. Labels moved during period
        cr.execute(f"""
            SELECT DISTINCT sm.label_id,
                   pl.product_id, pl.purity_id,
                   pl.purchase_gross_weight, pl.purchase_net_weight,
                   pl.create_date, pl.active, pl.age_import
            FROM stock_move sm
            JOIN product_label pl ON pl.id = sm.label_id
            WHERE sm.state = 'done'
              AND sm.date BETWEEN %s AND %s
              AND sm.label_id IS NOT NULL
              AND (sm.location_id = ANY(%s) OR sm.location_dest_id = ANY(%s))
            {branch_label_sql}
        """, [start_dt, end_dt, internal_loc_ids, internal_loc_ids] + bp)
        labels_moved = {r[0]: r for r in cr.fetchall()}

        # 1d. Labels sold during period
        cr.execute(f"""
            SELECT DISTINCT sol.label_id,
                   pl.product_id, pl.purity_id,
                   pl.purchase_gross_weight, pl.purchase_net_weight,
                   pl.create_date, pl.active, pl.age_import
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            JOIN product_label pl ON pl.id = sol.label_id
            WHERE sol.state IN ('sale','done')
              AND so.date_order BETWEEN %s AND %s
              AND sol.label_id IS NOT NULL
            {branch_so_sql}
        """, [start_dt, end_dt] + bp)
        labels_sold = {r[0]: r for r in cr.fetchall()}

        # Merge all relevant labels
        all_labels = {}
        all_labels.update(labels_before)
        all_labels.update(labels_in_period)
        all_labels.update(labels_moved)
        all_labels.update(labels_sold)

        if not all_labels:
            return self._open_report_action()

        all_label_ids = list(all_labels.keys())
        all_product_ids = list({r[1] for r in all_labels.values() if r[1]})

        # 2. Opening moves (before start_date) - aggregated by label
        cr.execute("""
            SELECT sm.label_id,
                   SUM(CASE WHEN sm.location_dest_id = ANY(%s)
                                 AND NOT (sm.location_id = ANY(%s)) THEN 1 ELSE 0 END) AS in_count,
                   SUM(CASE WHEN sm.location_id = ANY(%s)
                                 AND NOT (sm.location_dest_id = ANY(%s)) THEN 1 ELSE 0 END) AS out_count
            FROM stock_move sm
            WHERE sm.state = 'done'
              AND sm.date < %s
              AND sm.label_id = ANY(%s)
              AND (sm.location_id = ANY(%s) OR sm.location_dest_id = ANY(%s))
            GROUP BY sm.label_id
        """, [internal_loc_ids, internal_loc_ids,
              internal_loc_ids, internal_loc_ids,
              start_dt, all_label_ids,
              internal_loc_ids, internal_loc_ids])
        opening_by_label = {r[0]: (r[1], r[2]) for r in cr.fetchall()}

        # Labels sold before start date
        cr.execute("""
            SELECT DISTINCT sol.label_id
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            WHERE sol.state IN ('sale','done')
              AND so.date_order < %s
              AND sol.label_id = ANY(%s)
        """, [start_dt, all_label_ids])
        sold_before_ids = {r[0] for r in cr.fetchall()}

        # 3. Period moves - aggregated by label
        cr.execute("""
            SELECT sm.label_id,
                   SUM(CASE WHEN sm.location_dest_id = ANY(%s)
                                 AND NOT (sm.location_id = ANY(%s)) THEN 1 ELSE 0 END) AS in_count,
                   SUM(CASE WHEN sm.location_id = ANY(%s)
                                 AND NOT (sm.location_dest_id = ANY(%s)) THEN 1 ELSE 0 END) AS out_count
            FROM stock_move sm
            WHERE sm.state = 'done'
              AND sm.date BETWEEN %s AND %s
              AND sm.label_id = ANY(%s)
              AND (sm.location_id = ANY(%s) OR sm.location_dest_id = ANY(%s))
            GROUP BY sm.label_id
        """, [internal_loc_ids, internal_loc_ids,
              internal_loc_ids, internal_loc_ids,
              start_dt, end_dt, all_label_ids,
              internal_loc_ids, internal_loc_ids])
        period_by_label = {r[0]: (r[1], r[2]) for r in cr.fetchall()}

        # Labels sold during period
        cr.execute("""
            SELECT DISTINCT sol.label_id
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            WHERE sol.state IN ('sale','done')
              AND so.date_order BETWEEN %s AND %s
              AND sol.label_id = ANY(%s)
        """, [start_dt, end_dt, all_label_ids])
        sold_in_period_ids = {r[0] for r in cr.fetchall()}

        # 4. Min stock by product
        cr.execute("""
            SELECT product_id, MIN(product_min_qty)
            FROM stock_warehouse_orderpoint
            WHERE location_id = ANY(%s) AND product_id = ANY(%s)
            GROUP BY product_id
        """, [internal_loc_ids, all_product_ids])
        min_stock_by_product = {r[0]: r[1] for r in cr.fetchall()}

        # 5. Product attributes
        cr.execute("""
            SELECT pp.id,
                   pa.name::text,
                   pav.name::text
            FROM product_product pp
            JOIN product_template_attribute_value ptav ON ptav.product_tmpl_id = pp.product_tmpl_id
            JOIN product_attribute_value pav ON pav.id = ptav.product_attribute_value_id
            JOIN product_attribute pa ON pa.id = pav.attribute_id
            WHERE pp.id = ANY(%s)
        """, [all_product_ids])
        attr_by_product = {}
        for prod_id, aname, aval in cr.fetchall():
            attr_by_product.setdefault(prod_id, {})[aname.strip().lower()] = aval

        # 6. Build and insert report lines
        report_lines = []
        now_ts = datetime.now()
        uid = self.env.uid

        for label_id, ldata in all_labels.items():
            _, product_id, purity_id, gross_wt, net_wt, create_date, active, ageing = ldata
            if not product_id:
                continue

            if isinstance(create_date, datetime):
                create_dt = create_date
            elif create_date:
                create_dt = datetime.fromisoformat(str(create_date))
            else:
                create_dt = None

            # Opening
            if create_dt and create_dt < start_dt:
                op = opening_by_label.get(label_id, (0, 0))
                was_sold_before = label_id in sold_before_ids or (op[1] > 0)
                if not was_sold_before:
                    o_pcs, o_gross, o_net = 1.0, gross_wt or 0.0, net_wt or 0.0
                else:
                    o_pcs, o_gross, o_net = 0.0, 0.0, 0.0
            else:
                o_pcs, o_gross, o_net = 0.0, 0.0, 0.0

            # In
            if create_dt and start_dt <= create_dt <= end_dt:
                in_pcs, in_gross, in_net = 1.0, gross_wt or 0.0, net_wt or 0.0
            else:
                in_pcs, in_gross, in_net = 0.0, 0.0, 0.0

            # Out
            if label_id in sold_in_period_ids:
                out_pcs, out_gross, out_net = 1.0, gross_wt or 0.0, net_wt or 0.0
            else:
                pv = period_by_label.get(label_id, (0, 0))
                out_pcs = float(pv[1])
                out_gross = (gross_wt or 0.0) * out_pcs
                out_net = (net_wt or 0.0) * out_pcs

            c_pcs = o_pcs + in_pcs - out_pcs
            c_gross = o_gross + in_gross - out_gross
            c_net = o_net + in_net - out_net

            avg_inv = (o_gross + c_gross) / 2.0
            if avg_inv <= 0.0 and (in_gross > 0.0 or out_gross > 0.0):
                avg_inv = (in_gross + out_gross) / 4.0
            turnover = (out_gross / avg_inv) if avg_inv > 0.0001 else 0.0
            dio = round(no_of_days / turnover) if turnover > 0.0001 else (no_of_days if avg_inv > 0.0001 else 0.0)

            min_stock = float(min_stock_by_product.get(product_id, 0.0) or 0.0)
            stock_gap = c_gross - min_stock

            attrs = attr_by_product.get(product_id, {})
            type_val = attrs.get('type', attrs.get('item type', attrs.get('product type', '')))
            variety_val = attrs.get('variety', attrs.get('verity', ''))
            design_val = attrs.get('design', '')
            size_val = attrs.get('size', '')
            stone_val = attrs.get('stone colour', attrs.get('stone color', ''))
            metal_val = attrs.get('metal colour', attrs.get('metal color', ''))

            if not any([o_pcs, o_gross, in_pcs, in_gross, out_pcs, out_gross, c_pcs, c_gross, min_stock]):
                continue

            report_lines.append((
                product_id, label_id, purity_id or None,
                ageing or 0,
                o_pcs, o_gross, o_net,
                in_pcs, in_gross, in_net,
                out_pcs, out_gross, out_net,
                c_pcs, c_gross, c_net,
                avg_inv, no_of_days, min_stock, turnover, dio, stock_gap,
                type_val, variety_val, design_val, size_val,
                stone_val, metal_val,
                now_ts, uid, now_ts, uid,
            ))

        if report_lines:
            cr.executemany("""
                INSERT INTO stock_summary_report_line
                    (product_id, label_id, purity_id, ageing,
                     opening_pcs, opening_gross_weight, opening_net_weight,
                     in_pcs, in_gross_weight, in_net_weight,
                     out_pcs, out_gross_weight, out_net_weight,
                     closing_pcs, closing_gross_weight, closing_net_weight,
                     average_inventory, no_of_days, min_stock_level,
                     turnover_ratio, dio, stock_gap,
                     type_value, variety_value, design_value, size_value,
                     stone_colour_value, metal_colour_value,
                     create_date, create_uid, write_date, write_uid)
                VALUES (%s,%s,%s,%s, %s,%s,%s, %s,%s,%s, %s,%s,%s,
                        %s,%s,%s, %s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s, %s,%s,%s,%s)
            """, report_lines)

        return self._open_report_action()

    def _open_report_action(self):
        return {
            'name': _('Stock Summary Report'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.summary.report.line',
            'view_mode': 'tree',
            'context': {'search_default_group_by_product': 1},
        }

    def action_print_xlsx(self):
        self.ensure_one()
        self.action_generate_report()
        branch_names = ', '.join(self.branch_ids.mapped('name')) if self.branch_ids else 'All Branches'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/metal_ledger/export_stock_summary?start_date={self.start_date}&end_date={self.end_date}&branch_name={branch_names}',
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
