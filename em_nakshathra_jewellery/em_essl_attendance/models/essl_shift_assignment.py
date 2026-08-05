from odoo import models, fields

class EsslShiftAssignment(models.Model):
    _name = 'essl.shift.assignment'
    _description = 'eSSL Shift Assignment'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    shift_id = fields.Many2one('essl.shift', string='Shift', required=True, ondelete='cascade')
    active = fields.Boolean(string='Active', default=True)

    _sql_constraints = [
        ('employee_unique', 'unique(employee_id)', 'An employee can only be assigned to one shift at a time!')
    ]
