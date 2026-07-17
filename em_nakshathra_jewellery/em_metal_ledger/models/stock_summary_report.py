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
        self.env['stock.summary.report.line'].sudo().search([('create_uid', '=', self.env.user.id)]).unlink()

        internal_loc_domain = [('usage', '=', 'internal')]
        if self.branch_ids:
            internal_loc_domain.append(('branch_id', 'in', self.branch_ids.ids))
        internal_locations = self.env['stock.location'].sudo().search(internal_loc_domain)
        internal_loc_ids = internal_locations.ids

        no_of_days = (self.end_date - self.start_date).days + 1

        start_datetime = datetime.combine(self.start_date, datetime.min.time())
        end_datetime = datetime.combine(self.end_date, datetime.max.time())

        label_domain_in = [
            ('create_date', '>=', start_datetime),
            ('create_date', '<=', end_datetime)
        ]
        if self.branch_ids:
            label_domain_in.append(('branch_id', 'in', self.branch_ids.ids))
        labels_created_in_period = self.env['product.label'].sudo().with_context(active_test=False).search(label_domain_in)

        label_domain_active_before = [
            ('create_date', '<', start_datetime),
            ('active', '=', True)
        ]
        if self.branch_ids:
            label_domain_active_before.append(('branch_id', 'in', self.branch_ids.ids))
        labels_active_before = self.env['product.label'].sudo().with_context(active_test=False).search(label_domain_active_before)

        moves_domain_period = [
            ('state', '=', 'done'),
            ('date', '>=', start_datetime),
            ('date', '<=', end_datetime),
            ('label_id', '!=', False)
        ]
        if self.branch_ids:
            moves_domain_period.append(('label_id.branch_id', 'in', self.branch_ids.ids))
        moves_in_period = self.env['stock.move'].sudo().search(moves_domain_period)
        moved_label_ids = moves_in_period.mapped('label_id.id')
        labels_moved_in_period = self.env['product.label'].sudo().with_context(active_test=False).browse(moved_label_ids)

        sale_domain_period = [
            ('state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', start_datetime),
            ('order_id.date_order', '<=', end_datetime),
            ('label_id', '!=', False)
        ]
        if self.branch_ids:
            sale_domain_period.append(('order_id.branch_id', 'in', self.branch_ids.ids))
        sale_lines_in_period = self.env['sale.order.line'].sudo().search(sale_domain_period)
        sold_label_ids = sale_lines_in_period.mapped('label_id.id')
        labels_sold_in_period = self.env['product.label'].sudo().with_context(active_test=False).browse(sold_label_ids)

        active_labels = labels_created_in_period | labels_active_before | labels_moved_in_period | labels_sold_in_period
        relevant_product_ids = set(active_labels.mapped('product_id.id')) - {False}

        active_labels_in_period = labels_created_in_period

        moves_domain = [
            ('state', '=', 'done'),
            ('product_id', 'in', list(relevant_product_ids)),
            ('label_id', 'in', active_labels.ids),
            ('date', '<=', datetime.combine(self.end_date, datetime.max.time())),
            '|',
            ('location_id', 'in', internal_loc_ids),
            ('location_dest_id', 'in', internal_loc_ids)
        ]
        all_moves = self.env['stock.move'].sudo().search(moves_domain)
        
        moves_by_product = {}
        for move in all_moves:
            moves_by_product.setdefault(move.product_id.id, []).append(move)

        rules_domain = [
            ('location_id', 'in', internal_loc_ids),
            ('product_id', 'in', list(relevant_product_ids))
        ]
        all_rules = self.env['stock.warehouse.orderpoint'].sudo().search(rules_domain)
        
        rules_by_product = {}
        for rule in all_rules:
            rules_by_product.setdefault(rule.product_id.id, []).append(rule)

        products = self.env['product.product'].sudo().browse(list(relevant_product_ids)).filtered(lambda p: p.active)

        report_lines = []

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
                    purity_percent = move.purity_id.percentage if move.purity_id else move.product_id.purity_id.percentage
                    if purity_percent:
                        m_net = m_gross * (purity_percent / 100.0)
                    else:
                        m_net = m_gross

                pcs += m_pcs * coef
                gross += m_gross * coef
                net += m_net * coef
            
            return pcs, gross, net

        for product in products:
            product_moves = moves_by_product.get(product.id, [])
            
            product_labels = active_labels.filtered(lambda l: l.product_id.id == product.id)
            
            has_no_label_moves = any(not m.label_id for m in product_moves)
            
            labels_to_process = list(product_labels)
            if has_no_label_moves or not labels_to_process:
                labels_to_process.append(False)

            for label in labels_to_process:
                if label:
                    label_moves = [m for m in product_moves if m.label_id.id == label.id]
                else:
                    label_moves = [m for m in product_moves if not m.label_id]

                opening_moves = []
                period_moves = []
                for move in label_moves:
                    if move.date.date() < self.start_date:
                        opening_moves.append(move)
                    else:
                        period_moves.append(move)

                # Calculate Opening
                if label:
                    is_created_before_period = label.create_date and label.create_date.date() < self.start_date
                    if is_created_before_period:
                        sold_before_so_domain = [
                            ('state', 'in', ('sale', 'done')),
                            ('label_id', '=', label.id),
                            ('order_id.date_order', '<', start_datetime)
                        ]
                        was_sold_before_start = any(
                            m.location_id.id in internal_loc_ids and m.location_dest_id.id not in internal_loc_ids
                            for m in opening_moves
                        ) or bool(self.env['sale.order.line'].sudo().search(sold_before_so_domain, limit=1))
                        
                        if not was_sold_before_start:
                            o_pcs = 1.0
                            o_gross = label.purchase_gross_weight
                            o_net = label.purchase_net_weight
                        else:
                            o_pcs = 0.0
                            o_gross = 0.0
                            o_net = 0.0
                    else:
                        o_pcs = 0.0
                        o_gross = 0.0
                        o_net = 0.0
                else:
                    o_pcs, o_gross, o_net = get_stats(opening_moves, internal_loc_ids, mode='opening')

                if label:
                    is_created_in_period = label.create_date and start_datetime <= label.create_date <= end_datetime
                    if is_created_in_period:
                        in_pcs = 1.0
                        in_gross = label.purchase_gross_weight
                        in_net = label.purchase_net_weight
                    else:
                        in_pcs = 0.0
                        in_gross = 0.0
                        in_net = 0.0
                else:
                    in_pcs = 0.0
                    in_gross = 0.0
                    in_net = 0.0
                
                if label:
                    sale_domain = [
                        ('state', 'in', ('sale', 'done')),
                        ('label_id', '=', label.id),
                        ('order_id.date_order', '>=', start_datetime),
                        ('order_id.date_order', '<=', end_datetime)
                    ]
                    if self.branch_ids:
                        sale_domain.append(('order_id.branch_id', 'in', self.branch_ids.ids))
                    sale_line = self.env['sale.order.line'].sudo().search(sale_domain, limit=1)
                    if sale_line:
                        out_pcs = 1.0
                        out_gross = label.purchase_gross_weight
                        out_net = label.purchase_net_weight
                    else:
                        out_pcs, out_gross, out_net = get_stats(period_moves, internal_loc_ids, mode='out')
                else:
                    out_pcs, out_gross, out_net = get_stats(period_moves, internal_loc_ids, mode='out')

                c_pcs = o_pcs + in_pcs - out_pcs
                c_gross = o_gross + in_gross - out_gross
                c_net = o_net + in_net - out_net

                avg_inventory = (o_gross + c_gross) / 2.0
                if avg_inventory <= 0.0 and (in_gross > 0.0 or out_gross > 0.0):
                    avg_inventory = (in_gross + out_gross) / 4.0
                turnover_ratio = (out_gross / avg_inventory) if avg_inventory > 0.0001 else 0.0
                dio = round(no_of_days / turnover_ratio) if turnover_ratio > 0.0001 else (no_of_days if avg_inventory > 0.0001 else 0.0)
                
                # Minimum stock level from reordering rules
                product_rules = rules_by_product.get(product.id, [])
                min_stock = product_rules[0].product_min_qty if product_rules else 0.0
                stock_gap = c_gross - min_stock

                purity_id = label.purity_id.id if label and label.purity_id else (product.purity_id.id if hasattr(product, 'purity_id') and product.purity_id else False)
                ageing = label.age if label else 0

                attribute_map = {}
                for ptav in product.product_template_attribute_value_ids:
                    attribute_map[
                        ptav.attribute_id.name.strip().lower()
                    ] = ptav.product_attribute_value_id.name

                for line in product.product_tmpl_id.attribute_line_ids:
                    if line.value_ids:
                        attr_name = line.attribute_id.name.strip().lower()
                        if attr_name not in attribute_map:
                            attribute_map[attr_name] = line.value_ids[0].name

                type_value = attribute_map.get('type', attribute_map.get('item type', attribute_map.get('product type', '')))
                variety_value = attribute_map.get('variety', attribute_map.get('verity', ''))
                design_value = attribute_map.get('design', '')
                size_value = attribute_map.get('size', '')
                stone_colour_value = attribute_map.get('stone colour', attribute_map.get('stone color', ''))
                metal_colour_value = attribute_map.get('metal colour', attribute_map.get('metal color', ''))

                # Only add to report if there is any activity or stock, and the product has an active label
                if any([o_pcs, o_gross, o_net, in_pcs, in_gross, in_net, out_pcs, out_gross, out_net, c_pcs, c_gross, c_net, min_stock]):
                    report_lines.append({
                        'product_id': product.id,
                        'product_template_id': product.product_tmpl_id.id,
                        'label_id': label.id if label else False,
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
                        'type_value': type_value,
                        'variety_value': variety_value,
                        'design_value': design_value,
                        'size_value': size_value,
                        'stone_colour_value': stone_colour_value,
                        'metal_colour_value': metal_colour_value,
                    })

        if report_lines:
            self.env['stock.summary.report.line'].sudo().create(report_lines)

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
