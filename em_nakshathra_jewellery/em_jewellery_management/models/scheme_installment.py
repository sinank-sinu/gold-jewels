from odoo import models, fields, _, api
from odoo.exceptions import UserError, ValidationError

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
        """ 
        Overriding to open the Pine Labs payment gateway instead of 
        instantly generating a manual local journal entry.
        """
        for rec in self:
            if rec.state == 'paid' or rec.move_id:
                raise UserError(_("This installment has already been paid."))

            if rec.amount <= 0:
                raise UserError(_("Installment amount must be greater than zero."))

            # Open the Pine Labs payment wizard, passing the current installment details in context
            return {
                'name': _('Pay via Pine Labs (Scheme)'),
                'type': 'ir.actions.act_window',
                'res_model': 'pinelabs.payment.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_amount': rec.amount,
                    'default_scheme_installment_id': rec.id, # Map back to this line when transaction finishes
                },
            }

    # def action_confirm_payment(self):
    #     for rec in self:

    #         if not rec.journal_id:
    #             raise ValidationError("Please select a Journal")

    #         if rec.state == 'paid':
    #             continue

    #         # account = rec.journal_id.default_account_id.id
    #         debtors_account = self.env['account.account'].search([
    #             ('code', '=', '100400')
    #         ], limit=1)

    #         if not debtors_account:
    #             raise ValidationError("Debtors account 100400 not found")

    #         # Liability Account
    #         liability_account = rec.journal_id.default_account_id

    #         move = self.env['account.move'].create({
    #             'move_type': 'entry',
    #             'journal_id': rec.journal_id.id,
    #             'line_ids': [
    #                 (0, 0, {
    #                     'name': 'Scheme Liability',
    #                     'partner_id': rec.enrollment_id.partner_id.id,
    #                     'credit': 0.0,
    #                     'debit': rec.amount,
    #                     'account_id': liability_account.id
    #                 }),
    #                 (0, 0, {
    #                     'name': 'Scheme Payment',
    #                     'partner_id': rec.enrollment_id.partner_id.id,
    #                     'debit': 0.0,
    #                     'credit': rec.amount,
    #                     'account_id': debtors_account.id
    #                 })
                  
                    
    #             ]
    #         })

    #         move.action_post()

    #         rec.move_id = move.id
    #         rec.state = 'paid'
