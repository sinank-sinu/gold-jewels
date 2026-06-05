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
        # Clear previous report lines for this user
        self.env['stock.summary.report.line'].search([('create_uid', '=', self.env.user.id)]).unlink()

        # Get all products and variants
        products = self.env['product.product'].search([('active', '=', True)])
        
        report_lines = []
        
        # Internal Locations Domain
        internal_loc_domain = [('usage', '=', 'internal')]
        if self.branch_ids:
            internal_loc_domain.append(('branch_id', 'in', self.branch_ids.ids))
        internal_locations = self.env['stock.location'].search(internal_loc_domain)
        internal_loc_ids = internal_locations.ids

        # Number of days in the period
        no_of_days = (self.end_date - self.start_date).days + 1

        for product in products:
            # Domain for opening stock (before start_date)
            opening_domain = [
                ('product_id', '=', product.id),
                ('state', '=', 'done'),
                ('date', '<', self.start_date)
            ]
            
            # Domain for period movements
            period_domain = [
                ('product_id', '=', product.id),
                ('state', '=', 'done'),
                ('date', '>=', self.start_date),
                ('date', '<=', datetime.combine(self.end_date, datetime.max.time()))
            ]

            # Helper to calculate weights/pieces from moves
            def get_stats(moves, loc_ids, mode='in'):
                pcs = 0.0
                gross = 0.0
                net = 0.0
                for move in moves:
                    is_in = move.location_dest_id.id in loc_ids and move.location_id.id not in loc_ids
                    is_out = move.location_id.id in loc_ids and move.location_dest_id.id not in loc_ids
                    
                    # For opening, we look at the net effect
                    if mode == 'opening':
                        coef = 0
                        if move.location_dest_id.id in loc_ids: coef += 1
                        if move.location_id.id in loc_ids: coef -= 1
                    elif mode == 'in':
                        coef = 1 if is_in else 0
                    elif mode == 'out':
                        coef = 1 if is_out else 0
                    else:
                        coef = 0

                    if coef == 0:
                        continue

                    # Pieces
                    m_pcs = 0.0
                    if move.label_id:
                        m_pcs = 1.0
                    elif move.product_uom.category_id.name in ['Unit', 'Working Time']:
                        m_pcs = move.product_uom_qty
                    
                    # Gross Weight
                    m_gross = 0.0
                    if move.label_id:
                        m_gross = move.label_id.purchase_gross_weight
                    elif 'grams' in move._fields and move.grams:
                        m_gross = move.grams
                    elif move.product_uom.category_id.name == 'Weight':
                        m_gross = move.product_uom_qty
                    
                    # Net Weight
                    m_net = 0.0
                    if move.label_id:
                        m_net = move.label_id.purchase_net_weight
                    else:
                        # Fallback for net weight
                        purity_percent = move.purity_id.percentage if move.purity_id else product.purity_id.percentage
                        if purity_percent:
                            m_net = m_gross * (purity_percent / 100.0)
                        else:
                            m_net = m_gross

                    pcs += m_pcs * coef
                    gross += m_gross * coef
                    net += m_net * coef
                
                return pcs, gross, net

            # Calculate Opening
            opening_moves = self.env['stock.move'].search(opening_domain)
            o_pcs, o_gross, o_net = get_stats(opening_moves, internal_loc_ids, mode='opening')

            # Calculate Period In/Out
            period_moves = self.env['stock.move'].search(period_domain)
            in_pcs, in_gross, in_net = get_stats(period_moves, internal_loc_ids, mode='in')
            out_pcs, out_gross, out_net = get_stats(period_moves, internal_loc_ids, mode='out')

            # Closing
            c_pcs = o_pcs + in_pcs - out_pcs
            c_gross = o_gross + in_gross - out_gross
            c_net = o_net + in_net - out_net

            # New metrics
            avg_inventory = (o_gross + c_gross) / 2.0
            turnover_ratio = (out_gross / avg_inventory) if avg_inventory > 0 else 0.0
            dio = round(no_of_days / turnover_ratio) if turnover_ratio > 0 else 0.0
            
            # Minimum stock level from reordering rules
            reordering_rule = self.env['stock.warehouse.orderpoint'].search([
                ('product_id', '=', product.id),
                ('location_id', 'in', internal_loc_ids)
            ], limit=1)
            min_stock = reordering_rule.product_min_qty if reordering_rule else 0.0
            stock_gap = c_gross - min_stock
            # Fetch ageing from product.label
            label = self.env['product.label'].search([
                ('product_id', '=', product.id)
            ], limit=1)
            purity_id = label.purity_id.id if label and label.purity_id else False
            ageing = label.age if label else 0

            #Attribute values
            attribute_values = ', '.join(
                product.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id.name'
                )
            )
            
            # Only add to report if there is any activity or stock
            if any([o_pcs, o_gross, o_net, in_pcs, in_gross, in_net, out_pcs, out_gross, out_net, c_pcs, c_gross, c_net, min_stock]):
                report_lines.append({
                    'product_id': product.id,
                    'product_template_id': product.product_tmpl_id.id,
                    'opening_pcs': o_pcs,
                    'opening_gross_weight': o_gross,
                    'opening_net_weight': o_net,
                    'in_pcs': in_pcs,
                    'in_gross_weight': in_gross,
                    'in_net_weight': in_net,
                    'out_pcs': out_pcs,
                    'out_gross_weight': out_gross,
                    'out_net_weight': out_net,
                    'closing_pcs': c_pcs,
                    'closing_gross_weight': c_gross,
                    'closing_net_weight': c_net,
                    'average_inventory': avg_inventory,
                    'no_of_days': no_of_days,
                    'min_stock_level': min_stock,
                    'turnover_ratio': turnover_ratio,
                    'dio': dio,
                    'stock_gap': stock_gap,
                    'purity_id': purity_id,
                    'ageing': ageing,
                    'attribute_values': attribute_values,
                })

        if report_lines:
            self.env['stock.summary.report.line'].create(report_lines)

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
    attribute_values = fields.Char(string="Attributes")
