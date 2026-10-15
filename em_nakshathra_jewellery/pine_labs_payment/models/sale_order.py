# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pinelabs_transaction_ids = fields.One2many(
        'pinelabs.transaction', 'sale_order_id', string='Pine Labs Transactions'
    )
    pinelabs_payment_state = fields.Selection(
        related='pinelabs_transaction_ids.state',
        string='Pine Labs Payment Status',
        store=False,
    )

    def action_pay_via_pinelabs(self):
        """Open Pine Labs payment wizard for this Sale Order."""
        self.ensure_one()
        # Confirm the order if in draft
        if self.state == 'draft':
            self.action_confirm()

        # Ensure there is an invoice; create if not exists
        if not self.invoice_ids:
            self._create_invoices()

        invoice = self.invoice_ids.filtered(lambda inv: inv.state == 'draft')
        if not invoice:
            invoice = self.invoice_ids.filtered(lambda inv: inv.state not in ('cancel', 'posted'))

        if not invoice:
            raise UserError(_('No valid draft invoice found. Please create an invoice first.'))

        amount = invoice[0].amount_residual
        if amount <= 0:
            raise UserError(_('This order has no outstanding balance to pay.'))

        return {
            'name': _('Pay via Pine Labs'),
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_amount': amount,
                'default_sale_order_id': self.id,
                'default_invoice_id': invoice[0].id,
            },
        }
