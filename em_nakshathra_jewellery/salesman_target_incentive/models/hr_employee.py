from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    salesman_target_ids = fields.One2many(
        'salesman.target',
        'employee_id',
        string='Sales Targets',
    )
    target_count = fields.Integer(
        string='Target Count',
        compute='_compute_target_count',
    )

    def _compute_target_count(self):
        for emp in self:
            emp.target_count = len(emp.salesman_target_ids)
