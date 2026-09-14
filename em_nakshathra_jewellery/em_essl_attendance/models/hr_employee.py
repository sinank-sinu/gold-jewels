from odoo import models, fields, api

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    essl_emp_code = fields.Char(string='eSSL Employee Code', tracking=True)
    essl_location_id = fields.Many2one('res.branch', string='eSSL Location', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        employees = super(HrEmployee, self).create(vals_list)
        for emp in employees:
            if emp.department_id:
                emp._auto_assign_shift()
        return employees

    def write(self, vals):
        res = super(HrEmployee, self).write(vals)
        if 'department_id' in vals:
            for emp in self:
                emp._auto_assign_shift()
        return res

    def _auto_assign_shift(self):
        self.ensure_one()
        if self.department_id:
            shift = self.env['essl.shift'].sudo().search([
                ('department_ids', 'in', self.department_id.id)
            ], limit=1)
            if shift:
                existing = self.env['essl.shift.assignment'].sudo().search([
                    ('employee_id', '=', self.id)
                ], limit=1)
                if existing:
                    existing.write({'shift_id': shift.id, 'active': True})
                else:
                    self.env['essl.shift.assignment'].sudo().create({
                        'employee_id': self.id,
                        'shift_id': shift.id,
                        'active': True
                    })

class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    essl_emp_code = fields.Char(string='eSSL Employee Code', readonly=True)
    essl_location_id = fields.Many2one('res.branch', string='eSSL Location', readonly=True)
