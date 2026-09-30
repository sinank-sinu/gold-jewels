from datetime import datetime
import calendar
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SalaryAdjustment(models.Model):
    _name = 'salary.adjustment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Salary Adjustment'
    _order = 'date_start desc, name desc'

    def _default_date_start(self):
        today = fields.Date.context_today(self)
        return today.replace(day=1)

    def _default_date_end(self):
        today = fields.Date.context_today(self)
        last_day = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=last_day)

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'), tracking=True)
    date_start = fields.Date(string='Start Date', required=True, default=_default_date_start, tracking=True)
    date_end = fields.Date(string='End Date', required=True, default=_default_date_end, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company, tracking=True)
    line_ids = fields.One2many('salary.adjustment.line', 'salary_adjustment_id', string='Adjustment Lines', copy=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done')
    ], string='Status', default='draft', tracking=True)
    
    file_name = fields.Char(string='File Name', readonly=True)
    file_data = fields.Binary(string='File Data', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('salary.adjustment')
                if seq:
                    vals['name'] = seq
                else:
                    ref_date = fields.Date.from_string(vals.get('date_start') or fields.Date.today())
                    prefix = f"SA/{ref_date.strftime('%Y/%m')}/"
                    existing = self.search([('name', '=like', f"{prefix}%")], order='id desc', limit=1)
                    if existing and existing.name:
                        try:
                            last_num = int(existing.name.split('/')[-1])
                            vals['name'] = f"{prefix}{last_num + 1:04d}"
                        except Exception:
                            count = self.search_count([('name', '=like', f"{prefix}%")])
                            vals['name'] = f"{prefix}{count + 1:04d}"
                    else:
                        count = self.search_count([('name', '=like', f"{prefix}%")])
                        vals['name'] = f"{prefix}{count + 1:04d}"
        return super().create(vals_list)

    def action_generate_lines(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("You can only generate lines in Draft state."))
        
        # Clear existing lines
        self.line_ids.unlink()

        # Find all active employees in this company
        employees = self.env['hr.employee'].search([
            ('company_id', '=', self.company_id.id),
        ])
        
        lines_to_create = []
        for emp in employees:
            # 1. Fetch Contract & Basic Wage using sudo() to avoid multi-company record rule errors
            contract = self.env['hr.contract'].sudo().search([
                ('employee_id', '=', emp.id),
                ('company_id', '=', self.company_id.id),
                ('state', '=', 'open')
            ], limit=1)
            if not contract:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('company_id', '=', self.company_id.id)
                ], limit=1)
            if not contract:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'open')
                ], limit=1)
            if not contract and emp.sudo().contract_id:
                contract = emp.sudo().contract_id
            if not contract:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', emp.id)
                ], limit=1)
            
            basic_wage = contract.wage if contract else 0.0

            # 2. Fetch Allowances from Contract
            allowance = 0.0
            if contract:
                for f in ('hra', 'da', 'travel_allowance', 'meal_allowance', 'medical_allowance', 'other_allowance'):
                    if hasattr(contract, f):
                        allowance += getattr(contract, f, 0.0) or 0.0

            # 3. Fetch Deductions (Approved Advances + Unpaid Loan Installments in period)
            advances = self.env['salary.advance'].sudo().search([
                ('employee_id', '=', emp.id),
                ('state', '=', 'approved'),
                ('date', '>=', self.date_start),
                ('date', '<=', self.date_end),
                ('payslip_id', '=', False),
                ('salary_adjustment_line_id', '=', False)
            ])
            adv_deduction = sum(advances.mapped('amount'))

            loan_lines = self.env['salary.loan.line'].sudo().search([
                ('employee_id', '=', emp.id),
                ('loan_id.state', '=', 'approved'),
                ('date', '>=', self.date_start),
                ('date', '<=', self.date_end),
                ('paid', '=', False),
                ('payslip_id', '=', False)
            ])
            loan_deduction = sum(loan_lines.mapped('amount'))

            deduction = adv_deduction + loan_deduction
            
            lines_to_create.append({
                'salary_adjustment_id': self.id,
                'employee_id': emp.id,
                'basic_wage': basic_wage,
                'allowance': allowance,
                'deduction': deduction,
            })
        if lines_to_create:
            self.env['salary.adjustment.line'].create(lines_to_create)

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_done(self):
        self.write({'state': 'done'})
        for sheet in self:
            for line in sheet.line_ids:
                advances = self.env['salary.advance'].sudo().search([
                    ('employee_id', '=', line.employee_id.id),
                    ('state', '=', 'approved'),
                    ('date', '>=', sheet.date_start),
                    ('date', '<=', sheet.date_end),
                    ('payslip_id', '=', False),
                    ('salary_adjustment_line_id', '=', False)
                ])
                if advances:
                    advances.write({'salary_adjustment_line_id': line.id})

    def action_draft(self):
        self.write({'state': 'draft'})
        for sheet in self:
            advances = self.env['salary.advance'].sudo().search([
                ('salary_adjustment_line_id', 'in', sheet.line_ids.ids)
            ])
            if advances:
                advances.write({'salary_adjustment_line_id': False})


class SalaryAdjustmentLine(models.Model):
    _name = 'salary.adjustment.line'
    _description = 'Salary Adjustment Line'

    salary_adjustment_id = fields.Many2one('salary.adjustment', string='Salary Adjustment Sheet', ondelete='cascade', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    national_id = fields.Char(string='National ID', compute='_compute_national_id', readonly=True)
    basic_wage = fields.Float(string='Basic Wage', required=True)
    allowance = fields.Float(string='Allowances')
    deduction = fields.Float(string='Deductions')
    net_wage = fields.Float(string='Net Wage', compute='_compute_net_wage', store=True)

    @api.depends('employee_id', 'employee_id.national_id', 'employee_id.identification_id', 'employee_id.passport_id', 'employee_id.pf_uan_no', 'employee_id.esi_no')
    def _compute_national_id(self):
        for line in self:
            emp = line.employee_id.sudo() if line.employee_id else False
            line.national_id = (emp.national_id or emp.identification_id or emp.passport_id or emp.pf_uan_no or emp.esi_no or '') if emp else ''

    @api.depends('basic_wage', 'allowance', 'deduction')
    def _compute_net_wage(self):
        for line in self:
            line.net_wage = (line.basic_wage or 0.0) + (line.allowance or 0.0) - (line.deduction or 0.0)
