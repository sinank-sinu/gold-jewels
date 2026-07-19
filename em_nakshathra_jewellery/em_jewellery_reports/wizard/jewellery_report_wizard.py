from odoo import models, fields, api, _
from datetime import datetime, date
from odoo.exceptions import UserError


class JewelleryReportWizard(models.TransientModel):
    _name = 'jewellery.report.wizard'
    _description = 'Jewellery Report Wizard'

    date_from = fields.Date(string="Date From")
    date_to = fields.Date(string="Date To")

    branch_ids = fields.Many2many('res.branch', string="Branches")
    location_ids = fields.Many2many('stock.location', string="Locations", domain="[('usage', '=', 'internal')]")
    product_ids = fields.Many2many('product.product', string="Products")
    category_ids = fields.Many2many('product.category', string="Ornament Categories")
    purity_ids = fields.Many2many('gold.purity', string="Purities")

    item_detail_line_ids = fields.One2many('jewellery.item.detail.line', 'wizard_id', string="Item Detail Lines")
    stock_weight_line_ids = fields.One2many('jewellery.stock.weight.line', 'wizard_id', string="Stock Weight Lines")

    @api.onchange('branch_ids')
    def _onchange_branch_ids(self):
        """Filter locations by selected branches if any."""
        if self.branch_ids:
            return {'domain': {'location_ids': [('usage', '=', 'internal'), ('branch_id', 'in', self.branch_ids.ids)]}}
        return {'domain': {'location_ids': [('usage', '=', 'internal')]}}

    def action_view_in_odoo(self):
        self.ensure_one()

        self.item_detail_line_ids.unlink()
        self.stock_weight_line_ids.unlink()

        products = self.product_ids
        if not products:
            po_domain = [('state', 'in', ['purchase', 'done'])]
            so_domain = [('state', 'in', ['sale', 'done'])]
            if self.date_to:
                end_datetime = fields.Datetime.to_string(datetime.combine(self.date_to, datetime.max.time()))
                po_domain.append(('order_id.date_order', '<=', end_datetime))
                so_domain.append(('order_id.date_order', '<=', end_datetime))
                
            po_products = self.env['purchase.order.line'].read_group(
                po_domain, ['product_id'], ['product_id']
            )
            so_products = self.env['sale.order.line'].read_group(
                so_domain, ['product_id'], ['product_id']
            )
            product_ids = [p['product_id'][0] for p in po_products if p['product_id']] + \
                          [p['product_id'][0] for p in so_products if p['product_id']]
            products = self.env['product.product'].browse(list(set(product_ids)))

        vals_list = []
        for product in products:
            opening_gross = 0.0
            opening_net = 0.0
            
            if self.date_from:
                start_datetime = fields.Datetime.to_string(datetime.combine(self.date_from, datetime.min.time()))
                
                po_domain_open = [
                    ('product_id', '=', product.id),
                    ('state', 'in', ['purchase', 'done']),
                    ('order_id.date_order', '<', start_datetime)
                ]
                po_lines_open = self.env['purchase.order.line'].search(po_domain_open)
                po_gross_open = sum(po_lines_open.mapped('product_qty'))
                po_net_open = sum(po_lines_open.mapped('net_weight'))
                
                so_domain_open = [
                    ('product_id', '=', product.id),
                    ('state', 'in', ['sale', 'done']),
                    ('order_id.date_order', '<', start_datetime)
                ]
                so_lines_open = self.env['sale.order.line'].search(so_domain_open)
                so_gross_open = sum(so_lines_open.mapped('product_uom_qty'))
                so_net_open = sum(so_lines_open.mapped('net_weight'))
                
                opening_gross = po_gross_open - so_gross_open
                opening_net = po_net_open - so_net_open
                
                # Write an opening balance line record
                vals_list.append({
                    'wizard_id': self.id,
                    'product_id': product.id,
                    'date': self.date_from,
                    'ref': 'Opening Balance',
                    'inward_gross_weight': 0.0,
                    'inward_net_weight': 0.0,
                    'inward_diamond_weight': 0.0,
                    'inward_stone_weight': 0.0,
                    'outward_gross_weight': 0.0,
                    'outward_net_weight': 0.0,
                    'outward_diamond_weight': 0.0,
                    'outward_stone_weight': 0.0,
                    'outward_other_weight': 0.0,
                    'closing_gross_weight': opening_gross,
                    'closing_net_weight': opening_net,
                })
            
            # 2. Get transactions within date range
            po_domain_curr = [
                ('product_id', '=', product.id),
                ('state', 'in', ['purchase', 'done']),
            ]
            if self.date_from:
                start_datetime = fields.Datetime.to_string(datetime.combine(self.date_from, datetime.min.time()))
                po_domain_curr.append(('order_id.date_order', '>=', start_datetime))
            if self.date_to:
                end_datetime = fields.Datetime.to_string(datetime.combine(self.date_to, datetime.max.time()))
                po_domain_curr.append(('order_id.date_order', '<=', end_datetime))
                
            po_lines_curr = self.env['purchase.order.line'].search(po_domain_curr)
            
            so_domain_curr = [
                ('product_id', '=', product.id),
                ('state', 'in', ['sale', 'done']),
            ]
            if self.date_from:
                start_datetime = fields.Datetime.to_string(datetime.combine(self.date_from, datetime.min.time()))
                so_domain_curr.append(('order_id.date_order', '>=', start_datetime))
            if self.date_to:
                end_datetime = fields.Datetime.to_string(datetime.combine(self.date_to, datetime.max.time()))
                so_domain_curr.append(('order_id.date_order', '<=', end_datetime))
                
            so_lines_curr = self.env['sale.order.line'].search(so_domain_curr)
            
            transactions = []
            for pol in po_lines_curr:
                pol_date = pol.order_id.date_order.date() if pol.order_id.date_order else False
                transactions.append({
                    'type': 'purchase',
                    'date': pol_date or self.date_from or date.today(),
                    'ref': pol.order_id.partner_ref or pol.order_id.name or '',
                    'gross': pol.product_qty,
                    'net': pol.net_weight,
                    'diamond': pol.diamond_weight_gm,
                    'stone': pol.stone_weight,
                    'other': 0.0,
                })
            for sol in so_lines_curr:
                sol_date = sol.order_id.date_order.date() if sol.order_id.date_order else False
                transactions.append({
                    'type': 'sale',
                    'date': sol_date or self.date_from or date.today(),
                    'ref': sol.order_id.client_order_ref or sol.order_id.name or '',
                    'gross': sol.product_uom_qty,
                    'net': sol.net_weight,
                    'diamond': sol.sale_diamond_weight_gm,
                    'stone': sol.sale_stone_weight,
                    'other': sol.other_weight_g,
                })
            
            # Sort chronologically by date
            transactions.sort(key=lambda t: t['date'])
            
            running_gross = opening_gross
            running_net = opening_net
            
            for t in transactions:
                if t['type'] == 'purchase':
                    running_gross += t['gross']
                    running_net += t['net']
                    vals_list.append({
                        'wizard_id': self.id,
                        'product_id': product.id,
                        'date': t['date'],
                        'ref': t['ref'],
                        'inward_gross_weight': t['gross'],
                        'inward_net_weight': t['net'],
                        'inward_diamond_weight': t['diamond'],
                        'inward_stone_weight': t['stone'],
                        'outward_gross_weight': 0.0,
                        'outward_net_weight': 0.0,
                        'outward_diamond_weight': 0.0,
                        'outward_stone_weight': 0.0,
                        'outward_other_weight': 0.0,
                        'closing_gross_weight': running_gross,
                        'closing_net_weight': running_net,
                    })
                else:  # sale
                    running_gross -= t['gross']
                    running_net -= t['net']
                    vals_list.append({
                        'wizard_id': self.id,
                        'product_id': product.id,
                        'date': t['date'],
                        'ref': t['ref'],
                        'inward_gross_weight': 0.0,
                        'inward_net_weight': 0.0,
                        'inward_diamond_weight': 0.0,
                        'inward_stone_weight': 0.0,
                        'outward_gross_weight': t['gross'],
                        'outward_net_weight': t['net'],
                        'outward_diamond_weight': t['diamond'],
                        'outward_stone_weight': t['stone'],
                        'outward_other_weight': t['other'],
                        'closing_gross_weight': running_gross,
                        'closing_net_weight': running_net,
                    })

        if vals_list:
            self.env['jewellery.item.detail.line'].create(vals_list)

        action = self.env.ref('em_jewellery_reports.action_jewellery_item_detail_line').read()[0]
        action['domain'] = [('wizard_id', '=', self.id)]
        return action

    def action_export_excel(self):
        self.ensure_one()
        self.action_view_in_odoo()
        return self.env.ref('em_jewellery_reports.action_jewellery_report_xlsx').report_action(self)
