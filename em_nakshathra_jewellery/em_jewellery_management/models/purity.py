from odoo import models, fields

class GoldPurity(models.Model):
    _name = 'gold.purity'
    _description = 'Gold Purity'

    name = fields.Char(required=True)        # 22K, 18K
    percentage = fields.Float(string="Purity %")
    is_diamond_og = fields.Boolean(
        string="Is Diamond OG",
        help="Check this if this purity is for Diamond Old Gold. Items with this purity will be routed to the Diamond OG location."
    )
    active = fields.Boolean(default=True)
