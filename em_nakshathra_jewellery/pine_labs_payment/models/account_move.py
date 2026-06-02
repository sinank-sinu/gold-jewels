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
