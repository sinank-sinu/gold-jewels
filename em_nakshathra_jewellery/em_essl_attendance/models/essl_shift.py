from odoo import models, fields, api

class EsslShift(models.Model):
    _name = 'essl.shift'
    _description = 'eSSL Shift'

    name = fields.Char(string='Shift Name', required=True)
    start_time = fields.Float(
        string='Start Time', required=True,
        help="Shift start hour (e.g. 9.0 = 09:00)"
    )
    end_time = fields.Float(
        string='End Time', required=True,
        help="Shift end hour (e.g. 17.0 = 17:00). "
             "For an 8-hr day shift starting at 09:00, set to 17.0."
    )
    extra_minutes = fields.Integer(
        string='Grace Minutes (Late Threshold)', default=0,
        help="Minutes after shift start before an employee is marked as half-day late"
    )
    duration_hours = fields.Float(
        string='Shift Duration (hrs)', compute='_compute_duration', store=True,
        help="Calculated shift length in hours (should be 8.0 for a standard shift)"
    )
    department_ids = fields.Many2many(
        'hr.department',
        string='Assigned Departments',
        help="Departments assigned to this shift. Employees in these departments will automatically be assigned this shift."
    )


    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for rec in self:
            if rec.end_time > rec.start_time:
                rec.duration_hours = rec.end_time - rec.start_time
            else:
                # Overnight shift (e.g. 22:00 → 06:00)
                rec.duration_hours = (24.0 - rec.start_time) + rec.end_time

    @api.model_create_multi
    def create(self, vals_list):
        records = super(EsslShift, self).create(vals_list)
        records._auto_assign_employees()
        return records

    def write(self, vals):
        res = super(EsslShift, self).write(vals)
        if 'department_ids' in vals:
            self._auto_assign_employees()
        return res

    def _auto_assign_employees(self):
        for rec in self:
            if rec.department_ids:
                employees = self.env['hr.employee'].sudo().search([
                    ('department_id', 'in', rec.department_ids.ids)
                ])
                for emp in employees:
                    existing = self.env['essl.shift.assignment'].sudo().search([
                        ('employee_id', '=', emp.id)
                    ], limit=1)
                    if existing:
                        existing.write({'shift_id': rec.id, 'active': True})
                    else:
                        self.env['essl.shift.assignment'].sudo().create({
                            'employee_id': emp.id,
                            'shift_id': rec.id,
                            'active': True
                        })

