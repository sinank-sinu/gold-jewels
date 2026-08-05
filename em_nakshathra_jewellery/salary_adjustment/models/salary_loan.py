from odoo import models, fields, api, _

class SalaryLoan(models.Model):
    _name = 'salary.loan'
    _description = 'Loan Request'
    _order = 'date desc, name desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    date = fields.Date(string='Request Date', required=True, default=fields.Date.context_today)
    amount = fields.Float(string='Loan Amount', required=True)
    tenure_months = fields.Integer(string='Tenure (Months)', default=1, required=True)
    monthly_installment = fields.Float(string='Monthly Installment', compute='_compute_monthly_installment', store=True)
    reason = fields.Text(string='Reason')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected')
    ], string='Status', default='draft')

    invoice_id = fields.Many2one('account.move', string='Vendor Bill', readonly=True, copy=False)
    line_ids = fields.One2many('salary.loan.line', 'loan_id', string='Installment Lines', copy=False)

    @api.depends('amount', 'tenure_months')
    def _compute_monthly_installment(self):
        for rec in self:
            if rec.tenure_months > 0:
                rec.monthly_installment = rec.amount / rec.tenure_months
            else:
                rec.monthly_installment = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('salary.loan')
                if seq:
                    vals['name'] = seq
                else:
                    ref_date = fields.Date.from_string(vals.get('date') or fields.Date.today())
                    # fallback unique code
                    vals['name'] = f"LOAN/{ref_date.strftime('%Y/%m')}/{fields.Datetime.now().strftime('%M%S')}"
        return super().create(vals_list)

    def action_request(self):
        from odoo.exceptions import ValidationError
        for rec in self:
            contract = rec.employee_id.contract_id
            if not contract:
                raise ValidationError(_("Define a contract for the employee"))
            if rec.monthly_installment >= contract.wage:
                raise ValidationError(_("The monthly installment amount must be less than the employee's monthly salary."))
        self.write({'state': 'requested'})

    def action_approve(self):
        from dateutil.relativedelta import relativedelta
        from odoo.exceptions import ValidationError
        
        for rec in self:
            # Experience Validation
            if not rec.employee_id.joining_date:
                raise ValidationError(_("You should have a minimum of 6 months of experience in this company."))
            
            today = fields.Date.today()
            diff = relativedelta(today, rec.employee_id.joining_date)
            total_months = diff.years * 12 + diff.months
            
            if total_months < 12:
                raise ValidationError(_("You should have a minimum of 12 months of experience in this company."))
            
            pass

            # 2. Create Installment Lines
            if rec.tenure_months > 0:
                # Clear existing lines to prevent duplicates
                rec.line_ids.unlink()
                
                installment_amount = rec.amount / rec.tenure_months
                lines = []
                for i in range(rec.tenure_months):
                    inst_date = rec.date + relativedelta(months=i)
                    lines.append((0, 0, {
                        'date': inst_date,
                        'amount': installment_amount,
                    }))
                rec.write({'line_ids': lines})

            # 3. Create Vendor Bill
            if not rec.invoice_id:
                partner = False
                if rec.employee_id.user_partner_id:
                    partner = rec.employee_id.user_partner_id
                
                if not partner:
                    partner = self.env['res.partner'].search([
                        ('name', '=', rec.employee_id.name),
                        ('is_company', '=', False)
                    ], limit=1)
                
                if not partner and rec.employee_id.work_contact_id and rec.employee_id.work_contact_id != rec.company_id.partner_id:
                    partner = rec.employee_id.work_contact_id
                    
                if not partner and rec.employee_id.address_id and rec.employee_id.address_id != rec.company_id.partner_id:
                    partner = rec.employee_id.address_id
                
                if not partner:
                    partner = self.env['res.partner'].create({
                        'name': rec.employee_id.name,
                        'company_type': 'person',
                    })
                
                Account = self.env['account.account']
                account = Account.search([
                    ('account_type', '=', 'expense'),
                    ('code', '=', '210100'),
                    ('company_id', '=', rec.company_id.id)
                ], limit=1)
                if not account:
                    account = Account.search([
                        ('account_type', '=', 'expense'),
                        ('company_id', '=', rec.company_id.id)
                    ], limit=1)
                if not account:
                    account = Account.search([('company_id', '=', rec.company_id.id)], limit=1)
                
                move_vals = {
                    'move_type': 'in_invoice',
                    'partner_id': partner.id,
                    'invoice_date': rec.date or fields.Date.today(),
                    'date': rec.date or fields.Date.today(),
                    'company_id': rec.company_id.id,
                    'invoice_line_ids': [(0, 0, {
                        'name': f"Salary Loan for {rec.employee_id.name} (Ref: {rec.name})",
                        'quantity': 1.0,
                        'price_unit': rec.amount,
                        'account_id': account.id,
                    })],
                }
                
                if 'is_approved' in self.env['account.move']._fields:
                    move_vals['is_approved'] = True
                    
                if rec.reason:
                    move_vals['ref'] = rec.reason[:200]
                    
                bill = self.env['account.move'].create(move_vals)
                rec.write({'invoice_id': bill.id})

        self.write({'state': 'approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_draft(self):
        self.write({'state': 'draft'})
        for rec in self:
            # Delete installment lines when resetting to draft
            rec.line_ids.unlink()


class SalaryLoanLine(models.Model):
    _name = 'salary.loan.line'
    _description = 'Salary Loan Installment Line'
    _order = 'date'

    loan_id = fields.Many2one('salary.loan', string='Loan Ref', ondelete='cascade', required=True)
    employee_id = fields.Many2one('hr.employee', related='loan_id.employee_id', string='Employee', store=True)
    date = fields.Date(string='Installment Date', required=True)
    amount = fields.Float(string='Installment Amount', required=True)
    payslip_id = fields.Many2one('hr.payslip', string='Payslip Ref.', readonly=True, copy=False)
    paid = fields.Boolean(string='Paid', default=False)

    def write(self, vals):
        res = super(SalaryLoanLine, self).write(vals)
        if 'paid' in vals:
            for line in self:
                loan = line.loan_id
                if loan and loan.state == 'approved' and all(l.paid for l in loan.line_ids):
                    loan.write({'state': 'closed'})
        return res
