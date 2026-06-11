from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    label_location_id = fields.Many2one(
        'stock.location',
        string='Label Location'
    )



class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    # Mirroring the field onto the public profile completely bypasses the Access Error
    label_location_id = fields.Many2one(
        'stock.location',
        string='Label Location'
    )