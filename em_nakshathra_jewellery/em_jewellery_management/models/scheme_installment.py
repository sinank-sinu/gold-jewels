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
    move_id = fields.Many2one('account.move')
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
            raise UserError(_("Transfer limit exceeded. Total allowed amount for this scheme is %s. You cannot transfer more than the allowed duration.") % expected_total)
            
        # 1. Find Suspense Journal
        journal = self.env['account.journal'].search(['|', ('name', 'ilike', 'suspense'), ('name', 'ilike', 'suspence')], limit=1)
        if not journal:
            raise UserError(_("CRITICAL ERROR: No journal containing the name 'suspense' or 'suspence' was found in your accounting settings!"))
            
        # 2. Find Accounts
        suspense_account = self.env['account.account'].search([('code', '=', '100202')], limit=1)
        if not suspense_account:
            suspense_account = self.env['account.account'].search([('name', 'ilike', 'Bank Suspense Account')], limit=1)
            
        if not suspense_account:
            raise UserError(_("Bank Suspense Account (100202) not found in the chart of accounts."))
            
        debtors_account = self.env['account.account'].search([('code', '=', '100400')], limit=1)
        if not debtors_account:
            # Fallback to partner's receivable if '100400 Debtors' not found by code
            debtors_account = partner.property_account_receivable_id
            
        if not debtors_account:
            raise UserError(_("Debtors Account (100400) not found."))
            
        # 3. Create Draft Journal Entry
        move_vals = {
            'journal_id': journal.id,
            'date': fields.Date.today(),
            'ref': f"Scheme Transfer - {self.enrollment_id.name or partner.name}",
            'branch_id': self.enrollment_id.branch_id.id if hasattr(self.env['account.move'], 'branch_id') and self.enrollment_id.branch_id else False,
            'partner_id': partner.id,
            'line_ids': [
                (0, 0, {
                    'account_id': suspense_account.id,
                    'partner_id': partner.id,
                    'name': f"Transfer from Suspense - {partner.name}",
                    'debit': self.amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': debtors_account.id,
                    'partner_id': partner.id,
                    'name': f"Transfer to Debtors - {partner.name}",
                    'debit': 0.0,
                    'credit': self.amount,
                })
            ]
        }
        
        move = self.env['account.move'].create(move_vals)
        move.write({'partner_id': partner.id})
        
        # Link the created transfer move to the installment so it shows in the 'Move' column
        self.move_id = move.id
        self.journal_id = journal.id
        self.is_transferred = True
        self.state = 'paid'
        self.transaction_id = 'BANK-TRANSFER'
        
        # 4. Open the created move in a new window for the user to review
        return {
            'name': _('Draft Entry (Transfer)'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
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

