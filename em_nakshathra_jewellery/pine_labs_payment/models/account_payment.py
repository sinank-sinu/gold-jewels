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
    is_suspense_payment = fields.Boolean(
        string='Is Suspense Payment',
        default=False,
        help="If checked, the payment will be routed through the Bank Suspense account and Outstanding Receipts.",
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
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_amount': amount,
                'default_payment_id': self.id,
            },
        }

    def _get_trigger_fields_to_synchronize(self):
        res = super()._get_trigger_fields_to_synchronize()
        return res + ('is_suspense_payment',)

    def _synchronize_from_moves(self, changed_fields):
        partner_types = {pay.id: pay.partner_type for pay in self}
        super()._synchronize_from_moves(changed_fields)
        for pay in self:
            if pay.is_suspense_payment and partner_types.get(pay.id) == 'customer' and pay.partner_type != 'customer':
                pay.with_context(skip_account_move_synchronization=True).write({'partner_type': 'customer'})

    def _seek_for_lines(self):
        lines = super()._seek_for_lines()
        liquidity_lines, counterpart_lines, writeoff_lines = lines
        
        all_main_lines = liquidity_lines | counterpart_lines
        
        # If Odoo's core logic mistakenly grouped both lines into one bucket (causing Expected Singleton crash),
        # and we have exactly 2 main lines, we surgically split them into singletons.
        if len(all_main_lines) == 2 and (len(liquidity_lines) != 1 or len(counterpart_lines) != 1):
            all_main_lines = all_main_lines.sorted(key=lambda l: l.id)
            
            # Fallback split
            actual_liquidity = all_main_lines[0]
            actual_counterpart = all_main_lines[1]
            
            # Try to assign the one that is actually a liquidity account
            valid_liquidity = self._get_valid_liquidity_accounts()
            for line in all_main_lines:
                if line.account_id in valid_liquidity:
                    actual_liquidity = line
                    actual_counterpart = all_main_lines - line
                    break
                    
            return (actual_liquidity, actual_counterpart, writeoff_lines)
            
        return lines

    def _prepare_move_line_default_vals(self, write_off_line_vals=None, force_balance=None):
        line_vals_list = super()._prepare_move_line_default_vals(write_off_line_vals=write_off_line_vals, force_balance=force_balance)
        
        if self.is_suspense_payment:
            # Locate the Bank Suspense Account configured on the journal
            suspense_account = self.journal_id.suspense_account_id
            if not suspense_account:
                raise UserError(_("Please configure a Suspense Account on the journal %s.") % self.journal_id.name)
            
            # Dynamically fetch the best Outstanding Receipts account
            out_accs = self.journal_id._get_journal_inbound_outstanding_payment_accounts()
            outstanding_receipts_account = False
            
            if out_accs:
                outstanding_receipts_account = out_accs[0]
            elif self.company_id.account_journal_payment_debit_account_id:
                outstanding_receipts_account = self.company_id.account_journal_payment_debit_account_id
            else:
                # Fallback to searching other bank journals
                bank_journal = self.env['account.journal'].search([('type', 'in', ['bank', 'cash']), ('company_id', '=', self.company_id.id)], limit=1)
                other_out_accs = bank_journal._get_journal_inbound_outstanding_payment_accounts()
                if other_out_accs:
                    outstanding_receipts_account = other_out_accs[0]

            if not outstanding_receipts_account:
                raise UserError(_("Could not dynamically find an Outstanding Receipts account for your company. Please configure it in your Accounting settings."))
            
            if outstanding_receipts_account.id == suspense_account.id:
                raise UserError(_("CRITICAL CONFIGURATION ERROR: The Outstanding Receipts account and the Suspense account cannot be the exact same account (%s)! Please fix your Journal and Company settings.") % suspense_account.name)

            # In Odoo, line_vals_list[0] is ALWAYS the Liquidity line (Debit for inbound)
            # and line_vals_list[1] is ALWAYS the Counterpart line (Credit for inbound).
            # We strictly overwrite them to bypass any bad user-configured partner mappings.
            line_vals_list[0]['account_id'] = suspense_account.id
            line_vals_list[1]['account_id'] = outstanding_receipts_account.id
        
        return line_vals_list
