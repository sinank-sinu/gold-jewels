from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    essl_emp_code = fields.Char(string='eSSL Employee Code', tracking=True)
