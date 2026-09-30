from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

class SalaryLoan(models.Model):
    _name = 'salary.loan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Loan Request'
    _order = 'date desc, name desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'), tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True
    )
    date = fields.Date(string='Request Date', required=True, default=fields.Date.context_today, tracking=True)
    amount = fields.Float(string='Loan Amount', required=True, tracking=True)
    tenure_months = fields.Integer(string='Tenure (Months)', default=1, required=True, tracking=True)
    monthly_installment = fields.Float(string='Monthly Installment', compute='_compute_monthly_installment', store=True, readonly=False)
    reason = fields.Text(string='Reason')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected')
    ], string='Status', default='draft', tracking=True)

    invoice_id = fields.Many2one('account.move', string='Vendor Bill', readonly=True, copy=False)
    payslip_id = fields.Many2one('hr.payslip', string='Payslip', readonly=True, copy=False)
    line_ids = fields.One2many('salary.loan.line', 'loan_id', string='Installment Lines', copy=False)
    is_manager = fields.Boolean(
        compute='_compute_is_manager',
        default=lambda self: self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
    )

    def _compute_is_manager(self):
        is_mgr = self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
        for rec in self:
            rec.is_manager = is_mgr

    @api.depends('amount', 'tenure_months')
    def _compute_monthly_installment(self):
        for rec in self:
            if rec.tenure_months > 0:
                if rec.monthly_installment > 0:
                    import math
                    expected_tenure = math.ceil(rec.amount / rec.monthly_installment) if rec.monthly_installment else 0
                    if expected_tenure == rec.tenure_months:
                        continue
                rec.monthly_installment = round(rec.amount / rec.tenure_months, 2)
            else:
                rec.monthly_installment = 0.0

    @api.onchange('monthly_installment')
    def _onchange_monthly_installment(self):
        if self.amount > 0 and self.monthly_installment > 0:
            import math
            self.tenure_months = math.ceil(self.amount / self.monthly_installment)

    @api.onchange('tenure_months')
    def _onchange_tenure_months(self):
        if self.amount > 0 and self.tenure_months > 0:
            self.monthly_installment = round(self.amount / self.tenure_months, 2)

    @api.onchange('amount')
    def _onchange_amount(self):
        if self.amount > 0:
            if self.monthly_installment > 0:
                import math
                self.tenure_months = math.ceil(self.amount / self.monthly_installment)
            elif self.tenure_months > 0:
                self.monthly_installment = round(self.amount / self.tenure_months, 2)

    def _generate_installment_lines(self):
        import math
        from dateutil.relativedelta import relativedelta
        for rec in self:
            if rec.amount <= 0:
                continue

            inst_amount = rec.monthly_installment if rec.monthly_installment > 0 else (rec.amount / rec.tenure_months if rec.tenure_months else rec.amount)
            tenure = math.ceil(rec.amount / inst_amount) if inst_amount > 0 else (rec.tenure_months or 1)

            lines = []
            remaining = round(rec.amount, 2)
            ref_date = rec.date or fields.Date.today()
            for i in range(tenure):
                inst_date = ref_date + relativedelta(months=i)
                cur_amount = min(inst_amount, remaining)
                if i == tenure - 1:
                    cur_amount = round(remaining, 2)
                else:
                    cur_amount = round(cur_amount, 2)
                remaining = round(remaining - cur_amount, 2)
                lines.append((0, 0, {
                    'date': inst_date,
                    'amount': cur_amount,
                }))

            rec.line_ids.sudo().unlink()
            rec.sudo().with_context(skip_generate_installments=True).write({'line_ids': lines, 'tenure_months': tenure})

            # If a draft payslip was linked, link it to the first installment line and recompute
            first_line = rec.line_ids.sorted('date')[:1]
            if rec.payslip_id and first_line:
                first_line.sudo().write({'payslip_id': rec.payslip_id.id})
                if rec.payslip_id.state == 'draft':
                    try:
                        rec.payslip_id.sudo().action_compute_sheet()
                    except Exception:
                        pass

    @api.model_create_multi
    def create(self, vals_list):
        import math
        is_manager = self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
        for vals in vals_list:
            if not vals.get('employee_id') and self.env.user.employee_id:
                vals['employee_id'] = self.env.user.employee_id.id
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('salary.loan')
                if seq:
                    vals['name'] = seq
                else:
                    ref_date = fields.Date.from_string(vals.get('date') or fields.Date.today())
                    vals['name'] = f"LOAN/{ref_date.strftime('%Y/%m')}/{fields.Datetime.now().strftime('%M%S')}"

            # Sync tenure and monthly installment
            amt = vals.get('amount', 0.0)
            if amt > 0:
                if vals.get('monthly_installment', 0.0) > 0:
                    vals['tenure_months'] = math.ceil(amt / vals['monthly_installment'])
                elif vals.get('tenure_months', 0) > 0:
                    vals['monthly_installment'] = round(amt / vals['tenure_months'], 2)

            # Standard users can only create in draft status
            if not is_manager:
                if vals.get('state') and vals.get('state') != 'draft':
                    raise UserError(_("Users can only create Loan requests in Draft state."))
                if vals.get('is_approved'):
                    raise UserError(_("You are not allowed to approve Loan requests."))
                if self.env.user.employee_id and vals.get('employee_id') and vals['employee_id'] != self.env.user.employee_id.id:
                    raise UserError(_("You can only create Loan requests for yourself."))
        return super().create(vals_list)

    def write(self, vals):
        import math
        is_manager = self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
        if not is_manager:
            for rec in self:
                allowed_keys = {'message_follower_ids', 'activity_ids', 'message_ids'}
                if vals.get('state') == 'draft' and rec.state in ('requested', 'rejected'):
                    allowed_keys.add('state')
                if rec.state != 'draft' and set(vals.keys()) - allowed_keys:
                    raise UserError(_("You cannot modify a Loan request that is not in draft status."))
                if 'state' in vals and vals['state'] not in ('draft', 'requested'):
                    raise UserError(_("You are not allowed to change the status to %s.") % vals['state'])
                if vals.get('is_approved'):
                    raise UserError(_("You are not allowed to approve Loan requests."))
                if self.env.user.employee_id and vals.get('employee_id') and vals['employee_id'] != self.env.user.employee_id.id:
                    raise UserError(_("You can only create Loan requests for yourself."))

        res = super().write(vals)

        # Regenerate or update installment lines if financial parameters change
        if not self.env.context.get('skip_generate_installments'):
            if any(f in vals for f in ('monthly_installment', 'amount', 'tenure_months')):
                for rec in self:
                    if rec.state == 'approved' and not any(l.paid for l in rec.line_ids):
                        rec._generate_installment_lines()
                    elif rec.state == 'approved' and 'monthly_installment' in vals:
                        unpaid_lines = rec.line_ids.filtered(lambda l: not l.paid)
                        if unpaid_lines:
                            unpaid_lines.write({'amount': vals['monthly_installment']})
                        if rec.payslip_id and rec.payslip_id.state == 'draft':
                            rec.payslip_id.sudo().action_compute_sheet()
        return res

    def action_request(self):
        import math
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft loan requests can be submitted."))
            contract = rec.employee_id.sudo().contract_id
            if not contract:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', '=', 'open')
                ], limit=1)
            if not contract:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id)
                ], limit=1)
            if not contract:
                raise ValidationError(_("Define a contract for the employee"))

            # Ensure tenure and monthly installment are synced before request
            if rec.amount > 0:
                if rec.monthly_installment > 0:
                    tenure = math.ceil(rec.amount / rec.monthly_installment)
                    if rec.tenure_months != tenure:
                        rec.write({'tenure_months': tenure})
                elif rec.tenure_months > 0:
                    rec.write({'monthly_installment': round(rec.amount / rec.tenure_months, 2)})

            if rec.monthly_installment >= contract.wage:
                raise ValidationError(_("The monthly installment amount must be less than the employee's monthly salary."))
        self.write({'state': 'requested'})

    def action_approve(self):
        from dateutil.relativedelta import relativedelta
        
        if not self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') and not self.env.is_superuser():
            raise UserError(_("Only a Salary Adjustment Manager or Administrator can approve Loan requests."))
        
        for rec in self:
            # Experience Validation
            if not rec.employee_id.joining_date:
                raise ValidationError(_("You should have a minimum of 6 months of experience in this company."))
            
            today = fields.Date.today()
            diff = relativedelta(today, rec.employee_id.joining_date)
            total_months = diff.years * 12 + diff.months
            
            if total_months < 6:
                raise ValidationError(_("You should have a minimum of 6 months of experience in this company."))

            # 30% Salary Installment Validation
            installment = rec.monthly_installment or (rec.amount / rec.tenure_months if rec.tenure_months else 0.0)
            contract = rec.employee_id.sudo().contract_id
            if not contract:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', '=', 'open')
                ], limit=1)
            if not contract:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id)
                ], limit=1)

            if contract and contract.wage:
                if round(installment, 2) > round(contract.wage * 0.3, 2):
                    raise ValidationError(_("IF THE MONTHLY INSTALLMENT EXCEEDS 30% OF THE SALARY.<br/><span style='color: red;'>So please set the tenure period.</span>"))

            # 2. Create Installment Lines
            rec._generate_installment_lines()

            # 3. Create Vendor Bill
            if not rec.invoice_id:
                partner = False
                if rec.employee_id.user_partner_id and (not rec.employee_id.user_partner_id.company_id or rec.employee_id.user_partner_id.company_id == rec.company_id):
                    partner = rec.employee_id.user_partner_id
                
                if not partner and rec.employee_id.work_contact_id and rec.employee_id.work_contact_id != rec.company_id.partner_id and (not rec.employee_id.work_contact_id.company_id or rec.employee_id.work_contact_id.company_id == rec.company_id):
                    partner = rec.employee_id.work_contact_id

                if not partner and rec.employee_id.address_id and rec.employee_id.address_id != rec.company_id.partner_id and (not rec.employee_id.address_id.company_id or rec.employee_id.address_id.company_id == rec.company_id):
                    partner = rec.employee_id.address_id

                if not partner:
                    partner = self.env['res.partner'].sudo().search([
                        ('name', '=', rec.employee_id.name),
                        ('is_company', '=', False),
                        '|', ('company_id', '=', False), ('company_id', '=', rec.company_id.id)
                    ], limit=1)

                if not partner:
                    partner = self.env['res.partner'].sudo().create({
                        'name': rec.employee_id.name,
                        'is_company': False,
                        'company_id': rec.company_id.id,
                    })

                Account = self.env['account.account']
                account = Account.sudo().search([
                    ('company_id', '=', rec.company_id.id),
                    '|', ('name', 'ilike', 'salary'), ('name', 'ilike', 'advance'),
                    ('account_type', 'in', ('expense', 'asset_current', 'liability_current'))
                ], limit=1)
                if not account:
                    account = Account.sudo().search([
                        ('account_type', '=', 'expense'),
                        ('code', '=', '210100'),
                        ('company_id', '=', rec.company_id.id)
                    ], limit=1)
                if not account:
                    account = Account.sudo().search([
                        ('account_type', '=', 'expense'),
                        ('company_id', '=', rec.company_id.id)
                    ], limit=1)
                if not account:
                    account = Account.sudo().search([('company_id', '=', rec.company_id.id)], limit=1)

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
                        'tax_ids': False,
                    })],
                }

                if 'is_approved' in self.env['account.move']._fields:
                    move_vals['is_approved'] = True

                if 'branch_id' in self.env['account.move']._fields:
                    branch = (account and getattr(account, 'branch_id', False)) or getattr(rec.employee_id, 'branch_id', False) or (rec.employee_id.user_id and rec.employee_id.user_id.branch_id) or self.env.user.branch_id
                    if branch:
                        move_vals['branch_id'] = branch.id

                if rec.reason:
                    move_vals['ref'] = rec.reason[:200]

                bill = self.env['account.move'].sudo().create(move_vals)
                rec.sudo().write({'invoice_id': bill.id})

            # 4. Automatically create or update the payslip for the first installment month
            first_line = rec.line_ids.sorted('date')[:1]
            if first_line:
                ref_date = first_line.date or rec.date or fields.Date.today()
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', '=', 'open')
                ], limit=1)
                if not contract:
                    contract = self.env['hr.contract'].sudo().search([
                        ('employee_id', '=', rec.employee_id.id)
                    ], limit=1)

                if contract:
                    import calendar
                    date_from = ref_date.replace(day=1)
                    last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
                    date_to = ref_date.replace(day=last_day)

                    payslip = self.env['hr.payslip'].sudo().search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('date_from', '<=', ref_date),
                        ('date_to', '>=', ref_date),
                        ('state', 'not in', ('done', 'cancel'))
                    ], limit=1)

                    if not payslip:
                        payslip = self.env['hr.payslip'].sudo().create({
                            'employee_id': rec.employee_id.id,
                            'contract_id': contract.id,
                            'struct_id': contract.struct_id.id if contract.struct_id else False,
                            'date_from': date_from,
                            'date_to': date_to,
                        })
                        payslip.onchange_employee()

                    first_line.sudo().write({'payslip_id': payslip.id})
                    rec.sudo().write({'payslip_id': payslip.id})
                    payslip.sudo().action_compute_sheet()

        self.write({'state': 'approved'})

    def action_close(self):
        if not self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') and not self.env.is_superuser():
            raise UserError(_("Only a Salary Adjustment Manager or Administrator can close Loan requests."))
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Only approved loan requests can be closed."))
        self.write({'state': 'closed'})

    def action_reject(self):
        if not self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') and not self.env.is_superuser():
            raise UserError(_("Only a Salary Adjustment Manager or Administrator can reject Loan requests."))
        self.write({'state': 'rejected'})

    def action_draft(self):
        is_manager = self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
        for rec in self:
            if not is_manager:
                if rec.create_uid != self.env.user:
                    raise UserError(_("You can only reset your own Loan requests to draft."))
                if rec.state not in ('requested', 'rejected'):
                    raise UserError(_("You can only reset Loan requests that are in Requested or Rejected status."))
        self.write({'state': 'draft'})
        for rec in self:
            if rec.payslip_id and rec.payslip_id.state == 'draft':
                p = rec.payslip_id.sudo()
                rec.write({'payslip_id': False})
                try:
                    p.action_compute_sheet()
                except Exception:
                    pass
            rec.line_ids.sudo().unlink()


