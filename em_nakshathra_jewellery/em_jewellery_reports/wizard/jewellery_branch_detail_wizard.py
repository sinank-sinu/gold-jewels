from odoo import models, fields, api, _
from datetime import datetime
from odoo.exceptions import UserError


class JewelleryBranchDetailWizard(models.TransientModel):
    _name = 'jewellery.branch.detail.wizard'
    _description = 'Jewellery Branch Detail Wizard'

    branch_ids = fields.Many2many('res.branch', string="Branches")
    date_from = fields.Datetime(string="From Date/Time")
    date_to = fields.Datetime(string="To Date/Time")
    line_ids = fields.One2many('jewellery.branch.detail.line', 'wizard_id', string="Branch Detail Lines")

    def action_view_in_odoo(self):
        self.ensure_one()
        self.line_ids.unlink()

        domain = [
            ('state', '=', 'done'),
            ('label_id', '!=', False)
        ]
        
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
        if self.date_to:
            domain.append(('date', '<=', self.date_to))

        moves = self.env['stock.move'].with_context(active_test=False).search(domain)

        selected_branches = self.branch_ids
        groups = {}

        for move in moves:
            move_date = move.picking_id.date_done or move.date or fields.Datetime.now()
            product = move.product_id
            label = move.label_id
            source_loc = move.location_id
            dest_loc = move.location_dest_id
            
            source_usage = source_loc.usage
            dest_usage = dest_loc.usage

            if source_usage == 'internal' and dest_usage == 'internal':
                transfer_type = 'internal'
            elif source_usage != 'internal' and dest_usage == 'internal':
                continue
            elif source_usage == 'internal' and dest_usage != 'internal':
                transfer_type = 'so'
            else:
                continue

            purchase_ref = ''
            if move.purchase_line_id:
                purchase_ref = move.purchase_line_id.order_id.name or ''
                if move.purchase_line_id.order_id.partner_ref:
                    purchase_ref = f"{purchase_ref} ({move.purchase_line_id.order_id.partner_ref})"
            elif hasattr(move.picking_id, 'purchase_id') and move.picking_id.purchase_id:
                purchase_ref = move.picking_id.purchase_id.name or ''
                if move.picking_id.purchase_id.partner_ref:
                    purchase_ref = f"{purchase_ref} ({move.picking_id.purchase_id.partner_ref})"
            elif move.picking_id.origin and 'PO' in move.picking_id.origin:
                purchase_ref = move.picking_id.origin
            elif move.origin and 'PO' in move.origin:
                purchase_ref = move.origin

            sale_ref = ''
            if move.sale_line_id:
                sale_ref = move.sale_line_id.order_id.name or ''
                if move.sale_line_id.order_id.client_order_ref:
                    sale_ref = f"{sale_ref} ({move.sale_line_id.order_id.client_order_ref})"
            elif hasattr(move.picking_id, 'sale_id') and move.picking_id.sale_id:
                sale_ref = move.picking_id.sale_id.name or ''
                if move.picking_id.sale_id.client_order_ref:
                    sale_ref = f"{sale_ref} ({move.picking_id.sale_id.client_order_ref})"
            elif move.picking_id.origin and ('SO' in move.picking_id.origin or 'Shop' in move.picking_id.origin):
                sale_ref = move.picking_id.origin
            elif move.origin and ('SO' in move.origin or 'Shop' in move.origin):
                sale_ref = move.origin
                
            internal_ref = move.picking_id.name or move.reference or ''

            if transfer_type == 'po':
                dest_branch = dest_loc.branch_id
                if dest_branch and (not selected_branches or dest_branch in selected_branches):
                    key = (dest_branch.id, product.id, move_date, source_loc.id, dest_loc.id, 'po', purchase_ref, sale_ref)
                    if key not in groups:
                        groups[key] = {
                            'labels': set(),
                            'inward_gross': 0.0,
                            'inward_net': 0.0,
                            'inward_stone': 0.0,
                            'inward_diamond': 0.0,
                            'outward_gross': 0.0,
                            'outward_net': 0.0,
                            'outward_stone': 0.0,
                            'outward_diamond': 0.0,
                            'outward_other': 0.0,
                        }
                    groups[key]['labels'].add(label.id)
                    if move.purchase_line_id:
                        groups[key]['inward_gross'] += move.purchase_line_id.product_qty or 0.0
                        groups[key]['inward_net'] += move.purchase_line_id.net_weight or 0.0
                        groups[key]['inward_stone'] += move.purchase_line_id.stone_weight or 0.0
                        groups[key]['inward_diamond'] += move.purchase_line_id.diamond_weight_gm or 0.0
                    else:
                        groups[key]['inward_gross'] += label.purchase_gross_weight or 0.0
                        groups[key]['inward_net'] += label.purchase_net_weight or 0.0
                        groups[key]['inward_stone'] += label.purchase_stone_weight or 0.0
                        groups[key]['inward_diamond'] += label.purchase_diamond_weight_gm or 0.0

            elif transfer_type == 'so':
                source_branch = source_loc.branch_id
                if source_branch and (not selected_branches or source_branch in selected_branches):
                    key = (source_branch.id, product.id, move_date, source_loc.id, dest_loc.id, 'so', purchase_ref, sale_ref)
                    if key not in groups:
                        groups[key] = {
                            'labels': set(),
                            'inward_gross': 0.0,
                            'inward_net': 0.0,
                            'inward_stone': 0.0,
                            'inward_diamond': 0.0,
                            'outward_gross': 0.0,
                            'outward_net': 0.0,
                            'outward_stone': 0.0,
                            'outward_diamond': 0.0,
                            'outward_other': 0.0,
                        }
                    groups[key]['labels'].add(label.id)
                    if move.sale_line_id:
                        groups[key]['outward_gross'] += move.sale_line_id.product_uom_qty or 0.0
                        groups[key]['outward_net'] += move.sale_line_id.net_weight or 0.0
                        groups[key]['outward_stone'] += move.sale_line_id.sale_stone_weight or 0.0
                        groups[key]['outward_diamond'] += move.sale_line_id.sale_diamond_weight_gm or 0.0
                        groups[key]['outward_other'] += move.sale_line_id.other_weight_g or 0.0
                    else:
                        groups[key]['outward_gross'] += label.purchase_gross_weight or 0.0
                        groups[key]['outward_net'] += label.purchase_net_weight or 0.0
                        groups[key]['outward_stone'] += label.purchase_stone_weight or 0.0
                        groups[key]['outward_diamond'] += label.purchase_diamond_weight_gm or 0.0
                        groups[key]['outward_other'] += label.other_weight_g or 0.0

            else:
                dest_branch = dest_loc.branch_id
                if dest_branch and (not selected_branches or dest_branch in selected_branches):
                    key = (dest_branch.id, product.id, move_date, source_loc.id, dest_loc.id, 'internal', internal_ref, '')
                    if key not in groups:
                        groups[key] = {
                            'labels': set(),
                            'inward_gross': 0.0,
                            'inward_net': 0.0,
                            'inward_stone': 0.0,
                            'inward_diamond': 0.0,
                            'outward_gross': 0.0,
                            'outward_net': 0.0,
                            'outward_stone': 0.0,
                            'outward_diamond': 0.0,
                            'outward_other': 0.0,
                        }
                    groups[key]['labels'].add(label.id)
                    if move.purchase_line_id:
                        groups[key]['inward_gross'] += move.purchase_line_id.product_qty or 0.0
                        groups[key]['inward_net'] += move.purchase_line_id.net_weight or 0.0
                        groups[key]['inward_stone'] += move.purchase_line_id.stone_weight or 0.0
                        groups[key]['inward_diamond'] += move.purchase_line_id.diamond_weight_gm or 0.0
                    else:
                        groups[key]['inward_gross'] += label.purchase_gross_weight or 0.0
                        groups[key]['inward_net'] += label.purchase_net_weight or 0.0
                        groups[key]['inward_stone'] += label.purchase_stone_weight or 0.0
                        groups[key]['inward_diamond'] += label.purchase_diamond_weight_gm or 0.0

                source_branch = source_loc.branch_id
                if source_branch and (not selected_branches or source_branch in selected_branches):
                    key = (source_branch.id, product.id, move_date, source_loc.id, dest_loc.id, 'internal', internal_ref, '')
                    if key not in groups:
                        groups[key] = {
                            'labels': set(),
                            'inward_gross': 0.0,
                            'inward_net': 0.0,
                            'inward_stone': 0.0,
                            'inward_diamond': 0.0,
                            'outward_gross': 0.0,
                            'outward_net': 0.0,
                            'outward_stone': 0.0,
                            'outward_diamond': 0.0,
                            'outward_other': 0.0,
                        }
                    groups[key]['labels'].add(label.id)
                    if move.sale_line_id:
                        groups[key]['outward_gross'] += move.sale_line_id.product_uom_qty or 0.0
                        groups[key]['outward_net'] += move.sale_line_id.net_weight or 0.0
                        groups[key]['outward_stone'] += move.sale_line_id.sale_stone_weight or 0.0
                        groups[key]['outward_diamond'] += move.sale_line_id.sale_diamond_weight_gm or 0.0
                        groups[key]['outward_other'] += move.sale_line_id.other_weight_g or 0.0
                    else:
                        groups[key]['outward_gross'] += label.purchase_gross_weight or 0.0
                        groups[key]['outward_net'] += label.purchase_net_weight or 0.0
                        groups[key]['outward_stone'] += label.purchase_stone_weight or 0.0
                        groups[key]['outward_diamond'] += label.purchase_diamond_weight_gm or 0.0
                        groups[key]['outward_other'] += label.other_weight_g or 0.0

        vals_list = []
        for key, data in groups.items():
            branch_id, product_id, move_date, source_loc_id, dest_loc_id, transfer_type, p_ref, s_ref = key
            vals_list.append({
                'wizard_id': self.id,
                'branch_id': branch_id,
                'product_id': product_id,
                'date': move_date,
                'transfer_type': transfer_type,
                'particulars': p_ref if transfer_type == 'internal' else s_ref,
                'location_id': source_loc_id,
                'location_dest_id': dest_loc_id,
                'label_ids': [(6, 0, list(data['labels']))],
                'label_count': len(data['labels']),
                'inward_gross_weight': data['inward_gross'],
                'inward_net_weight': data['inward_net'],
                'inward_stone_weight': data['inward_stone'],
                'inward_diamond_weight': data['inward_diamond'],
                'outward_gross_weight': data['outward_gross'],
                'outward_net_weight': data['outward_net'],
                'outward_stone_weight': data['outward_stone'],
                'outward_diamond_weight': data['outward_diamond'],
                'outward_other_weight': data['outward_other'],
            })

        branch_product_groups = {}
        for val in vals_list:
            b_prod_key = (val['branch_id'], val['product_id'])
            if b_prod_key not in branch_product_groups:
                branch_product_groups[b_prod_key] = []
            branch_product_groups[b_prod_key].append(val)

        final_vals_list = []
        for b_prod_key, items in branch_product_groups.items():
            items.sort(key=lambda x: x['date'])
            running_gross = 0.0
            running_net = 0.0
            for item in items:
                running_gross += item['inward_gross_weight'] - item['outward_gross_weight']
                running_net += item['inward_net_weight'] - item['outward_net_weight']
                item['closing_gross_weight'] = running_gross
                item['closing_net_weight'] = running_net
                final_vals_list.append(item)

        if final_vals_list:
            self.env['jewellery.branch.detail.line'].create(final_vals_list)

        action = self.env.ref('em_jewellery_reports.action_jewellery_branch_detail_line').read()[0]
        action['domain'] = [('wizard_id', '=', self.id)]
        return action
