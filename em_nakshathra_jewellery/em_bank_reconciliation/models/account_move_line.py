from odoo import fields, models

class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    bank_reference = fields.Char(related="payment_id.bank_reference", string="Bank Reference", store=True)
