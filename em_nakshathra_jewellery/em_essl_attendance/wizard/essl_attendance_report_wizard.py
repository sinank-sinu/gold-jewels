import pytz
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class EsslAttendanceReportWizard(models.TransientModel):
    _name = 'essl.attendance.report.wizard'
    _description = 'Detailed Attendance Report Wizard'

    date_from = fields.Date(
        string='Start Date',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1)
    )
    date_to = fields.Date(
        string='End Date',
        required=True,
        default=fields.Date.today
    )
    department_ids = fields.Many2many(
        'hr.department',
        string='Departments'
    )
    essl_location_ids = fields.Many2many(
        'res.branch',
        string='eSSL Locations'
    )
    filter_present = fields.Boolean(string='Present', default=True)
    filter_absent = fields.Boolean(string='Absent', default=True)
    filter_half_day = fields.Boolean(string='Half Day', default=True)
    filter_on_leave = fields.Boolean(string='On Leave', default=True)

    line_ids = fields.One2many(
        'essl.attendance.report.line',
        'wizard_id',
        string='Report Lines'
    )

    def action_generate_report(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("Start Date cannot be later than End Date."))

        # 1. Clear existing report lines for this wizard
        self.line_ids.unlink()

        # 2. Get timezone
        timezone_name = self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.timezone') or 'Asia/Kolkata'
        try:
            local_tz = pytz.timezone(timezone_name)
        except Exception:
            local_tz = pytz.timezone('Asia/Kolkata')

        # 3. Find active employees in selected departments and locations
        domain = [('active', '=', True)]
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.essl_location_ids:
            domain.append(('essl_location_id', 'in', self.essl_location_ids.ids))
        employees = self.env['hr.employee'].sudo().search(domain)

        if not employees:
            raise UserError(_("No active employees found matching the filters."))

        # 4. Fetch all attendances within range
        start_utc = local_tz.localize(datetime.combine(self.date_from, datetime.min.time())).astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = local_tz.localize(datetime.combine(self.date_to, datetime.max.time())).astimezone(pytz.utc).replace(tzinfo=None)

        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', employees.ids),
            ('check_in', '>=', start_utc),
            ('check_in', '<=', end_utc)
        ])

        # Map to dict: { (employee_id, date): attendance }
        att_by_emp_date = {}
        for att in attendances:
            check_in_local = pytz.utc.localize(att.check_in).astimezone(local_tz)
            local_date = check_in_local.date()
            att_by_emp_date[(att.employee_id.id, local_date)] = att

        # 5. Fetch all approved leaves within range
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', 'in', employees.ids),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', self.date_to),
            ('request_date_to', '>=', self.date_from)
        ])

        # Map to dict: { (employee_id, date): 'leave' / 'half_day' }
        leave_by_emp_date = {}
        for leave in leaves:
            curr_date = max(leave.request_date_from, self.date_from)
            end_date = min(leave.request_date_to, self.date_to)
            while curr_date <= end_date:
                key = (leave.employee_id.id, curr_date)
                if not leave.request_unit_half:
                    leave_by_emp_date[key] = 'leave'
                else:
                    if leave_by_emp_date.get(key) != 'leave':
                        leave_by_emp_date[key] = 'half_day'
                curr_date += timedelta(days=1)

        # 6. Prefetch shift assignments for report lines
        shift_by_employee_id = {}
        employee_ids = employees.ids
        if employee_ids:
            # 1. Direct assignments
            direct_assignments = self.env['essl.shift.assignment'].sudo().search([
                ('employee_id', 'in', employee_ids),
                ('active', '=', True)
            ])
            for a in direct_assignments:
                shift_by_employee_id[a.employee_id.id] = a.shift_id

            # 2. Department-based fallback
            no_direct_emp_ids = [eid for eid in employee_ids if eid not in shift_by_employee_id]
            if no_direct_emp_ids:
                no_direct_emps = self.env['hr.employee'].sudo().browse(no_direct_emp_ids)
                dept_ids = [emp.department_id.id for emp in no_direct_emps if emp.department_id]
                if dept_ids:
                    dept_shifts = self.env['essl.shift'].sudo().search([
                        ('department_ids', 'in', dept_ids)
                    ])
                    shift_by_dept_id = {}
                    for ds in dept_shifts:
                        for dept in ds.department_ids:
                            if dept.id in dept_ids and dept.id not in shift_by_dept_id:
                                shift_by_dept_id[dept.id] = ds
                    for emp in no_direct_emps:
                        if emp.department_id and emp.department_id.id in shift_by_dept_id:
                            shift_by_employee_id[emp.id] = shift_by_dept_id[emp.department_id.id]

        # 7. Generate lines for each date and employee
        lines_vals = []
        curr_date = self.date_from
        while curr_date <= self.date_to:
            for emp in employees:
                att = att_by_emp_date.get((emp.id, curr_date))
                leave_status = leave_by_emp_date.get((emp.id, curr_date))

                status = 'absent'
                worked_hours = 0.0
                check_in = False
                check_out = False

                if att:
                    check_in = att.check_in
                    check_out = att.check_out
                    worked_hours = att.worked_hours

                    if att.half_day_leave or leave_status == 'half_day':
                        status = 'half_day'
                    else:
                        status = 'present'
                else:
                    if leave_status:
                        status = leave_status
                        if status == 'half_day':
                            worked_hours = 4.0
                    else:
                        status = 'absent'

                # Apply status filter checkboxes
                if status == 'present' and not self.filter_present:
                    continue
                if status == 'absent' and not self.filter_absent:
                    continue
                if status == 'half_day' and not self.filter_half_day:
                    continue
                if status == 'leave' and not self.filter_on_leave:
                    continue

                emp_shift = att.essl_shift_id if (att and att.essl_shift_id) else shift_by_employee_id.get(emp.id)

                lines_vals.append({
                    'wizard_id': self.id,
                    'employee_id': emp.id,
                    'department_id': emp.department_id.id or False,
                    'essl_location_id': emp.essl_location_id.id or False,
                    'essl_shift_id': emp_shift.id if emp_shift else False,
                    'date': curr_date,
                    'status': status,
                    'worked_hours': worked_hours,
                    'check_in': check_in,
                    'check_out': check_out,
                })

            curr_date += timedelta(days=1)

        if not lines_vals:
            raise UserError(_("No report data found matching your filters and selection."))

        self.env['essl.attendance.report.line'].sudo().create(lines_vals)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'essl.attendance.report.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_pdf(self):
        self.ensure_one()
        self.action_generate_report()
        return self.env.ref('em_essl_attendance.action_report_essl_attendance').report_action(self)


class EsslAttendanceReportLine(models.TransientModel):
    _name = 'essl.attendance.report.line'
    _description = 'Detailed Attendance Report Line'
    _order = 'date desc, employee_id asc'

    wizard_id = fields.Many2one(
        'essl.attendance.report.wizard',
        string='Wizard',
        ondelete='cascade',
        required=True
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department'
    )
    essl_location_id = fields.Many2one(
        'res.branch',
        string='eSSL Location'
    )
    essl_shift_id = fields.Many2one(
        'essl.shift',
        string='Shift'
    )
    date = fields.Date(
        string='Date',
        required=True
    )
    status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('half_day', 'Half Day'),
        ('leave', 'On Leave')
    ], string='Status', required=True)

    worked_hours = fields.Float(string='Worked Hours')
    check_in = fields.Datetime(string='Check In')
    check_out = fields.Datetime(string='Check Out')
