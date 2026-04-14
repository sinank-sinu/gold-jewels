from odoo import api, fields, models, _


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    label_id = fields.Many2one(
        'product.label',
        string="Label",
    )
    purity_id = fields.Many2one('gold.purity', string="Purity")