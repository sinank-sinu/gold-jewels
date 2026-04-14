from odoo import models, fields
from odoo.exceptions import ValidationError

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
        for rec in self:

            if not rec.journal_id:
                raise ValidationError("Please select a Journal")

            if rec.state == 'paid':
                continue

            account = rec.journal_id.default_account_id.id

            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': rec.journal_id.id,
                'line_ids': [
                    (0, 0, {
                        'name': 'Scheme Payment',
                        'debit': rec.amount,
                        'credit': 0.0,
                        'account_id': account
                    }),
                    (0, 0, {
                        'name': 'Scheme Liability',
                        'credit': rec.amount,
                        'debit': 0.0,
                        'account_id': account
                    }),
                ]
            })

            move.action_post()

            rec.move_id = move.id
            rec.state = 'paid'
