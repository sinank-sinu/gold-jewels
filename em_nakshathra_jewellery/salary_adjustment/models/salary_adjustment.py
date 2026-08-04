from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SalaryAdjustment(models.Model):
    _name = 'salary.adjustment'
    _description = 'Salary Adjustment'
    _order = 'date_start desc, name desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    date_start = fields.Date(string='Start Date', required=True, default=fields.Date.context_today)
    date_end = fields.Date(string='End Date', required=True, default=fields.Date.context_today)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    line_ids = fields.One2many('salary.adjustment.line', 'salary_adjustment_id', string='Adjustment Lines', copy=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done')
    ], string='Status', default='draft')
    
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
                    vals['name'] = f"SA/{ref_date.strftime('%Y/%m')}"
        return super().create(vals_list)

    def action_generate_lines(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("You can only generate lines in Draft state."))
        
        # Clear existing lines
        self.line_ids.unlink()

        # Find all active employees in this company
        employees = self.env['hr.employee'].search([('company_id', '=', self.company_id.id)])
        
        lines_to_create = []
        for emp in employees:
            # Find approved, undeducted advance salary requests in this period
            advances = self.env['salary.advance'].search([
                ('employee_id', '=', emp.id),
                ('state', '=', 'approved'),
                ('date', '>=', self.date_start),
                ('date', '<=', self.date_end),
                ('payslip_id', '=', False),
                ('salary_adjustment_line_id', '=', False)
            ])
            deduction = sum(advances.mapped('amount'))
            
            lines_to_create.append({
                'salary_adjustment_id': self.id,
                'employee_id': emp.id,
                'basic_wage': 0.0,
                'allowance': 0.0,
                'deduction': deduction,
            })
        if lines_to_create:
            self.env['salary.adjustment.line'].create(lines_to_create)
        return True

    def action_done(self):
        self.write({'state': 'done'})
        for sheet in self:
            for line in sheet.line_ids:
                advances = self.env['salary.advance'].search([
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
            advances = self.env['salary.advance'].search([
                ('salary_adjustment_line_id', 'in', sheet.line_ids.ids)
            ])
            if advances:
                advances.write({'salary_adjustment_line_id': False})


class SalaryAdjustmentLine(models.Model):
    _name = 'salary.adjustment.line'
    _description = 'Salary Adjustment Line'

    salary_adjustment_id = fields.Many2one('salary.adjustment', string='Salary Adjustment Sheet', ondelete='cascade', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    national_id = fields.Char(related='employee_id.national_id', string='National ID', readonly=True)
    basic_wage = fields.Float(string='Basic Wage', required=True)
    allowance = fields.Float(string='Allowances')
    deduction = fields.Float(string='Deductions')
    net_wage = fields.Float(string='Net Wage', compute='_compute_net_wage', store=True)

    @api.depends('basic_wage', 'allowance', 'deduction')
    def _compute_net_wage(self):
        for line in self:
            line.net_wage = line.basic_wage + line.allowance - line.deduction
