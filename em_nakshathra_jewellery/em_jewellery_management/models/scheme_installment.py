from odoo import models, fields, _, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare
from dateutil.relativedelta import relativedelta  # Added for safe month arithmetic


class JewellerySchemeInstallment(models.Model):
    _name = 'jewellery.scheme.installment'
    _description = 'Scheme Installment'

    enrollment_id = fields.Many2one(
        'jewellery.scheme.enrollment',
        required=True,
        ondelete='cascade'
    )

    date = fields.Date(default=fields.Date.today)
    amount = fields.Float(required=True)

    journal_id = fields.Many2one('account.journal')
    move_id = fields.Many2one('account.move', string="Customer Move")
    suspense_move_id = fields.Many2one('account.move', string="Suspense Move", copy=False)
    transaction_id = fields.Char(string="Transaction ID", copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('paid', 'Paid')
    ], default='draft')
    remark = fields.Char(string="Remark")
    is_transferred = fields.Boolean(string="Transferred", default=False, copy=False)

    def action_transfer(self):
        self.ensure_one()

        if self.is_transferred:
            raise UserError(_("This installment has already been transferred!"))

        if not self.amount or self.amount <= 0:
            raise UserError(_("Installment amount must be greater than zero to transfer."))

        partner = self.enrollment_id.partner_id
        if not partner:
            raise UserError(_("No partner found on the scheme enrollment."))

        enrollment = self.enrollment_id
        expected_total = enrollment.duration * enrollment.installment_amount
        if expected_total > 0 and (enrollment.total_paid + self.amount) > expected_total:
            raise UserError(
                _("Transfer limit exceeded. Total allowed amount for this scheme is %s. You cannot transfer more than the allowed duration.") % expected_total)

        target_company_id = self.enrollment_id.branch_id.company_id.id if self.enrollment_id.branch_id and hasattr(
            self.enrollment_id.branch_id,
            'company_id') and self.enrollment_id.branch_id.company_id else self.env.company.id
        target_company = self.env['res.company'].browse(target_company_id)

        # 1. Find Miscellaneous Journal for target company
        journal = self.env['account.journal'].search([
            ('company_id', '=', target_company_id),
            ('code', '=', 'SUS')
        ], limit=1) or self.env['account.journal'].search([
            ('company_id', '=', target_company_id),
            ('name', 'ilike', 'suspense')
        ], limit=1) or self.env['account.journal'].search([
            ('company_id', '=', target_company_id),
            ('type', '=', 'general')
        ], limit=1)

        if not journal:
            raise UserError(
                _("Miscellaneous Journal missing!\nPlease create or configure a Miscellaneous Journal for company '%s'.") % target_company.name)

        # 2. Get Suspense Partner
        suspense_partner = self.env['res.partner'].search([
            ('name', 'ilike', 'Suspense')
        ], limit=1)

        if not suspense_partner or not suspense_partner.id:
            suspense_partner = self.env['res.partner'].create({
                'name': 'Scheme Suspense',
                'company_id': False,
            })

        # 3. Get Customer Debtors Account
        debtors_account = partner.with_company(target_company).property_account_receivable_id
        if debtors_account and debtors_account.company_id and debtors_account.company_id.id != target_company_id:
            debtors_account = False

        if not debtors_account:
            debtors_account = self.env['account.account'].search([
                ('company_id', '=', target_company_id),
                ('account_type', '=', 'asset_receivable')
            ], limit=1)

        if not debtors_account or not debtors_account.id:
            raise UserError(
                _("No Receivable account found on the partner '%s', and no generic receivable account found for company '%s'.") % (
                    partner.name, target_company.name))

        # 4. Get Outstanding Receipts Account

        outstanding_receipt_account = self.env['account.account'].search([
            ('company_id', '=', target_company_id),
            ('name', 'ilike', 'Outstanding Receipt')
        ], limit=1) or self.env['account.account'].search([
            ('company_id', '=', target_company_id),
            ('name', 'ilike', 'Outstanding Reciept')
        ], limit=1) or self.env['account.account'].search([
            ('company_id', '=', target_company_id),
            ('name', 'ilike', 'Outstanding')
        ], limit=1)

        if not outstanding_receipt_account or not outstanding_receipt_account.id:
            raise UserError(_("Outstanding Receipts Account missing for company '%s'.") % target_company.name)

        # ------------------------------------------------------------------
        branch_id = self.enrollment_id.branch_id.id if self.enrollment_id.branch_id else False
        entry_date = self.date or fields.Date.today()

        # ------------------------------------------------------------------
        # ENTRY 2 (Miscellaneous Journal - Suspense Partner Clearing):
        # Line 1 (Debit): Debtor / Suspense Account (Debit) - Suspense Partner
        # Line 2 (Credit): Outstanding Receipts Account (Credit) - Suspense Partner
        # ------------------------------------------------------------------
        entry2_vals = {
            'journal_id': journal.id,
            'company_id': target_company_id,
            'date': entry_date,
            'ref': f"Scheme Transfer (Suspense) - {self.enrollment_id.name or partner.name}",
            'partner_id': suspense_partner.id,
            'branch_id': branch_id,
            'line_ids': [
                (0, 0, {
                    'account_id': debtors_account.id,
                    'partner_id': suspense_partner.id,
                    'name': f"Transfer Scheme Suspense Debtor - {suspense_partner.name}",
                    'debit': self.amount,
                    'credit': 0.0,
                    'company_id': target_company_id,
                    'branch_id': branch_id,
                }),
                (0, 0, {
                    'account_id': outstanding_receipt_account.id,
                    'partner_id': suspense_partner.id,
                    'name': f"Transfer Scheme Suspense Outstanding Receipt - {suspense_partner.name}",
                    'debit': 0.0,
                    'credit': self.amount,
                    'company_id': target_company_id,
                    'branch_id': branch_id,
                })
            ]
        }
        move2 = self.env['account.move'].create(entry2_vals)
        move2.write({'partner_id': suspense_partner.id})
        move2.action_post()

        # ------------------------------------------------------------------
        # ENTRY 3 (Miscellaneous Journal - Customer Partner Allocation):
        # Line 1 (Debit): Outstanding Receipts Account (Debit) - Customer Partner
        # Line 2 (Credit): Debtor Account (Credit) - Customer Partner
        # ------------------------------------------------------------------
        entry3_vals = {
            'journal_id': journal.id,
            'company_id': target_company_id,
            'date': entry_date,
            'ref': f"Scheme Transfer - {self.enrollment_id.name or partner.name}",
            'partner_id': partner.id,
            'branch_id': branch_id,
            'line_ids': [
                (0, 0, {
                    'account_id': outstanding_receipt_account.id,
                    'partner_id': partner.id,
                    'name': f"Scheme Outstanding Receipt - {partner.name}",
                    'debit': self.amount,
                    'credit': 0.0,
                    'company_id': target_company_id,
                    'branch_id': branch_id,
                }),
                (0, 0, {
                    'account_id': debtors_account.id,
                    'partner_id': partner.id,
                    'name': f"Scheme Debtor Transfer - {partner.name}",
                    'debit': 0.0,
                    'credit': self.amount,
                    'company_id': target_company_id,
                    'branch_id': branch_id,
                })
            ]
        }
        move3 = self.env['account.move'].create(entry3_vals)
        move3.write({'partner_id': partner.id})
        move3.action_post()

        # ------------------------------------------------------------------
        # 1. Cancel Move 2 and Move 3 against each other on Outstanding Receipts
        # (Both entries have the same account, same amount; debit & credit cancel each other)
        # ------------------------------------------------------------------
        try:
            m2_out_line = move2.line_ids.filtered(
                lambda l: l.account_id.id == outstanding_receipt_account.id and not l.reconciled
            )
            m3_out_line = move3.line_ids.filtered(
                lambda l: l.account_id.id == outstanding_receipt_account.id and not l.reconciled
            )
            if m2_out_line and m3_out_line:
                (m2_out_line + m3_out_line).reconcile()
        except Exception:
            pass

        # ------------------------------------------------------------------
        # 2. Clear Suspense Partner in Debtors Account
        # Reconcile Move 2's Suspense Debtor line with Customer Payment's Debtor line.
        # NOTE: The Customer Payment's Outstanding Receipts line is NOT touched,
        # so it remains available for Bank Statement Reconciliation.
        # ------------------------------------------------------------------
        try:
            m2_debtor_line = move2.line_ids.filtered(
                lambda l: l.account_id.id == debtors_account.id and not l.reconciled
            )
            if m2_debtor_line:
                counterpart_domain = [
                    ('partner_id', '=', suspense_partner.id),
                    ('account_id', '=', debtors_account.id),
                    ('reconciled', '=', False),
                    ('company_id', '=', target_company_id),
                    ('id', '!=', m2_debtor_line.id),
                    ('credit', '=', self.amount),
                ]

                counterpart = False
                # If transaction_id is present, try matching specific payment first
                if self.transaction_id:
                    counterpart = self.env['account.move.line'].search(counterpart_domain + [
                        '|', '|',
                        ('move_id.ref', '=', self.transaction_id),
                        ('move_id.payment_id.bank_reference', '=', self.transaction_id),
                        ('move_id.payment_id.ref', '=', self.transaction_id),
                    ], limit=1)

                if not counterpart:
                    counterpart = self.env['account.move.line'].search(counterpart_domain, limit=1)

                if counterpart:
                    (m2_debtor_line + counterpart).reconcile()

            # Pairwise reconcile any remaining matching amounts for suspense partner on Debtors ONLY
            unreconciled_lines = self.env['account.move.line'].search([
                ('partner_id', '=', suspense_partner.id),
                ('account_id', '=', debtors_account.id),
                ('reconciled', '=', False),
                ('company_id', '=', target_company_id),
            ])
            debit_lines = list(unreconciled_lines.filtered(lambda l: l.debit > 0))
            credit_lines = list(unreconciled_lines.filtered(lambda l: l.credit > 0))
            for d in debit_lines[:]:
                for c in credit_lines[:]:
                    if float_compare(d.debit, c.credit, precision_rounding=0.01) == 0:
                        (d + c).reconcile()
                        debit_lines.remove(d)
                        credit_lines.remove(c)
                        break
        except Exception:
            pass

        # Link moves to the installment record
        self.suspense_move_id = move2.id
        self.move_id = move3.id
        self.journal_id = journal.id
        self.is_transferred = True
        self.state = 'paid'
        self.transaction_id = self.transaction_id or 'BANK-TRANSFER'

        # Return action to view created transfer entries
        return {
            'name': _('Transfer Journal Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'domain': [('id', 'in', [move2.id, move3.id])],
            'view_mode': 'tree,form',
            'target': 'current',
        }


    def action_confirm_payment(self):
            self.ensure_one()

            if self.state == 'paid' or self.move_id:
                raise UserError(_("Already paid."))

            enrollment = self.enrollment_id
            inst_amt = enrollment.installment_amount
            payment_amount = self.amount

            if inst_amt <= 0:
                raise UserError(_("Invalid installment amount."))

            if payment_amount < inst_amt:
                raise UserError(_("Payment amount must be at least one installment."))

            if payment_amount % inst_amt != 0:
                raise UserError(
                    _("Payment amount must be a multiple of installment amount (%s).")
                    % inst_amt
                )

            expected_total = enrollment.duration * inst_amt
            if expected_total > 0 and (enrollment.total_paid + payment_amount) > expected_total:
                raise UserError(_("Payment limit exceeded. Total allowed amount for this scheme is %s. You cannot pay more than the allowed duration.") % expected_total)

            # --------------------------------------------------
            # OPEN PAYMENT WIZARD
            # --------------------------------------------------
            return {
                'name': _('Pay via Pine Labs (Scheme)'),
                'type': 'ir.actions.act_window',
                'res_model': 'pinelabs.payment.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_amount': payment_amount,
                    'default_scheme_installment_id': self.id,
                },
        }


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    # --------------------------------------------------
    # PAYMENT HOOK (RIGHT PLACE)
    # --------------------------------------------------
    def _create_payments(self):
        payments = super()._create_payments()

        for wizard in self:
            wizard._generate_scheme_installments()

        return payments

    # --------------------------------------------------
    # YOUR SPLIT LOGIC (FIXED)
    # --------------------------------------------------
    def _generate_scheme_installments(self):
        self.ensure_one()

        # If it is paying an invoice (NOT a standalone/outstanding payment), skip scheme allocation
        if self.line_ids.move_id:
            return

        enrollment = self.env['jewellery.scheme.enrollment'].search([
            ('partner_id', '=', self.partner_id.id)
        ], limit=1)

        if not enrollment:
            return

        inst_amt = enrollment.installment_amount
        entered_amt = self.amount

        if not inst_amt or entered_amt <= 0:
            return

        # ------------------------------------------
        # calculate splits
        # ------------------------------------------
        total_lines = int(entered_amt // inst_amt)
        if entered_amt % inst_amt:
            total_lines += 1

        remaining = entered_amt

        # ------------------------------------------
        # IMPORTANT FIX:
        # start from NEXT MONTH (NO BACK DATES)
        # ------------------------------------------
        base_date = self.payment_date or fields.Date.today()

        for i in range(total_lines):

            amount = inst_amt if remaining >= inst_amt else remaining
            remaining -= amount

            installment_date = base_date + relativedelta(months=i + 1)

            self.env['jewellery.scheme.installment'].create({
                'enrollment_id': enrollment.id,
                'amount': amount,
                'date': installment_date,
            })
