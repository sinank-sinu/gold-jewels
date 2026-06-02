# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    pinelabs_transaction_id = fields.Many2one(
        'pinelabs.transaction',
        string='Pine Labs Transaction',
        copy=False,
    )
    pinelabs_txn_ref = fields.Char(
        related='pinelabs_transaction_id.pinelabs_transaction_id',
        string='Pine Labs Txn Ref',
        readonly=True,
    )
    pinelabs_approval_code = fields.Char(
        related='pinelabs_transaction_id.approval_code',
        string='Approval Code',
        readonly=True,
    )

    def action_pay_via_pinelabs(self):
        """Open the Pine Labs payment wizard from Register Payment."""
        self.ensure_one()
        amount = self.amount
        if amount <= 0:
            raise UserError(_('Payment amount must be greater than zero.'))
        return {
            'name': _('Pay via Pine Labs'),
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_amount': amount,
                'default_payment_id': self.id,
            },
        }
