from odoo import models, fields

class ResBranch(models.Model):
    _inherit = 'res.branch'

    cutpiece_location_id = fields.Many2one('stock.location', string="Cutpiece Location", domain="[('usage', '=', 'internal')]")
