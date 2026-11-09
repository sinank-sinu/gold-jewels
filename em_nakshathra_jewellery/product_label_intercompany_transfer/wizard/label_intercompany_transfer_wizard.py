# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LabelIntercompanyTransferWizard(models.TransientModel):
    _name = 'label.intercompany.transfer.wizard'
    _description = 'Inter-Company Product Label Transfer Wizard'

    source_company_id = fields.Many2one(
        'res.company',
        string="Source Company",
        required=True,
        readonly=True,
        default=lambda self: self.env.company
    )
    dest_company_id = fields.Many2one(
        'res.company',
        string="Destination Company",
        required=True,
        domain="[('id', '!=', source_company_id)]"
    )
    dest_branch_id = fields.Many2one(
        'res.branch',
        string="Destination Branch",
        required=True,
        domain="[('company_id', '=', dest_company_id)]"
    )
    dest_location_id = fields.Many2one(
        'stock.location',
        string="Destination Branch Location",
        required=True,
        domain="[('company_id', 'in', [dest_company_id, False]), ('usage', '=', 'internal')]"
    )
    transfer_date = fields.Date(
        string="Transfer Date",
        default=fields.Date.context_today,
        required=True
    )

    label_ids = fields.Many2many(
        'product.label',
        'label_intercompany_transfer_rel',
        'wizard_id',
        'label_id',
        string="Selected Labels",
        required=True
    )

    label_count = fields.Integer(
        string="Total Labels",
        compute="_compute_totals"
    )
    total_gross_weight = fields.Float(
        string="Total Gross Wt (g)",
        digits=(16, 3),
        compute="_compute_totals"
    )
    total_net_weight = fields.Float(
        string="Total Net Wt (g)",
        digits=(16, 3),
        compute="_compute_totals"
    )
    total_fine_weight = fields.Float(
        string="Total Fine Wt (g)",
        digits=(16, 3),
        compute="_compute_totals"
    )
    total_purchase_cost = fields.Float(
        string="Total Estimated Cost",
        digits=(16, 2),
        compute="_compute_totals"
    )

    # Transfer Results
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Transferred')],
        default='draft',
        readonly=True
    )
    result_po_id = fields.Many2one(
        'purchase.order',
        string="Created Purchase Order",
        readonly=True
    )
    result_bill_id = fields.Many2one(
        'account.move',
        string="Created Vendor Bill",
        readonly=True
    )
    transferred_label_ids = fields.Many2many(
        'product.label',
        'label_intercompany_transferred_created_rel',
        'wizard_id',
        'created_label_id',
        string="Transferred Labels (Destination)",
        readonly=True
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids')
        if not active_ids and self.env.context.get('active_id'):
            active_ids = [self.env.context.get('active_id')]
        active_model = self.env.context.get('active_model')
        if (not active_model or active_model == 'product.label') and active_ids:
            labels = self.env['product.label'].browse(active_ids)
            res['label_ids'] = [(6, 0, labels.ids)]
            res['source_company_id'] = self.env.company.id
        return res

    @api.depends('label_ids')
    def _compute_totals(self):
        for rec in self:
            labels = rec.label_ids
            rec.label_count = len(labels)
            rec.total_gross_weight = round(sum(labels.mapped(lambda l: l.sale_gross_weight or l.purchase_gross_weight or 0.0)), 3)
            rec.total_net_weight = round(sum(labels.mapped(lambda l: l.sale_net_weight or l.purchase_net_weight or l.sale_gross_weight or 0.0)), 3)
            rec.total_fine_weight = round(sum(labels.mapped(lambda l: l.sale_fine_weight or l.purchase_fine_weight or 0.0)), 3)
            rec.total_purchase_cost = round(sum(
                (l.sale_gross_weight or l.purchase_gross_weight or 1.0) * (l.purchase_price_per_gram or l.purchase_metal_rate or l.sale_price_per_gram or 0.0)
                for l in labels
            ), 2)

    @api.onchange('dest_company_id')
    def _onchange_dest_company_id(self):
        self.dest_branch_id = False
        self.dest_location_id = False
        if self.dest_company_id:
            # Pick first branch of destination company with branch_code
            branch = self.env['res.branch'].search([
                ('company_id', '=', self.dest_company_id.id),
                ('branch_code', '!=', False)
            ], limit=1)
            if branch:
                self.dest_branch_id = branch.id
                self._onchange_dest_branch_id()

    @api.onchange('dest_branch_id')
    def _onchange_dest_branch_id(self):
        if self.dest_branch_id and self.dest_company_id:
            # Find warehouse and location
            warehouse = self.env['stock.warehouse'].search([
                ('branch_id', '=', self.dest_branch_id.id),
                ('company_id', '=', self.dest_company_id.id)
            ], limit=1)
            if warehouse and warehouse.lot_stock_id:
                self.dest_location_id = warehouse.lot_stock_id.id
            else:
                loc = self.env['stock.location'].search([
                    ('company_id', 'in', [self.dest_company_id.id, False]),
                    ('usage', '=', 'internal')
                ], limit=1)
                if loc:
                    self.dest_location_id = loc.id

    def action_process_transfer(self):
        self.ensure_one()
        if not self.label_ids:
            raise UserError(_("No labels selected to transfer."))
        if not self.dest_company_id:
            raise UserError(_("Please select a Destination Company."))
        if not self.dest_branch_id:
            raise UserError(_("Please select a Destination Branch."))
        if not self.dest_location_id:
            raise UserError(_("Please select a Destination Location."))
        if self.dest_company_id == self.source_company_id:
            raise UserError(_("Destination Company cannot be the same as Source Company."))

        # 1. Verification of selected labels
        invalid_company_labels = self.label_ids.filtered(lambda l: l.company_id and l.company_id != self.source_company_id)
        if invalid_company_labels:
            names = ", ".join(invalid_company_labels.mapped('name'))
            raise UserError(_("Some selected labels do not belong to the current company %s: %s") % (
                self.source_company_id.name, names
            ))

        already_transferred = self.label_ids.filtered(lambda l: l.is_transferred)
        if already_transferred:
            names = ", ".join(already_transferred.mapped('name'))
            raise UserError(_("The following labels are already marked as transferred: %s") % names)

        source_company = self.source_company_id
        dest_company = self.dest_company_id
        dest_branch = self.dest_branch_id
        dest_location = self.dest_location_id
        transfer_date = self.transfer_date or fields.Date.context_today(self)

        # 2. Resolve destination warehouse for receiving goods
        dest_warehouse = self.env['stock.warehouse'].with_company(dest_company).search([
            ('branch_id', '=', dest_branch.id),
            ('company_id', '=', dest_company.id)
        ], limit=1)
        if not dest_warehouse:
            dest_warehouse = self.env['stock.warehouse'].with_company(dest_company).search([
                ('company_id', '=', dest_company.id)
            ], limit=1)
        if not dest_warehouse:
            raise UserError(_("No warehouse found for Destination Company '%s'.") % dest_company.name)

        dest_lot_stock = dest_warehouse.lot_stock_id or dest_location

        # 3. Resolve Vendor Partner for Source Company in Destination Company
        vendor_partner = source_company.partner_id
        if not vendor_partner:
            vendor_partner = self.env['res.partner'].sudo().search([
                ('name', '=', source_company.name)
            ], limit=1)
            if not vendor_partner:
                vendor_partner = self.env['res.partner'].sudo().create({
                    'name': source_company.name,
                    'supplier_rank': 1,
                    'company_id': False,
                })

        # 4. Group labels by resolved destination product and purity for PO lines
        grouped_items = {}
        for label in self.label_ids:
            dest_product = self._resolve_product_for_dest_company(label.product_id, dest_company)
            purity = label.purity_id or label.sale_purity_id
            key = (dest_product.id, purity.id if purity else False)
            if key not in grouped_items:
                grouped_items[key] = {
                    'product': dest_product,
                    'purity': purity,
                    'labels': self.env['product.label'],
                    'gross_weight': 0.0,
                    'net_weight': 0.0,
                    'costs': [],
                }
            grouped_items[key]['labels'] |= label
            gross_wt = label.sale_gross_weight or label.purchase_gross_weight or 0.0
            net_wt = label.sale_net_weight or label.purchase_net_weight or gross_wt
            grouped_items[key]['gross_weight'] += gross_wt
            grouped_items[key]['net_weight'] += net_wt
            price = label.purchase_price_per_gram or label.purchase_metal_rate or label.sale_price_per_gram or 0.0
            grouped_items[key]['costs'].append(price)

        # 5. Create Purchase Order in Destination Company
        po_line_vals_list = []
        for key, data in grouped_items.items():
            dest_prod = data['product']
            purity = data['purity']
            gross_wt = round(data['gross_weight'], 3)
            count = len(data['labels'])
            avg_cost = sum(data['costs']) / len(data['costs']) if data['costs'] else 0.0

            line_vals = {
                'product_id': dest_prod.id,
                'name': dest_prod.display_name,
                'product_qty': gross_wt,
                'gross_weight': gross_wt,
                'product_uom': dest_prod.uom_id.id,
                'price_unit': avg_cost,
                'date_planned': transfer_date,
                'taxes_id': [(5, 0, 0)],
            }
            if purity:
                line_vals['purity_id'] = purity.id
            po_line_vals_list.append((0, 0, line_vals))

        po_vals = {
            'partner_id': vendor_partner.id,
            'company_id': dest_company.id,
            'branch_id': dest_branch.id,
            'date_order': transfer_date,
            'partner_ref': f"Transfer from {source_company.name} ({transfer_date})",
            'order_line': po_line_vals_list,
        }
        po = self.env['purchase.order'].sudo().with_company(dest_company).create(po_vals)

        # 6. Confirm Purchase Order
        po.with_company(dest_company).button_confirm()
        po.write({'date_approve': transfer_date, 'date_planned': transfer_date})

        # 7. Validate Receipt Picking in Destination Company
        for picking in po.picking_ids.filtered(lambda p: p.state not in ['done', 'cancel']):
            picking.location_dest_id = dest_lot_stock.id
            for move in picking.move_ids:
                move.location_dest_id = dest_lot_stock.id
                move.quantity = move.product_uom_qty
                for ml in move.move_line_ids:
                    ml.location_dest_id = dest_lot_stock.id
                    ml.quantity = ml.quantity_product_uom or move.product_uom_qty
            picking.scheduled_date = transfer_date
            picking.button_validate()
            picking.write({'date_done': transfer_date})

        # 8. Create & Post Vendor Bill in Destination Company
        bill = False
        try:
            po.with_company(dest_company).action_create_invoice()
            bill = po.invoice_ids.filtered(lambda m: m.state == 'draft')[:1]
            if bill:
                bill.write({
                    'invoice_date': transfer_date,
                    'date': transfer_date,
                    'is_approved': True,
                })
                bill.action_post()
        except Exception as e:
            _logger.warning("Vendor bill creation note: %s. Attempting direct fallback...", e)
            if not bill:
                try:
                    inv_vals = po.with_company(dest_company)._prepare_invoice()
                    inv_vals['invoice_date'] = transfer_date
                    inv_vals['date'] = transfer_date
                    inv_vals['is_approved'] = True
                    for line in po.order_line:
                        line_vals = line._prepare_account_move_line()
                        line_vals['tax_ids'] = [(5, 0, 0)]
                        inv_vals['invoice_line_ids'].append((0, 0, line_vals))
                    bill = self.env['account.move'].sudo().with_company(dest_company).create([inv_vals])[0]
                    bill.action_post()
                except Exception as bill_err:
                    _logger.error("Could not post vendor bill: %s", bill_err)

        # 9. Relieve Stock from Source Company (Company A)
        self._relieve_source_stock(self.label_ids, source_company, dest_company, transfer_date)

        # 10. Create new Labels in Destination Company linked to PO
        new_labels = self.env['product.label']
        for label in self.label_ids:
            dest_product = self._resolve_product_for_dest_company(label.product_id, dest_company)
            gross_wt = label.sale_gross_weight or label.purchase_gross_weight or 0.0
            net_wt = label.sale_net_weight or label.purchase_net_weight or gross_wt

            label_vals = {
                'name': label.name,
                'company_id': dest_company.id,
                'branch_id': dest_branch.id,
                'product_id': dest_product.id,
                'product_template_id': dest_product.product_tmpl_id.id,
                'purchase_id': po.id,
                'source_location_id': dest_lot_stock.id,
                'branch_location_id': dest_location.id,

                # Exact barcode retention
                'barcode': label.barcode,
                'barcode2': label.barcode2,

                # Weights
                'tag_weight': label.tag_weight,
                'sale_gross_weight': gross_wt,
                'purchase_gross_weight': gross_wt,
                'sale_net_weight': net_wt,
                'purchase_net_weight': net_wt,

                # Purity
                'purity_id': label.purity_id.id if label.purity_id else False,
                'sale_purity_id': label.sale_purity_id.id if label.sale_purity_id else (label.purity_id.id if label.purity_id else False),

                # Stones & Diamonds
                'sale_stone_weight': label.sale_stone_weight,
                'purchase_stone_weight': label.purchase_stone_weight,
                'sale_diamond_weight': label.sale_diamond_weight,
                'purchase_diamond_weight': label.purchase_diamond_weight,
                'sale_diamond_weight_gm': label.sale_diamond_weight_gm,
                'sale_diamond_weight_ct': label.sale_diamond_weight_ct,
                'purchase_diamond_weight_gm': label.purchase_diamond_weight_gm,
                'purchase_diamond_weight_ct': label.purchase_diamond_weight_ct,

                # Pricing & Rates
                'purchase_price_per_gram': label.purchase_price_per_gram,
                'purchase_metal_rate': label.purchase_metal_rate,
                'sale_price_per_gram': label.sale_price_per_gram,
                'sale_metal_rate': label.sale_metal_rate,

                # Making charges
                'sale_making_charge_type': label.sale_making_charge_type,
                'sale_making_charge_value': label.sale_making_charge_value,
                'sale_making_charge_amount': label.sale_making_charge_amount,
                'purchase_making_charge_type': label.purchase_making_charge_type,
                'purchase_making_charge_value': label.purchase_making_charge_value,
                'purchase_making_charge_amount': label.purchase_making_charge_amount,

                'diamond_certificate_filename': label.diamond_certificate_filename,
            }

            new_label = self.env['product.label'].sudo().with_company(dest_company).create(label_vals)
            
            # Ensure exact name and barcode are preserved even if core create() auto-generated sequences
            if label.name:
                new_label.sudo().write({'name': label.name})
            if label.barcode:
                new_label.sudo().write({'barcode': label.barcode})
            if label.barcode2:
                new_label.sudo().write({'barcode2': label.barcode2})

            new_labels |= new_label

            # Trigger Stock In
            if new_label.source_location_id and new_label.branch_location_id and new_label.source_location_id != new_label.branch_location_id:
                try:
                    new_label.with_company(dest_company).action_stock_in()
                except Exception as stock_err:
                    _logger.warning("action_stock_in bypassed on label %s: %s", new_label.id, stock_err)
                    new_label.write({'is_stocked_in': True, 'active': True})
            else:
                new_label.write({'is_stocked_in': True, 'active': True})

            # Archive and mark source label in Company A
            label.write({
                'active': False,
                'is_transferred': True,
                'transfer_dest_company_id': dest_company.id,
                'transfer_dest_label_id': new_label.id,
                'transfer_date': transfer_date,
                'transfer_notes': f"Transferred to {dest_company.name} ({dest_branch.name}) on {transfer_date}. New Label ID: {new_label.id}, PO: {po.name}",
            })
            label.message_post(body=f"Transferred to {dest_company.name} ({dest_branch.name}) on {transfer_date}. PO: {po.name}, New Label ID: {new_label.id}")

        # 11. Recompute PO unlabelled weights
        po.sudo()._compute_total_labelled()
        po.sudo()._compute_unlabelled_totals()

        # 12. Save wizard results
        self.write({
            'result_po_id': po.id,
            'result_bill_id': bill.id if bill else False,
            'transferred_label_ids': [(6, 0, new_labels.ids)],
            'state': 'done',
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer Completed'),
            'res_model': 'label.intercompany.transfer.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _relieve_source_stock(self, labels, source_company, dest_company, transfer_date):
        """Relieve physical on-hand stock from the source company."""
        transit_loc = self.env['stock.location'].search([
            ('company_id', 'in', [source_company.id, False]),
            ('usage', 'in', ['transit', 'customer'])
        ], limit=1)
        if not transit_loc:
            transit_loc = self.env.ref('stock.stock_location_customers', raise_if_not_found=False)

        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing'),
            ('company_id', '=', source_company.id)
        ], limit=1)
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('company_id', '=', source_company.id)
            ], limit=1)

        if not picking_type or not transit_loc:
            _logger.warning("Could not find transit location or picking type for source stock relief.")
            return

        moves_data = {}
        for l in labels:
            src_loc = l.branch_location_id or l.source_location_id or picking_type.default_location_src_id
            if not src_loc:
                continue
            key = (src_loc.id, l.product_id.id)
            if key not in moves_data:
                moves_data[key] = {
                    'src_loc_id': src_loc.id,
                    'product_id': l.product_id.id,
                    'qty': 0.0,
                    'weight': 0.0,
                }
            moves_data[key]['qty'] += 1.0
            moves_data[key]['weight'] += (l.sale_gross_weight or l.purchase_gross_weight or 1.0)

        if not moves_data:
            return

        first_src_loc_id = list(moves_data.values())[0]['src_loc_id']
        try:
            picking = self.env['stock.picking'].sudo().with_company(source_company).create({
                'picking_type_id': picking_type.id,
                'location_id': first_src_loc_id,
                'location_dest_id': transit_loc.id,
                'origin': f"Inter-Company Transfer to {dest_company.name}",
                'company_id': source_company.id,
                'scheduled_date': transfer_date,
            })

            for item in moves_data.values():
                prod = self.env['product.product'].browse(item['product_id'])
                move = self.env['stock.move'].sudo().with_company(source_company).create({
                    'name': f"Transfer to {dest_company.name}",
                    'product_id': prod.id,
                    'product_uom_qty': item['weight'] if prod.uom_id.name in ['g', 'Gram', 'Grams'] else item['qty'],
                    'product_uom': prod.uom_id.id,
                    'location_id': item['src_loc_id'],
                    'location_dest_id': transit_loc.id,
                    'picking_id': picking.id,
                    'company_id': source_company.id,
                })
                move.quantity = move.product_uom_qty

            picking.button_validate()
            picking.write({'date_done': transfer_date})
        except Exception as e:
            _logger.warning("Stock relief picking note: %s", e)

    def _resolve_product_for_dest_company(self, source_product, dest_company):
        """Map source product variant to the corresponding variant in the destination company."""
        if not source_product.company_id or source_product.company_id == dest_company:
            return source_product

        source_tmpl = source_product.product_tmpl_id
        tmpl_name = source_tmpl.name

        # Search matching template in destination company
        dest_tmpl = self.env['product.template'].sudo().with_company(dest_company).search([
            ('name', '=', tmpl_name),
            ('company_id', 'in', [dest_company.id, False])
        ], limit=1)

        if not dest_tmpl:
            dest_tmpl = self.env['product.template'].sudo().with_company(dest_company).search([
                ('name', '=ilike', tmpl_name.strip()),
                ('company_id', 'in', [dest_company.id, False])
            ], limit=1)

        if not dest_tmpl:
            raise UserError(_("Product Template '%s' does not exist in destination company '%s'.") % (
                tmpl_name, dest_company.name
            ))

        if len(dest_tmpl.product_variant_ids) == 1:
            return dest_tmpl.product_variant_ids[0]

        # Match by attribute values
        source_attr_vals = source_product.product_template_attribute_value_ids.mapped('product_attribute_value_id')
        for var in dest_tmpl.product_variant_ids:
            var_attr_vals = var.product_template_attribute_value_ids.mapped('product_attribute_value_id')
            if set(var_attr_vals.ids) == set(source_attr_vals.ids):
                return var

        return dest_tmpl.product_variant_ids[0]

    def action_view_created_labels(self):
        self.ensure_one()
        return {
            'name': _('Transferred Product Labels (%s)') % self.dest_company_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.transferred_label_ids.ids)],
            'context': {'active_test': False},
        }

    def action_view_created_po(self):
        self.ensure_one()
        if not self.result_po_id:
            return
        return {
            'name': _('Purchase Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': self.result_po_id.id,
            'view_mode': 'form',
        }
