from odoo import models, fields, api, _

class SalaryAdvance(models.Model):
    _name = 'salary.advance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Advance Salary Request'
    _order = 'date desc, name desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'), tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    date = fields.Date(string='Request Date', required=True, default=fields.Date.context_today, tracking=True)
    amount = fields.Float(string='Advance Amount', required=True, tracking=True)
    reason = fields.Text(string='Reason')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string='Status', default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('salary.advance')
                if seq:
                    vals['name'] = seq
                else:
                    ref_date = fields.Date.from_string(vals.get('date') or fields.Date.today())
                    # fallback unique code
                    vals['name'] = f"ADV/{ref_date.strftime('%Y/%m')}/{fields.Datetime.now().strftime('%M%S')}"
        return super().create(vals_list)

    invoice_id = fields.Many2one('account.move', string='Vendor Bill', readonly=True, copy=False)
    payslip_id = fields.Many2one('hr.payslip', string='Payslip Ref.', readonly=True, copy=False)
    salary_adjustment_line_id = fields.Many2one('salary.adjustment.line', string='Salary Adjustment Line Ref.', readonly=True, copy=False)

    def action_request(self):
        self.write({'state': 'requested'})

    def action_approve(self):
        self.write({'state': 'approved'})

        for rec in self:
            if not rec.payslip_id:
                contract = self.env['hr.contract'].search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', '=', 'open')
                ], limit=1)
                if not contract:
                    contract = self.env['hr.contract'].search([
                        ('employee_id', '=', rec.employee_id.id)
                    ], limit=1)
                
                if contract:
                    import calendar
                    ref_date = rec.date or fields.Date.today()
                    date_from = ref_date.replace(day=1)
                    last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
                    date_to = ref_date.replace(day=last_day)
                    
                    payslip_vals = {
                        'employee_id': rec.employee_id.id,
                        'contract_id': contract.id,
                        'struct_id': contract.struct_id.id if contract.struct_id else False,
                        'date_from': date_from,
                        'date_to': date_to,
                    }
                    payslip = self.env['hr.payslip'].create(payslip_vals)
                    payslip.onchange_employee()
                    payslip.action_compute_sheet()
                    rec.write({'payslip_id': payslip.id})


    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_draft(self):
        self.write({'state': 'draft'})
