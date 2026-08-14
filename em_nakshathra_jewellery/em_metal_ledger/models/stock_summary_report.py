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

        # Create indexes for instant querying if they don't already exist
        cr.execute("CREATE INDEX IF NOT EXISTS idx_stock_move_label_date_state ON stock_move (label_id, state, date)")
        cr.execute("CREATE INDEX IF NOT EXISTS idx_sale_order_line_label_state ON sale_order_line (label_id, state)")
        cr.execute("CREATE INDEX IF NOT EXISTS idx_product_label_branch_created ON product_label (branch_id, create_date, active)")

        cr.execute("DELETE FROM stock_summary_report_line WHERE create_uid = %s", (self.env.uid,))

        start_dt = datetime.combine(self.start_date, datetime.min.time())
        end_dt = datetime.combine(self.end_date, datetime.max.time())
        no_of_days = (self.end_date - self.start_date).days + 1

        branch_ids = self.branch_ids.ids if self.branch_ids else []

        query = """
        WITH internal_locs AS (
            SELECT id FROM stock_location 
            WHERE usage = 'internal'
              AND (%s::int[] IS NULL OR cardinality(%s::int[]) = 0 OR branch_id = ANY(%s::int[]))
        ),
        relevant_labels AS (
            SELECT pl.id AS label_id, pl.product_id, pl.purity_id,
                   COALESCE(pl.purchase_gross_weight, 0.0) AS gross_wt,
                   COALESCE(pl.purchase_net_weight, 0.0) AS net_wt,
                   pl.create_date, COALESCE(pl.age_import, 0) AS ageing
            FROM product_label pl
            WHERE (%s::int[] IS NULL OR cardinality(%s::int[]) = 0 OR pl.branch_id = ANY(%s::int[]))
              AND (
                (pl.create_date BETWEEN %s AND %s)
                OR (pl.create_date < %s AND pl.active = true)
                OR pl.id IN (
                    SELECT sm.label_id FROM stock_move sm
                    WHERE sm.state = 'done' AND sm.date BETWEEN %s AND %s AND sm.label_id IS NOT NULL
                      AND (sm.location_id IN (SELECT id FROM internal_locs) OR sm.location_dest_id IN (SELECT id FROM internal_locs))
                )
                OR pl.id IN (
                    SELECT sol.label_id FROM sale_order_line sol
                    JOIN sale_order so ON so.id = sol.order_id
                    WHERE sol.state IN ('sale','done') AND so.date_order BETWEEN %s AND %s AND sol.label_id IS NOT NULL
                      AND (%s::int[] IS NULL OR cardinality(%s::int[]) = 0 OR so.branch_id = ANY(%s::int[]))
                )
            )
        ),
        sold_before AS (
            SELECT DISTINCT sol.label_id
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            WHERE sol.state IN ('sale','done') AND so.date_order < %s AND sol.label_id IS NOT NULL
              AND (%s::int[] IS NULL OR cardinality(%s::int[]) = 0 OR so.branch_id = ANY(%s::int[]))
        ),
        out_before AS (
            SELECT sm.label_id, COUNT(*) AS out_cnt
            FROM stock_move sm
            WHERE sm.state = 'done' AND sm.date < %s AND sm.label_id IS NOT NULL
              AND sm.location_id IN (SELECT id FROM internal_locs)
              AND sm.location_dest_id NOT IN (SELECT id FROM internal_locs)
            GROUP BY sm.label_id
        ),
        sold_in_period AS (
            SELECT DISTINCT sol.label_id
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            WHERE sol.state IN ('sale','done') AND so.date_order BETWEEN %s AND %s AND sol.label_id IS NOT NULL
              AND (%s::int[] IS NULL OR cardinality(%s::int[]) = 0 OR so.branch_id = ANY(%s::int[]))
        ),
        out_period AS (
            SELECT sm.label_id, COUNT(*) AS out_cnt
            FROM stock_move sm
            WHERE sm.state = 'done' AND sm.date BETWEEN %s AND %s AND sm.label_id IS NOT NULL
              AND sm.location_id IN (SELECT id FROM internal_locs)
              AND sm.location_dest_id NOT IN (SELECT id FROM internal_locs)
            GROUP BY sm.label_id
        ),
        min_stocks AS (
            SELECT product_id, MIN(product_min_qty) AS min_qty
            FROM stock_warehouse_orderpoint
            WHERE location_id IN (SELECT id FROM internal_locs)
            GROUP BY product_id
        ),
        product_attrs AS (
            SELECT pp.id AS product_id,
                MAX(CASE WHEN LOWER(TRIM(pa.name::text)) IN ('"type"','type','"item type"','item type','"product type"','product type') THEN pav.name::text END) AS type_val,
                MAX(CASE WHEN LOWER(TRIM(pa.name::text)) IN ('"variety"','variety','"verity"','verity') THEN pav.name::text END) AS variety_val,
                MAX(CASE WHEN LOWER(TRIM(pa.name::text)) IN ('"design"','design') THEN pav.name::text END) AS design_val,
                MAX(CASE WHEN LOWER(TRIM(pa.name::text)) IN ('"size"','size') THEN pav.name::text END) AS size_val,
                MAX(CASE WHEN LOWER(TRIM(pa.name::text)) IN ('"stone colour"','stone colour','"stone color"','stone color') THEN pav.name::text END) AS stone_val,
                MAX(CASE WHEN LOWER(TRIM(pa.name::text)) IN ('"metal colour"','metal colour','"metal color"','metal color') THEN pav.name::text END) AS metal_val
            FROM product_product pp
            JOIN product_template_attribute_value ptav ON ptav.product_tmpl_id = pp.product_tmpl_id
            JOIN product_attribute_value pav ON pav.id = ptav.product_attribute_value_id
            JOIN product_attribute pa ON pa.id = pav.attribute_id
            GROUP BY pp.id
        ),
        computed AS (
            SELECT
                rl.product_id,
                rl.label_id,
                rl.purity_id,
                rl.ageing,
                -- Opening
                (CASE WHEN rl.create_date < %s AND sb.label_id IS NULL AND COALESCE(ob.out_cnt, 0) = 0 THEN 1.0 ELSE 0.0 END) AS o_pcs,
                (CASE WHEN rl.create_date < %s AND sb.label_id IS NULL AND COALESCE(ob.out_cnt, 0) = 0 THEN rl.gross_wt ELSE 0.0 END) AS o_gross,
                (CASE WHEN rl.create_date < %s AND sb.label_id IS NULL AND COALESCE(ob.out_cnt, 0) = 0 THEN rl.net_wt ELSE 0.0 END) AS o_net,
                -- In
                (CASE WHEN rl.create_date BETWEEN %s AND %s THEN 1.0 ELSE 0.0 END) AS in_pcs,
                (CASE WHEN rl.create_date BETWEEN %s AND %s THEN rl.gross_wt ELSE 0.0 END) AS in_gross,
                (CASE WHEN rl.create_date BETWEEN %s AND %s THEN rl.net_wt ELSE 0.0 END) AS in_net,
                -- Out
                (CASE WHEN sip.label_id IS NOT NULL THEN 1.0 ELSE COALESCE(op.out_cnt, 0)::float END) AS out_pcs,
                (CASE WHEN sip.label_id IS NOT NULL THEN rl.gross_wt ELSE rl.gross_wt * COALESCE(op.out_cnt, 0) END) AS out_gross,
                (CASE WHEN sip.label_id IS NOT NULL THEN rl.net_wt ELSE rl.net_wt * COALESCE(op.out_cnt, 0) END) AS out_net,
                
                COALESCE(ms.min_qty, 0.0) AS min_stock,
                COALESCE(pa.type_val, '') AS type_val,
                COALESCE(pa.variety_val, '') AS variety_val,
                COALESCE(pa.design_val, '') AS design_val,
                COALESCE(pa.size_val, '') AS size_val,
                COALESCE(pa.stone_val, '') AS stone_val,
                COALESCE(pa.metal_val, '') AS metal_val
            FROM relevant_labels rl
            LEFT JOIN sold_before sb ON sb.label_id = rl.label_id
            LEFT JOIN out_before ob ON ob.label_id = rl.label_id
            LEFT JOIN sold_in_period sip ON sip.label_id = rl.label_id
            LEFT JOIN out_period op ON op.label_id = rl.label_id
            LEFT JOIN min_stocks ms ON ms.product_id = rl.product_id
            LEFT JOIN product_attrs pa ON pa.product_id = rl.product_id
            WHERE rl.product_id IS NOT NULL
        )
        INSERT INTO stock_summary_report_line (
            product_id, label_id, purity_id, ageing,
            opening_pcs, opening_gross_weight, opening_net_weight,
            in_pcs, in_gross_weight, in_net_weight,
            out_pcs, out_gross_weight, out_net_weight,
            closing_pcs, closing_gross_weight, closing_net_weight,
            average_inventory, no_of_days, min_stock_level,
            turnover_ratio, dio, stock_gap,
            type_value, variety_value, design_value, size_value,
            stone_colour_value, metal_colour_value,
            create_date, create_uid, write_date, write_uid
        )
        SELECT
            product_id, label_id, purity_id, ageing,
            o_pcs, o_gross, o_net,
            in_pcs, in_gross, in_net,
            out_pcs, out_gross, out_net,
            (o_pcs + in_pcs - out_pcs) AS closing_pcs,
            (o_gross + in_gross - out_gross) AS closing_gross_weight,
            (o_net + in_net - out_net) AS closing_net_weight,
            -- average_inventory
            (CASE 
                WHEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0 > 0 THEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0
                WHEN (in_gross > 0 OR out_gross > 0) THEN (in_gross + out_gross) / 4.0
                ELSE 0.0
            END) AS average_inventory,
            %s AS no_of_days,
            min_stock AS min_stock_level,
            -- turnover_ratio
            (CASE 
                WHEN (CASE 
                        WHEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0 > 0 THEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0
                        WHEN (in_gross > 0 OR out_gross > 0) THEN (in_gross + out_gross) / 4.0
                        ELSE 0.0
                    END) > 0.0001 
                THEN out_gross / (CASE 
                        WHEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0 > 0 THEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0
                        WHEN (in_gross > 0 OR out_gross > 0) THEN (in_gross + out_gross) / 4.0
                        ELSE 0.0
                    END)
                ELSE 0.0
            END) AS turnover_ratio,
            -- dio
            (CASE 
                WHEN (CASE 
                        WHEN (CASE 
                                WHEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0 > 0 THEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0
                                WHEN (in_gross > 0 OR out_gross > 0) THEN (in_gross + out_gross) / 4.0
                                ELSE 0.0
                            END) > 0.0001 
                        THEN out_gross / (CASE 
                                WHEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0 > 0 THEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0
                                WHEN (in_gross > 0 OR out_gross > 0) THEN (in_gross + out_gross) / 4.0
                                ELSE 0.0
                            END)
                        ELSE 0.0
                    END) > 0.0001
                THEN ROUND(%s::numeric / (out_gross / (CASE 
                        WHEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0 > 0 THEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0
                        WHEN (in_gross > 0 OR out_gross > 0) THEN (in_gross + out_gross) / 4.0
                        ELSE 0.0
                    END)))
                WHEN (CASE 
                        WHEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0 > 0 THEN (o_gross + (o_gross + in_gross - out_gross)) / 2.0
                        WHEN (in_gross > 0 OR out_gross > 0) THEN (in_gross + out_gross) / 4.0
                        ELSE 0.0
                    END) > 0.0001 THEN %s
                ELSE 0.0
            END) AS dio,
            ((o_gross + in_gross - out_gross) - min_stock) AS stock_gap,
            type_val, variety_val, design_val, size_val, stone_val, metal_val,
            NOW(), %s, NOW(), %s
        FROM computed
        WHERE (o_pcs != 0 OR o_gross != 0 OR in_pcs != 0 OR in_gross != 0 OR out_pcs != 0 OR out_gross != 0 OR (o_pcs + in_pcs - out_pcs) != 0 OR (o_gross + in_gross - out_gross) != 0 OR min_stock != 0);
        """

        params = [
            # internal_locs
            branch_ids, branch_ids, branch_ids,
            # relevant_labels
            branch_ids, branch_ids, branch_ids,
            start_dt, end_dt, start_dt,
            start_dt, end_dt,
            start_dt, end_dt, branch_ids, branch_ids, branch_ids,
            # sold_before
            start_dt, branch_ids, branch_ids, branch_ids,
            # out_before
            start_dt,
            # sold_in_period
            start_dt, end_dt, branch_ids, branch_ids, branch_ids,
            # out_period
            start_dt, end_dt,
            # computed Opening & In
            start_dt, start_dt, start_dt,
            start_dt, end_dt, start_dt, end_dt, start_dt, end_dt,
            # SELECT no_of_days & dio & uid
            no_of_days, no_of_days, no_of_days, self.env.uid, self.env.uid
        ]

        cr.execute(query, params)
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
