# -*- coding: utf-8 -*-
import time

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Maps wizard payment_method_type to Pine Labs AllowedPaymentMode codes
PINE_LABS_MODE_MAP = {
    'card': '1',
    'upi': '3',
}


class PineLabsPaymentWizard(models.TransientModel):
    _name = 'pinelabs.payment.wizard'
    _description = 'Pine Labs Payment Wizard'

    amount = fields.Float(string='Amount to Pay', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: self.env.company.currency_id)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order')
    invoice_id = fields.Many2one('account.move', string='Invoice')
    payment_id = fields.Many2one('account.payment', string='Vendor Payment')

    # Branch terminal selection
    terminal_id = fields.Many2one(
        'pinelabs.terminal',
        string='Terminal',
        domain="[('active', '=', True)]",
        help='Select the Pine Labs terminal for this payment. Filtered by branch automatically.',
    )

    # Payment mode: card / upi → Pine Labs | bank → Odoo Register Payment
    payment_method_type = fields.Selection([
        ('card', 'Card (Credit / Debit)'),
        ('upi', 'UPI'),
        ('bank', 'Bank Transfer (Register Payment)'),
        ('cash', 'Cash Payment'),
    ], string='Payment Mode', required=True, default='card')

    state = fields.Selection([
        ('draft', 'Ready'),
        ('waiting', 'Waiting for Terminal...'),
        ('success', 'Payment Successful'),
        ('failed', 'Payment Failed'),
    ], default='draft')

    # Result fields populated after successful Pine Labs payment
    pinelabs_transaction_ref = fields.Char(string='Plutus Reference ID', readonly=True)
    approval_code = fields.Char(string='Approval Code', readonly=True)
    card_type = fields.Char(string='Card Type', readonly=True)
    payment_mode = fields.Char(string='Payment Mode Result', readonly=True)
    txn_id = fields.Many2one('pinelabs.transaction', string='Transaction Record', readonly=True)
    scheme_installment_id = fields.Many2one('jewellery.scheme.installment', string='Scheme Installment Row')

    def _get_branch_terminals(self):
        """Return pinelabs.terminal records for the current invoice/document branch."""
        branch = None
        if self.invoice_id and hasattr(self.invoice_id, 'branch_id'):
            branch = self.invoice_id.branch_id
        if not branch and self.sale_order_id and hasattr(self.sale_order_id, 'branch_id'):
            branch = self.sale_order_id.branch_id
        if not branch:
            branch = self.env.user.branch_id if hasattr(self.env.user, 'branch_id') else None
        domain = [('active', '=', True)]
        if branch:
            domain.append(('branch_id', '=', branch.id))
        return self.env['pinelabs.terminal'].search(domain, limit=2)

    # ─────────────────────────────────────────────────────────────────
    # Payment mode toggle buttons (Card / UPI / Bank)
    # ─────────────────────────────────────────────────────────────────

    def _set_mode_and_refresh(self, mode):
        """Set payment_method_type and re-open the wizard to show selection."""
        self.payment_method_type = mode
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_select_card(self):
        return self._set_mode_and_refresh('card')

    def action_select_upi(self):
        return self._set_mode_and_refresh('upi')

    def action_select_bank(self):
        return self._set_mode_and_refresh('bank')

    def action_select_cash(self):
        return self._set_mode_and_refresh('cash')

    # ─────────────────────────────────────────────────────────────────
    # Main action: routes to Bank or Pine Labs depending on mode
    # ─────────────────────────────────────────────────────────────────

    def action_initiate_payment(self):
        """Route to Bank (Odoo) or Pine Labs terminal depending on payment_method_type."""
        self.ensure_one()

        if self.payment_method_type == 'bank':
            return self._action_register_bank_payment()
        elif self.payment_method_type == 'cash':
            return self._action_register_cash_payment()
        else:
            return self._action_initiate_pinelabs_payment()

    # ─────────────────────────────────────────────────────────────────
    # Bank Transfer: Use Odoo's standard Register Payment wizard
    # ─────────────────────────────────────────────────────────────────

    def _action_register_bank_payment(self):
        """Open Odoo's standard Register Payment wizard for bank/cash."""
        self.ensure_one()
        # ─── NEW HOOK: Handle Scheme Installments for Bank Transfer directly ───
        if self.scheme_installment_id:
            rec = self.scheme_installment_id

            # Find a fallback Bank/Cash journal since terminal configurations are for Pine Labs card/upi
            payment_journal = self.env['account.journal'].search([
                ('type', '=', 'bank'),
                ('company_id', '=', self.env.company.id),
            ], limit=1)

            if not payment_journal:
                raise UserError(_("No valid Bank journal found in your Chart of Accounts."))

            # Target dynamic Debtors Account Search matching your exact accounting structure logic
            debtors_account = self.env['account.account'].search([
                ('code', '=', '100400')
            ], limit=1)

            if not debtors_account:
                raise UserError(_("Debtors account 100400 not found in Chart of Accounts."))

            liability_account = payment_journal.default_account_id
            if not liability_account:
                raise UserError(_("Please configure a default account on Journal: %s") % payment_journal.name)

            # Generate the financial transaction entry document exactly like your original custom button
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': payment_journal.id,
                'ref': _('Scheme Payment via Bank Transfer - %s') % (rec.enrollment_id.name or ''),
                'line_ids': [
                    (0, 0, {
                        'name': _('Scheme Liability - %s') % (rec.enrollment_id.name or ''),
                        'partner_id': rec.enrollment_id.partner_id.id,
                        'credit': 0.0,
                        'debit': self.amount,
                        'account_id': liability_account.id
                    }),
                    (0, 0, {
                        'name': _('Scheme Payment via Bank Transfer'),
                        'partner_id': rec.enrollment_id.partner_id.id,
                        'debit': 0.0,
                        'credit': self.amount,
                        'account_id': debtors_account.id
                    })
                ]
            })

            # Force entry validation adjustments straight down to General Ledgers
            move.action_post()

            # Pass values straight down into your installment row list columns layout fields
            rec.write({
                'journal_id': payment_journal.id,
                'move_id': move.id,
                'transaction_id': 'BANK-TRANSFER',
                'state': 'paid'
            })

            # Close the wizard popup upon success
            return {'type': 'ir.actions.act_window_close'}
        # ─── LEGACY CODO ODOO FLOW (INVOICES / SALE ORDERS) ───
        active_ids = []
        if self.invoice_id:
            active_ids = self.invoice_id.ids
        elif self.sale_order_id:
            # For SO, find the related invoice
            invoices = self.sale_order_id.invoice_ids.filtered(
                lambda inv: inv.state == 'posted' and inv.payment_state in ('not_paid', 'partial')
            )
            if invoices:
                active_ids = invoices.ids
            else:
                raise UserError(_('No posted unpaid invoice found for this Sale Order.'))
        else:
            raise UserError(_('Bank Transfer is only available for invoices or sale orders.'))

        # Create the standard payment register wizard and explicitly set the amount
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=active_ids,
        ).create({
            'is_pine_labs_payment': True,
            'pine_labs_amount': self.amount,
        })

        return {
            'name': _('Register Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move',
                'active_ids': active_ids,
                'pine_labs_wizard_amount': self.amount,
            },
        }

    # ─────────────────────────────────────────────────────────────────
    # Cash Payment: Auto-select Cash journal
    # ─────────────────────────────────────────────────────────────────

    def _action_register_cash_payment(self):
        """Open Odoo's standard Register Payment wizard for cash with journal preset."""
        self.ensure_one()

        cash_journal = self.env['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', self.env.company.id)], limit=1)
        if not cash_journal:
            raise UserError(
                _('No cash journal found. Please create a cash journal first to proceed with cash payment.'))

        active_ids = []
        if self.invoice_id:
            active_ids = self.invoice_id.ids
        elif self.sale_order_id:
            # For SO, find the related invoice
            invoices = self.sale_order_id.invoice_ids.filtered(
                lambda inv: inv.state == 'posted' and inv.payment_state in ('not_paid', 'partial')
            )
            if invoices:
                active_ids = invoices.ids
            else:
                raise UserError(_('No posted unpaid invoice found for this Sale Order.'))
        else:
            raise UserError(_('Cash Payment is only available for invoices or sale orders.'))

        # Create the standard payment register wizard and explicitly set the amount
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=active_ids,
        ).create({
            'is_pine_labs_payment': True,
            'pine_labs_amount': self.amount,
            'journal_id': cash_journal.id,
        })

        return {
            'name': _('Register Cash Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move',
                'active_ids': active_ids,
                'pine_labs_wizard_amount': self.amount,
                'default_journal_id': cash_journal.id,
            },
        }

    # ─────────────────────────────────────────────────────────────────
    # Pine Labs: Card or UPI
    # ─────────────────────────────────────────────────────────────────

    def _action_initiate_pinelabs_payment(self):
        """Send payment request to Pine Labs terminal (Card or UPI)."""
        self.ensure_one()

        # Determine terminal config: use selected terminal
        terminal = self.terminal_id
        if not terminal:
            # Auto-pick first branch terminal if available
            branch_terminals = self._get_branch_terminals()
            if branch_terminals:
                terminal = branch_terminals[0]
        if not terminal:
            raise UserError(
                _('No Pine Labs terminal is configured for this branch. '
                  'Go to Accounting → Configuration → Pine Labs Terminals to add one.')
            )
        config = terminal.get_config()

        billing_ref = (
                self.sale_order_id.name or
                (self.invoice_id and self.invoice_id.name) or
                (self.payment_id and self.payment_id.name) or
                f'PAY-{int(time.time())}'
        )

        # Determine AllowedPaymentMode from wizard selection
        allowed_mode = PINE_LABS_MODE_MAP.get(self.payment_method_type, '1')

        # Create the transaction log record
        txn = self.env['pinelabs.transaction'].create({
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'sale_order_id': self.sale_order_id.id if self.sale_order_id else False,
            'invoice_id': self.invoice_id.id if self.invoice_id else False,
            'payment_id': self.payment_id.id if self.payment_id else False,
            'terminal_id': terminal.terminal_id if terminal else '',
            'merchant_id': config['merchant_id'] if config else 'DEMO',
            'pinelabs_terminal_id': terminal.id if terminal else False,
        })

        # Call the Pine Labs API (pass mode override)
        response = txn.pinelabs_create_payment(self.amount, allowed_mode=allowed_mode)
        if response.get('error'):
            txn.state = 'failed'
            self.state = 'failed'
            raise UserError(_('Pine Labs Error: %s') % response['error'])

        ref_id = (
                response.get('PlutusTransactionReferenceID') or
                response.get('plutusTransactionReferenceID')
        )
        if not ref_id:
            txn.state = 'failed'
            self.state = 'failed'
            raise UserError(
                _('Pine Labs did not return a transaction reference. Response: %s') % response
            )

        self.write({
            'state': 'waiting',
            'pinelabs_transaction_ref': str(ref_id),
            'txn_id': txn.id,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ─────────────────────────────────────────────────────────────────
    # Status check & cancel (Pine Labs only)
    # ─────────────────────────────────────────────────────────────────

    def action_check_status(self):
        """Poll Pine Labs for the current transaction status."""
        self.ensure_one()
        if not self.txn_id or not self.pinelabs_transaction_ref:
            raise UserError(_('No transaction in progress.'))

        result = self.txn_id.pinelabs_check_status()
        status = result.get('status', 'pending')

        if status == 'success':
            self.write({
                'state': 'success',
                'approval_code': result.get('data', {}).get('ApprovalCode', '') if 'data' in result else '',
                'card_type': result.get('data', {}).get('CardType', '') if 'data' in result else '',
                'payment_mode': result.get('data', {}).get('TxnModeName', '') if 'data' in result else '',
            })
            self._post_payment_success()
        elif status == 'failed':
            self.state = 'failed'
            raise UserError(_('Pine Labs payment failed: %s') % result.get('message', 'Unknown error'))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _post_payment_success(self):
        """
        After a successful Pine Labs transaction:
        - Post and reconcile the invoice (for SO/invoice flow)
        - Post the vendor payment record (for Purchase flow)
        """
        self.ensure_one()
        txn = self.txn_id

        if self.invoice_id and self.invoice_id.state == 'draft':
            self.invoice_id.action_post()

        if self.invoice_id and self.invoice_id.state == 'posted':
            journal = False
            if self.payment_method_type == 'card':
                journal = txn.pinelabs_terminal_id.card_journal_id
            elif self.payment_method_type == 'upi':
                journal = txn.pinelabs_terminal_id.upi_journal_id

            if not journal:
                # Fallback to the first available bank/cash journal if not configured on the terminal
                journal = self.env['account.journal'].search([
                    ('type', 'in', ('bank', 'cash')),
                    ('company_id', '=', self.env.company.id),
                ], limit=1)

            if journal:
                is_outbound = self.invoice_id.move_type in ('in_invoice', 'out_refund')
                payment = self.env['account.payment'].create({
                    'payment_type': 'outbound' if is_outbound else 'inbound',
                    'partner_type': 'supplier' if is_outbound else 'customer',
                    'partner_id': self.invoice_id.partner_id.id,
                    'amount': self.amount,
                    'currency_id': self.currency_id.id,
                    'journal_id': journal.id,
                    'payment_method_line_id': journal.inbound_payment_method_line_ids[:1].id,
                    'ref': txn.name,
                    'pinelabs_transaction_id': txn.id,
                })
                payment.action_post()
                lines = (payment.move_id | self.invoice_id.sudo()).mapped('line_ids').filtered(
                    lambda l: not l.reconciled and l.account_id.account_type in (
                        'asset_receivable', 'liability_payable')
                )
                lines.reconcile()

        if self.payment_id and self.payment_id.state == 'draft':
            self.payment_id.pinelabs_transaction_id = txn.id
            self.payment_id.action_post()

    def action_cancel_payment(self):
        """Cancel the current Pine Labs terminal transaction."""
        self.ensure_one()
        if self.txn_id:
            self.txn_id.pinelabs_cancel_payment()
        self.state = 'failed'
        return {'type': 'ir.actions.act_window_close'}