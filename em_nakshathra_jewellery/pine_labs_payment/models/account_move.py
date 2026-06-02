# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    pinelabs_transaction_ids = fields.One2many(
        'pinelabs.transaction', 'invoice_id', string='Pine Labs Transactions'
    )
    pinelabs_payment_state = fields.Selection(
        related='pinelabs_transaction_ids.state',
        string='Pine Labs Payment Status',
        store=False,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Generated Sale Order'
    )
    show_create_sale_order = fields.Boolean(
        compute='_compute_show_create_sale_order'
    )

    @api.depends('state','amount_residual','invoice_line_ids.product_id')
    def _compute_show_create_sale_order(self):
        bullion_product = self.env.ref(
            'em_jewellery_management.product_bullion_gold',
            raise_if_not_found=False
        )

        for move in self:
            move.show_create_sale_order = False

            if move.state != 'posted':
                continue

            if move.amount_residual <= 0:
                continue

            if not bullion_product:
                continue

            if bullion_product.id not in move.invoice_line_ids.mapped('product_id').ids:
                continue

            move.show_create_sale_order = True

    def action_create_sale_order(self):
        self.ensure_one()

        if self.sale_order_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'res_id': self.sale_order_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

        product = self.env.ref(
            'em_jewellery_management.product_bullion_gold'
        )
        original_so = self.invoice_line_ids.sale_line_ids.order_id[:1]
        purchase_order = original_so.purchase_order_id

        sale_order = self.env['sale.order'].create({
            'purchase_order_id': purchase_order.id,
            'from_invoice': True,
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'unfix': self.unfix,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'name': product.display_name,
                'product_uom_qty': 1,
                'price_unit': self.amount_residual,
            })]
        })

        self.sale_order_id = sale_order.id

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_pay_via_pinelabs(self):
        """Open Pine Labs payment wizard for this invoice/bill."""
        self.ensure_one()

        if self.state != 'posted':
            raise UserError(_('Only posted invoices/bills can be paid via Pine Labs.'))

        amount = self.amount_residual
        if amount <= 0:
            raise UserError(_('This invoice has no outstanding balance to pay.'))

        return {
            'name': _('Pay via Pine Labs'),
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_amount': amount,
                'default_invoice_id': self.id,
            },
        }
