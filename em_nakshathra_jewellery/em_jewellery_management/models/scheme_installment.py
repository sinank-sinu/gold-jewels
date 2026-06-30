from odoo import    models, fields, _, api
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

