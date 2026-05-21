from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    label_location_id = fields.Many2one(
        'stock.location',
        string='Label Location'
    )


    