class SalaryLoanLine(models.Model):
    _name = 'salary.loan.line'
    _description = 'Salary Loan Installment Line'
    _order = 'date'

    loan_id = fields.Many2one('salary.loan', string='Loan Ref', ondelete='cascade', required=True)
    employee_id = fields.Many2one('hr.employee', related='loan_id.employee_id', string='Employee', store=True)
    is_manager = fields.Boolean(related='loan_id.is_manager')
    date = fields.Date(string='Installment Date', required=True)
    amount = fields.Float(string='Installment Amount', required=True)
    payslip_id = fields.Many2one('hr.payslip', string='Payslip Ref.', readonly=True, copy=False)
    paid = fields.Boolean(string='Paid', default=False)
    paid_status = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid')
    ], string='Paid Indicator', compute='_compute_paid_status', store=True)

    @api.depends('paid')
    def _compute_paid_status(self):
        for line in self:
            line.paid_status = 'paid' if line.paid else 'unpaid'

    def write(self, vals):
        res = super(SalaryLoanLine, self).write(vals)
        if 'paid' in vals:
            for line in self:
                loan = line.loan_id
                if loan and loan.state in ('approved', 'closed') and loan.line_ids:
                    if all(l.paid for l in loan.line_ids):
                        if loan.state != 'closed':
                            loan.write({'state': 'closed'})
                    else:
                        if loan.state == 'closed' and not vals.get('paid'):
                            loan.write({'state': 'approved'})
        if 'amount' in vals:
            for line in self:
                if line.payslip_id and line.payslip_id.state == 'draft':
                    line.payslip_id.action_compute_sheet()
        return res
