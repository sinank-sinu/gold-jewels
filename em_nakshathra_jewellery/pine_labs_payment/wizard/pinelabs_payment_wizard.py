# -*- coding: utf-8 -*-
import time

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta  # Added for safe month arithmetic

import logging
_logger = logging.getLogger(__name__)


# Maps wizard payment_method_type to Pine Labs AllowedPaymentMode codes
# Pine Labs AllowedPaymentMode reference:
#   0=All modes, 1=Card, 2=Cash, 3=Points, 4=Wallets,
#   6=Brand EMI, 7=Sodexo, 8=PhonePe, 10=UPI Sale
PINE_LABS_MODE_MAP = {
    'card': 1,
    'upi': 10,
    'points': 3,   # Points / Reward Redemption (State Bank Rewardz, etc.)
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

    cash_account_id = fields.Many2one(
        'account.account',
        string='Cash Account',
    )

    @api.onchange('payment_method_type')
    def _onchange_payment_method_type(self):
        if self.payment_method_type == 'cash' and not self.cash_account_id:
            branch = self._get_payment_branch()
            cash_journal = self._get_branch_journal('cash', branch)
            if cash_journal and cash_journal.default_account_id:
                self.cash_account_id = cash_journal.default_account_id

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

    # ── Auto-polling tracking fields ───────────────────────────────────
    poll_count = fields.Integer(string='Poll Attempts', default=0, readonly=True)
    max_polls = fields.Integer(string='Max Poll Attempts', default=10)   # 10 × 5s = 50s
    poll_interval = fields.Integer(string='Poll Interval (seconds)', default=5)
    cancel_attempts = fields.Integer(string='Cancel Attempts', default=0, readonly=True)
    cancel_message = fields.Char(string='Cancel Status Message', readonly=True)

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

    def _get_pinelabs_payment_journal(self, terminal=None):
        self.ensure_one()
        terminal = terminal or self.terminal_id
        if not terminal:
            terminals = self._get_branch_terminals()
            terminal = terminals[:1]
        if not terminal:
            raise UserError(_('No Pine Labs terminal is configured for this branch.'))

        journal_field = {
            'card': 'card_journal_id',
            'upi': 'upi_journal_id',
        }.get(self.payment_method_type)
        if not journal_field:
            raise UserError(_('A Pine Labs journal is only available for Card or UPI payments.'))

        journal = terminal[journal_field]
        if not journal:
            raise UserError(_(
                'Configure the %(mode)s payment journal on Pine Labs terminal %(terminal)s.',
                mode=self.payment_method_type.upper(),
                terminal=terminal.display_name,
            ))

        branch = self._get_payment_branch()
        company = branch.company_id if branch else self.env.company
        if journal.company_id != company:
            raise UserError(_(
                'The %(mode)s journal %(journal)s on terminal %(terminal)s belongs to a different company.',
                mode=self.payment_method_type.upper(),
                journal=journal.display_name,
                terminal=terminal.display_name,
            ))
        if branch and journal.branch_id and journal.branch_id != branch:
            raise UserError(_(
                'The %(mode)s journal %(journal)s on terminal %(terminal)s belongs to branch %(journal_branch)s, '
                'not payment branch %(payment_branch)s.',
                mode=self.payment_method_type.upper(),
                journal=journal.display_name,
                terminal=terminal.display_name,
                journal_branch=journal.branch_id.display_name,
                payment_branch=branch.display_name,
            ))
        return journal

    def _get_payment_branch(self):
        self.ensure_one()
        branch = False
        branch_sources = (
            (self.invoice_id, 'branch_id'),
            (self.sale_order_id, 'branch_id'),
            (
                self.payment_id.invoice_id
                if self.payment_id and 'invoice_id' in self.payment_id._fields
                else self.env['account.move'],
                'branch_id',
            ),
            (self.payment_id, 'branch_id'),
        )
        for record, field_name in branch_sources:
            if record and field_name in record._fields:
                branch = record[field_name]
                if branch:
                    break
        if (
            not branch
            and self.scheme_installment_id
            and 'branch_id' in self.scheme_installment_id.enrollment_id._fields
        ):
            branch = self.scheme_installment_id.enrollment_id.branch_id
        if (
            not branch
            and self.scheme_installment_id
            and self.scheme_installment_id.journal_id.branch_id
        ):
            branch = self.scheme_installment_id.journal_id.branch_id
        if not branch and 'branch_id' in self.env.user._fields:
            branch = self.env.user.branch_id
        if (
            branch
            and 'branch_ids' in self.env.user._fields
            and branch not in self.env.user.branch_ids
        ):
            raise UserError(
                _('You are not allowed to register payments for branch %s.') % branch.name
            )
        return branch

    def _get_branch_journal(self, journal_type, branch, excluded_journal_ids=None):
        company = branch.company_id if branch else self.env.company
        domain = [
            ('type', '=', journal_type),
            ('company_id', '=', company.id),
            ('name', 'not ilike', 'suspense'),
            ('name', 'not ilike', 'suspence'),
        ]
        if excluded_journal_ids:
            domain.append(('id', 'not in', excluded_journal_ids))
        journals = self.env['account.journal']
        if branch:
            branch_journal = journals.search(
                domain + [('branch_id', '=', branch.id)], limit=1
            )
            if branch_journal:
                return branch_journal
            return journals.search(domain + [('branch_id', '=', False)], limit=1)
        return journals.search(domain, limit=1)

    def _get_selected_payment_journal(self, journal_type, branch, excluded_journal_ids=None):
        self.ensure_one()
        if not self.payment_id:
            return self.env['account.journal']

        journal = self.payment_id.move_id.journal_id
        if (
            journal.type != journal_type
            or journal.id in (excluded_journal_ids or [])
        ):
            return self.env['account.journal']

        company = branch.company_id if branch else self.payment_id.company_id
        if journal.company_id != company:
            raise UserError(_(
                "The selected payment journal %(journal)s belongs to a different company.",
                journal=journal.display_name,
            ))

        if branch and journal.branch_id and journal.branch_id != branch:
            return self.env['account.journal']

        return journal

    def _get_installment_journal(self, journal_type, excluded_journal_ids=None):
        self.ensure_one()
        installment = self.scheme_installment_id
        journal = installment.journal_id
        if not journal:
            return journal
        if journal.id in (excluded_journal_ids or []):
            return self.env['account.journal']

        if journal.type != journal_type:
            raise UserError(_(
                "The journal selected on this installment (%(journal)s) is %(actual_type)s, "
                "but %(expected_type)s is required for this payment.",
                journal=journal.display_name,
                actual_type=journal.type,
                expected_type=journal_type,
            ))

        enrollment_branch = installment.enrollment_id.branch_id
        if enrollment_branch and journal.branch_id and journal.branch_id != enrollment_branch:
            raise UserError(_(
                "The installment journal %(journal)s belongs to %(journal_branch)s, "
                "but this scheme belongs to %(scheme_branch)s.",
                journal=journal.display_name,
                journal_branch=journal.branch_id.display_name,
                scheme_branch=enrollment_branch.display_name,
            ))

        payment_branch = self._get_payment_branch()
        if payment_branch and journal.branch_id and journal.branch_id != payment_branch:
            raise UserError(_(
                "The installment journal %(journal)s belongs to %(journal_branch)s, "
                "but this payment belongs to %(payment_branch)s.",
                journal=journal.display_name,
                journal_branch=journal.branch_id.display_name,
                payment_branch=payment_branch.display_name,
            ))

        if journal.branch_id and 'branch_ids' in self.env.user._fields:
            if journal.branch_id not in self.env.user.branch_ids:
                raise UserError(_(
                    "You are not allowed to use journal %(journal)s from branch %(branch)s.",
                    journal=journal.display_name,
                    branch=journal.branch_id.display_name,
                ))

        expected_company = payment_branch.company_id if payment_branch else self.env.company
        if journal.company_id != expected_company:
            raise UserError(_(
                "The installment journal %(journal)s belongs to a different company.",
                journal=journal.display_name,
            ))
        return journal

    # ─────────────────────────────────────────────────────────────────
    # Payment mode toggle buttons (Card / UPI / Bank)
    # ─────────────────────────────────────────────────────────────────

    def _set_mode_and_refresh(self, mode):
        """Set payment_method_type and re-open the wizard to show selection."""
        self.payment_method_type = mode
        if mode in ('card', 'upi') and self.payment_id and self.payment_id.state == 'draft':
            self.payment_id.journal_id = self._get_pinelabs_payment_journal()
        if mode == 'cash' and not self.cash_account_id:
            branch = self._get_payment_branch()
            cash_journal = self._get_branch_journal('cash', branch)
            if cash_journal and cash_journal.default_account_id:
                self.cash_account_id = cash_journal.default_account_id
                
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
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
        """Route to Bank / Cash / Pine Labs and handle installment allocation."""
        self.ensure_one()

        if self.payment_method_type == 'bank':
            result = self._action_register_bank_payment()
        elif self.payment_method_type == 'cash':
            result = self._action_register_cash_payment()
        else:
            result = self._action_initiate_pinelabs_payment()
        return result


    # ─────────────────────────────────────────────────────────────────
    # Bank Transfer: Use Odoo's standard Register Payment wizard
    # ─────────────────────────────────────────────────────────────────

    def _action_register_bank_payment(self):
        """Open Odoo's standard Register Payment wizard for bank/cash."""
        self.ensure_one()

        branch = self._get_payment_branch()
        target_company_id = branch.company_id.id if branch else self.env.company.id

        terminal_domain = [('branch_id.company_id', '=', target_company_id)]
        if branch:
            terminal_domain.append(('branch_id', '=', branch.id))
        terminal_journals = self.env['pinelabs.terminal'].with_context(
            active_test=False,
        ).search(terminal_domain)
        terminal_payment_journals = (
            terminal_journals.mapped('card_journal_id')
            | terminal_journals.mapped('upi_journal_id')
        )

        bank_journal = self._get_selected_payment_journal(
            'bank', branch, terminal_payment_journals.ids
        )
        if not bank_journal:
            bank_journal = self._get_installment_journal(
                'bank', terminal_payment_journals.ids
            )
        if not bank_journal:
            bank_journal = self._get_branch_journal(
                'bank', branch, terminal_payment_journals.ids
            )
            
        if not bank_journal:
            if branch:
                raise UserError(_('No bank journal found for branch %s. Please create a bank branch journal first.') % branch.name)
            else:
                raise UserError(_('No bank journal found. Please create a bank journal first.'))
        if self.payment_id and self.payment_id.state == 'draft':
            self.payment_id.amount = self.amount
            self.payment_id.journal_id = bank_journal.id
            self.payment_id.action_post()
            return {'type': 'ir.actions.act_window_close'}
        # ─── NEW HOOK: Handle Scheme Installments for Bank Transfer directly ───
        if self.scheme_installment_id:
            rec = self.scheme_installment_id

            payment_journal = bank_journal

            # Target dynamic Debtors Account Search matching your exact accounting structure logic
            debtors_domain = [('name', 'ilike', 'Debtors'), ('company_id', '=', payment_journal.company_id.id)]
            if branch:
                debtors_domain = [
                    ('name', 'ilike', 'Debtors'),
                    ('company_id', '=', payment_journal.company_id.id),
                    '|', ('branch_id', '=', branch.id), ('branch_id', '=', False)
                ]
            debtors_account = self.env['account.account'].search(debtors_domain, limit=1)

            if not debtors_account:
                raise UserError(_("Debtors account not found in Chart of Accounts for company %s.") % payment_journal.company_id.name)

            out_accs = payment_journal._get_journal_inbound_outstanding_payment_accounts()
            liability_account = out_accs[0] if out_accs else payment_journal.default_account_id
            if not liability_account:
                raise UserError(_("Please configure a default account on Journal: %s") % payment_journal.name)

            # Generate the financial transaction entry document exactly like your original custom button
            move_vals = {
                'move_type': 'entry',
                'journal_id': payment_journal.id,
                'company_id': payment_journal.company_id.id,
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
            }
            if branch:
                move_vals['branch_id'] = branch.id
            move = self.env['account.move'].create(move_vals)

            # Force entry validation adjustments straight down to General Ledgers
            move.action_post()
            rec.write({
                'amount': self.amount,
                'journal_id': move.journal_id.id,
                'move_id': move.id,
                'transaction_id': 'BANK-TRANSFER',
                'state': 'paid'
            })

            # Close the wizard popup upon success
            return {'type': 'ir.actions.act_window_close'}
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

        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=active_ids,
        ).create({
            'is_pine_labs_payment': True,
            'pine_labs_amount': self.amount,
            'journal_id': bank_journal.id,
        })

        return {
            'name': _('Register Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'active_model': 'account.move',
                'active_ids': active_ids,
                'pine_labs_wizard_amount': self.amount,
                'default_journal_id': bank_journal.id,
            },
        }

    # ─────────────────────────────────────────────────────────────────
    # Cash Payment: Auto-select Cash journal
    # ─────────────────────────────────────────────────────────────────

    def _action_register_cash_payment(self):
        """Open Odoo's standard Register Payment wizard for cash with journal preset."""
        self.ensure_one()

        branch = self._get_payment_branch()
        target_company_id = branch.company_id.id if branch else self.env.company.id
        cash_journal = self._get_selected_payment_journal('cash', branch)
        if not cash_journal:
            cash_journal = self._get_installment_journal('cash')
        if not cash_journal:
            cash_journal = self._get_branch_journal('cash', branch)
            
        if not cash_journal:
            if branch:
                raise UserError(_('No cash journal found for branch %s. Please create a cash branch journal first to proceed with cash payment.') % branch.name)
            else:
                raise UserError(_('No cash journal found. Please create a cash journal first to proceed with cash payment.'))

        if self.payment_id and self.payment_id.state == 'draft':
            payment_vals = {
                'amount': self.amount,
                'journal_id': cash_journal.id,
            }
            if branch:
                payment_vals['branch_id'] = branch.id
            self.payment_id.write(payment_vals)
            
            if self.cash_account_id:
                liquidity_line = self.payment_id.move_id.line_ids.filtered(
                    lambda l: l.account_id.id == self.payment_id.outstanding_account_id.id
                )
                if liquidity_line:
                    liquidity_line.with_context(check_move_validity=False).account_id = self.cash_account_id.id
                    
            self.payment_id.action_post()
            return {'type': 'ir.actions.act_window_close'}

        # ─── NEW HOOK: Handle Scheme Installments for Cash Transfer directly ───
        if self.scheme_installment_id:
            rec = self.scheme_installment_id

            payment_journal = cash_journal

            # Target dynamic Debtors Account Search matching your exact accounting structure logic
            debtors_domain = [('name', 'ilike', 'Debtors'), ('company_id', '=', payment_journal.company_id.id)]
            if branch:
                debtors_domain = [
                    ('name', 'ilike', 'Debtors'),
                    ('company_id', '=', payment_journal.company_id.id),
                    '|', ('branch_id', '=', branch.id), ('branch_id', '=', False)
                ]
            debtors_account = self.env['account.account'].search(debtors_domain, limit=1)

            if not debtors_account:
                raise UserError(_("Debtors account not found in Chart of Accounts for company %s.") % payment_journal.company_id.name)

            out_accs = payment_journal._get_journal_inbound_outstanding_payment_accounts()
            liability_account = self.cash_account_id if self.cash_account_id else (out_accs[0] if out_accs else payment_journal.default_account_id)
            if not liability_account:
                raise UserError(_("Please select a Cash Account or configure a default account on Journal: %s") % payment_journal.name)

            # Generate the financial transaction entry document exactly like your original custom button
            move_vals = {
                'move_type': 'entry',
                'journal_id': payment_journal.id,
                'company_id': payment_journal.company_id.id,
                'ref': _('Scheme Payment via Cash - %s') % (rec.enrollment_id.name or ''),
                'line_ids': [
                    (0, 0, {
                        'name': _('Scheme Liability - %s') % (rec.enrollment_id.name or ''),
                        'partner_id': rec.enrollment_id.partner_id.id,
                        'credit': 0.0,
                        'debit': self.amount,
                        'account_id': liability_account.id
                    }),
                    (0, 0, {
                        'name': _('Scheme Payment via Cash'),
                        'partner_id': rec.enrollment_id.partner_id.id,
                        'debit': 0.0,
                        'credit': self.amount,
                        'account_id': debtors_account.id
                    })
                ]
            }
            if branch:
                move_vals['branch_id'] = branch.id
            move = self.env['account.move'].create(move_vals)

            # Force entry validation adjustments straight down to General Ledgers
            move.action_post()

            rec.write({
                'amount': self.amount,
                'journal_id': payment_journal.id,
                'move_id': move.id,
                'transaction_id': 'CASH',
                'state': 'paid'
            })

            # Close the wizard popup upon success
            return {'type': 'ir.actions.act_window_close'}

        # Handle both invoice_id and sale_order_id
        if self.invoice_id or self.sale_order_id:
            if not self.cash_account_id:
                raise UserError(_("Please select a Cash Account for Cash Payment."))
            
            invoices = self.invoice_id
            if not invoices and self.sale_order_id:
                invoices = self.sale_order_id.invoice_ids.filtered(
                    lambda inv: inv.state == 'posted' and inv.payment_state in ('not_paid', 'partial')
                )
                if not invoices:
                    raise UserError(_('No posted unpaid invoice found for this Sale Order.'))

            first_inv = invoices[0]
            is_outbound = first_inv.move_type in ('in_invoice', 'out_refund')
            
            payment_vals = {
                'payment_type': 'outbound' if is_outbound else 'inbound',
                'partner_type': 'supplier' if is_outbound else 'customer',
                'partner_id': first_inv.partner_id.id,
                'amount': self.amount,
                'currency_id': self.currency_id.id,
                'journal_id': cash_journal.id,
                'ref': first_inv.name,
            }
            if branch:
                payment_vals['branch_id'] = branch.id
            
            if is_outbound and cash_journal.outbound_payment_method_line_ids:
                payment_vals['payment_method_line_id'] = cash_journal.outbound_payment_method_line_ids[:1].id
            elif not is_outbound and cash_journal.inbound_payment_method_line_ids:
                payment_vals['payment_method_line_id'] = cash_journal.inbound_payment_method_line_ids[:1].id
                
            payment = self.env['account.payment'].create(payment_vals)
            
            if self.cash_account_id:
                # Update the liquidity line before posting to use the selected cash account
                liquidity_line = payment.move_id.line_ids.filtered(
                    lambda l: l.account_id.id == payment.outstanding_account_id.id or l.account_id.id == cash_journal.default_account_id.id
                )
                if liquidity_line:
                    liquidity_line.with_context(check_move_validity=False).account_id = self.cash_account_id.id
                    
            payment.action_post()
            
            # Reconcile with the invoice(s)
            lines = (payment.move_id | invoices).mapped('line_ids').filtered(
                lambda l: not l.reconciled and l.account_id.account_type in ('asset_receivable', 'liability_payable')
            )
            if len(lines) > 1:
                lines.reconcile()

            return {'type': 'ir.actions.act_window_close'}


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

        import re
        raw_ref = (
                self.sale_order_id.name or
                (self.invoice_id and self.invoice_id.name) or
                (self.payment_id and self.payment_id.name) or
                (self.scheme_installment_id and (self.scheme_installment_id.enrollment_id.ticket_number or self.scheme_installment_id.enrollment_id.name)) or
                f'PAY{int(time.time())}'
        )
        billing_ref = re.sub(r'[^A-Za-z0-9]', '', str(raw_ref)) or f'PAY{int(time.time())}'

        # Determine AllowedPaymentMode from wizard selection
        allowed_mode = PINE_LABS_MODE_MAP.get(self.payment_method_type, 1)

        if allowed_mode == 10 and self.amount < 1.0:
            raise UserError(_('Minimum amount for Pine Labs UPI payment is ₹1.00 (100 paise). Please enter an amount of at least ₹1.00.'))

        # Create the transaction log record
        txn = self.env['pinelabs.transaction'].create({
            'name': billing_ref,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'sale_order_id': self.sale_order_id.id if self.sale_order_id else False,
            'invoice_id': self.invoice_id.id if self.invoice_id else False,
            'payment_id': self.payment_id.id if self.payment_id else False,
            'terminal_id': terminal.terminal_id if terminal else '',
            'merchant_store_pos_code': config.get('merchant_store_pos_code', ''),
            'imei': config.get('imei', ''),
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
        try:
            ref_int = int(ref_id) if ref_id is not None else 0
        except (ValueError, TypeError):
            ref_int = 0

        resp_code = response.get('ResponseCode')
        resp_msg = response.get('ResponseMessage') or ''

        if (resp_code is not None and str(resp_code) != '0') or ref_int <= 0:
            txn.state = 'failed'
            self.state = 'failed'
            if 'OPEN TXN' in resp_msg.upper() or 'APPROVE' in resp_msg.upper():
                cancel_err = response.get('TerminalCancelError')
                existing_ref = response.get('ExistingReferenceId')
                extra = f" ({cancel_err})" if cancel_err else ""
                ref_txt = f" #{existing_ref}" if existing_ref else ""
                raise UserError(
                    _('The Pine Labs terminal has an active transaction in progress%s%s.\n\n'
                      'How to clear it:\n'
                      '• On the physical Pine Labs machine: press the RED key (Cancel / ✕) on the keypad.\n'
                      '• If a card is inserted or tapped, remove the card first.\n'
                      '• Once the terminal returns to its home/idle screen, click "Send to Terminal" again.') % (ref_txt, extra)
                )
            raise UserError(
                _('Pine Labs Terminal Error: %s (Code: %s)') % (resp_msg or _('Declined'), resp_code or 'N/A')
            )

        self.write({
            'state': 'waiting',
            'pinelabs_transaction_ref': str(ref_int),
            'txn_id': txn.id,
            'poll_count': 0,
            'cancel_attempts': 0,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }





    # ─────────────────────────────────────────────────────────────────
    # Status check & cancel (Pine Labs only)
    # ─────────────────────────────────────────────────────────────────

    def _process_check_result(self, result):
        """
        Shared helper: parse a pinelabs_check_status() result dict and apply
        wizard state changes.  Returns a simple status string:
        'success' | 'failed' | 'pending'
        """
        status = result.get('status', 'pending')

        if status == 'success':
            data = result.get('data', {})

            def _d(*keys):
                for k in keys:
                    v = data.get(k, '')
                    if v:
                        return str(v)
                return ''

            payment_mode_val  = _d('PaymentMode', 'Payment Mode')
            card_type_val     = _d('CardType', 'Card Type')
            approval_code_val = _d('ApprovalCode')
            customer_vpa_val  = _d('CustomerVPA', 'Customer VPA')

            wizard_vals = {
                'state': 'success',
                'approval_code': approval_code_val,
                'payment_mode': payment_mode_val,
            }
            if card_type_val:
                wizard_vals['card_type'] = card_type_val
            elif customer_vpa_val:
                wizard_vals['card_type'] = customer_vpa_val

            self.write(wizard_vals)
            self._post_payment_success()

        elif status == 'failed':
            self.write({'state': 'failed'})

        return status

    def action_check_status(self):
        """Manual poll — user clicked Check Status button."""
        self.ensure_one()
        if not self.txn_id or not self.pinelabs_transaction_ref:
            raise UserError(_('No transaction in progress.'))

        result = self.txn_id.pinelabs_check_status()
        self.poll_count += 1
        status = self._process_check_result(result)

        if status == 'success':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Payment Successful!'),
                    'message': _('Pine Labs transaction confirmed and invoice reconciled.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        elif status == 'failed':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Payment Failed'),
                    'message': result.get('message', _('Payment declined or cancelled on terminal.')),
                    'type': 'danger',
                    'sticky': True,
                }
            }

        # If reached maximum attempts during manual check, auto-cancel
        if self.poll_count >= self.max_polls:
            try:
                self.txn_id.pinelabs_cancel_payment()
            except Exception as e:
                _logger.warning('Failed to cancel Pine Labs txn on manual timeout: %s', e)

            cancel_msg = _('Payment automatically cancelled after %d attempts (timed out).') % self.poll_count
            self.write({
                'state': 'failed',
                'cancel_message': cancel_msg,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Transaction Cancelled (Timeout)'),
                    'message': cancel_msg,
                    'type': 'warning',
                    'sticky': True,
                }
            }

        # Pending
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Payment Pending'),
                'message': _('Waiting for customer to complete transaction on the Pine Labs terminal (Checked %d times).') % self.poll_count,
                'type': 'warning',
                'sticky': False,
            }
        }

    def action_auto_check_status(self):
        """
        Called by the JS auto-poller (every poll_interval seconds).
        Returns a plain dict — NOT an ir.actions window — so the JS
        can decide what to do without the dialog re-opening.

        Return dict keys:
          status   : 'success' | 'failed' | 'pending' | 'timeout' | 'error'
          poll_count: current attempt number
          max_polls : configured maximum
          message  : human-readable detail (on failure/timeout)
        """
        self.ensure_one()
        if self.state in ('success', 'failed'):
            # Already resolved — nothing to poll
            return {
                'status': self.state,
                'poll_count': self.poll_count,
                'max_polls': self.max_polls,
                'message': self.cancel_message or '',
            }

        if not self.txn_id or not self.pinelabs_transaction_ref:
            return {'status': 'error', 'poll_count': self.poll_count,
                    'max_polls': self.max_polls,
                    'message': _('No active transaction found.')}

        # Increment attempt counter
        new_count = self.poll_count + 1
        self.poll_count = new_count

        # Automatically cancel if maximum attempts (10) reached
        if new_count >= self.max_polls:
            _logger.info('Auto-check reached %d/%d attempts for txn %s. Automatically cancelling...',
                         new_count, self.max_polls, self.pinelabs_transaction_ref)
            try:
                self.txn_id.pinelabs_cancel_payment()
            except Exception as e:
                _logger.warning('Failed to cancel Pine Labs txn on timeout: %s', e)

            cancel_msg = _('Payment automatically cancelled after %d attempts (timed out).') % self.max_polls
            self.write({
                'state': 'failed',
                'cancel_message': cancel_msg,
            })
            return {
                'status': 'failed',
                'poll_count': new_count,
                'max_polls': self.max_polls,
                'message': cancel_msg,
            }

        try:
            result = self.txn_id.pinelabs_check_status()
        except Exception as e:
            return {'status': 'error', 'poll_count': new_count,
                    'max_polls': self.max_polls, 'message': str(e)}

        status = self._process_check_result(result)
        msg = ''
        if status == 'failed':
            msg = result.get('message', _('Payment declined by terminal.'))

        return {
            'status': status,
            'poll_count': new_count,
            'max_polls': self.max_polls,
            'message': msg,
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

        payment = txn.payment_id or self.payment_id

        if (
            self.invoice_id
            and self.invoice_id.state == 'posted'
            and not payment
        ):
            journal = False
            if self.payment_method_type == 'card':
                journal = txn.pinelabs_terminal_id.card_journal_id
            elif self.payment_method_type == 'upi':
                journal = txn.pinelabs_terminal_id.upi_journal_id

            if not journal:
                # Fallback to the first available bank/cash journal if not configured on the terminal
                target_company_id = self.invoice_id.company_id.id if self.invoice_id else self.env.company.id
                journal = self.env['account.journal'].search([
                    ('type', 'in', ('bank', 'cash')),
                    ('company_id', '=', target_company_id),
                ], limit=1)

            if journal:
                is_outbound = self.invoice_id.move_type in ('in_invoice', 'out_refund')
                # Use Pine Labs PlutusTransactionReferenceID as the bank reference when available
                pinelabs_ref = txn.pinelabs_transaction_id or txn.name
                payment = self.env['account.payment'].create({
                    'payment_type': 'outbound' if is_outbound else 'inbound',
                    'partner_type': 'supplier' if is_outbound else 'customer',
                    'partner_id': self.invoice_id.partner_id.id,
                    'amount': self.amount,
                    'currency_id': self.currency_id.id,
                    'journal_id': journal.id,
                    'payment_method_line_id': journal.inbound_payment_method_line_ids[:1].id,
                    'ref': pinelabs_ref,
                    'pinelabs_transaction_id': txn.id,
                })
                payment.action_post()
                lines = (payment.move_id | self.invoice_id.sudo()).mapped('line_ids').filtered(
                    lambda l: not l.reconciled and l.account_id.account_type in (
                        'asset_receivable', 'liability_payable')
                )
                lines.reconcile()

        if self.payment_id and self.payment_id.state == 'draft':
            self.payment_id.amount = self.amount
            self.payment_id.pinelabs_transaction_id = txn.id
            # Set Bank Reference to Pine Labs PlutusTransactionReferenceID when available
            if txn.pinelabs_transaction_id:
                self.payment_id.ref = txn.pinelabs_transaction_id

            self.payment_id.journal_id = self._get_pinelabs_payment_journal(
                txn.pinelabs_terminal_id
            ).id
            self.payment_id.action_post()

        if self.scheme_installment_id:
            rec = self.scheme_installment_id
            journal = False
            if rec.journal_id:
                journal = rec.journal_id
            elif self.payment_method_type == 'card':
                journal = txn.pinelabs_terminal_id.card_journal_id
            elif self.payment_method_type == 'upi':
                journal = txn.pinelabs_terminal_id.upi_journal_id

            target_company_id = rec.enrollment_id.branch_id.company_id.id if rec.enrollment_id.branch_id and rec.enrollment_id.branch_id.company_id else self.env.company.id
            if not journal:
                journal = self.env['account.journal'].search([
                    ('type', 'in', ('bank', 'cash')),
                    ('company_id', '=', target_company_id),
                ], limit=1)

            if not journal:
                raise UserError(_("No suitable journal found for Pine Labs scheme payment."))

            branch = rec.enrollment_id.branch_id or self.env.user.branch_id
            debtors_domain = [('name', 'ilike', 'Debtors'), ('company_id', '=', journal.company_id.id)]
            if branch:
                debtors_domain = [
                    ('name', 'ilike', 'Debtors'),
                    ('company_id', '=', journal.company_id.id),
                    '|', ('branch_id', '=', branch.id), ('branch_id', '=', False)
                ]
            debtors_account = self.env['account.account'].search(debtors_domain, limit=1)
            if not debtors_account:
                raise UserError(_("Debtors account not found in Chart of Accounts."))

            out_accs = journal._get_journal_inbound_outstanding_payment_accounts()
            liability_account = out_accs[0] if out_accs else journal.default_account_id
            if not liability_account:
                raise UserError(_("Please configure a default account on Journal: %s") % journal.name)

            move_vals = {
                'move_type': 'entry',
                'journal_id': journal.id,
                'company_id': journal.company_id.id,
                'ref': _('Scheme Payment via %s - %s') % (self.payment_method_type.upper(), rec.enrollment_id.name or ''),
                'line_ids': [
                    (0, 0, {
                        'name': _('Scheme Liability - %s') % (rec.enrollment_id.name or ''),
                        'partner_id': rec.enrollment_id.partner_id.id,
                        'credit': 0.0,
                        'debit': self.amount,
                        'account_id': liability_account.id
                    }),
                    (0, 0, {
                        'name': _('Scheme Payment via %s') % self.payment_method_type.upper(),
                        'partner_id': rec.enrollment_id.partner_id.id,
                        'debit': 0.0,
                        'credit': self.amount,
                        'account_id': debtors_account.id
                    })
                ]
            }
            if branch:
                move_vals['branch_id'] = branch.id
            move = self.env['account.move'].create(move_vals)
            move.action_post()

            rec.write({
                'amount': self.amount,
                'journal_id': journal.id,
                'move_id': move.id,
                'transaction_id': self.approval_code or self.pinelabs_transaction_ref or self.payment_method_type.upper(),
                'state': 'paid',
            })

    def action_cancel_payment(self):
        """
        Cancel the current Pine Labs terminal transaction.
        If Pine Labs reports CANNOT CANCEL (e.g. transaction in progress),
        we DO NOT close or fail the wizard — we display the exact response,
        increment the cancel attempt count, and keep the dialog open.
        If Pine Labs successfully cancels the transaction, we mark it failed/cancelled
        and notify the user.
        """
        self.ensure_one()
        self.cancel_attempts += 1

        if not self.txn_id:
            self.write({
                'state': 'failed',
                'cancel_message': _('No transaction in progress.'),
            })
            return {'type': 'ir.actions.act_window_close'}

        response = self.txn_id.pinelabs_cancel_payment()
        resp_code = response.get('ResponseCode')
        resp_msg = response.get('ResponseMessage') or response.get('error') or ''

        if response.get('success'):
            # Terminal cancelled successfully
            success_msg = _('Transaction cancelled on terminal: %s') % (resp_msg or 'APPROVED')
            self.write({
                'state': 'failed',
                'cancel_message': success_msg,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Transaction Cancelled'),
                    'message': _('Pine Labs transaction #%s was successfully cancelled.') % (self.pinelabs_transaction_ref or ''),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        else:
            # Terminal did NOT cancel the transaction (e.g., "CANNOT CANCEL AS TRANSACTION IS IN PROGRESS")
            if 'IN PROGRESS' in (resp_msg or '').upper() or 'CANNOT CANCEL' in (resp_msg or '').upper():
                err_text = _('Transaction is in progress on the terminal. Press the Red Cancel (X) button on the Pine Labs terminal machine, wait a moment and retry, or click "Force Cancel (Unlock)".')
            else:
                err_text = resp_msg or _('Cannot cancel transaction (Code: %s)') % resp_code
            self.write({
                'cancel_message': err_text,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Cancel Request Failed (Attempt %d)') % self.cancel_attempts,
                    'message': err_text,
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_force_cancel(self):
        """
        Force cancel the transaction in Odoo when the terminal is unresponsive or stuck in progress.
        Marks the transaction as failed/cancelled and allows the cashier to proceed.
        """
        self.ensure_one()
        if self.txn_id:
            self.txn_id.write({'state': 'cancelled'})
        self.write({
            'state': 'failed',
            'cancel_message': _('Transaction was force-cancelled in Odoo.'),
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transaction Force Cancelled'),
                'message': _('The Pine Labs transaction was cancelled in Odoo.'),
                'type': 'warning',
                'sticky': False,
            }
        }

    def action_reset_draft(self):
        """Reset wizard to draft state so the user can start over or choose another payment method."""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'txn_id': False,
            'pinelabs_transaction_ref': False,
            'poll_count': 0,
            'cancel_attempts': 0,
            'cancel_message': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }