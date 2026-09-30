from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class SalaryAdvance(models.Model):
    _name = 'salary.advance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Advance Salary Request'
    _order = 'date desc, name desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'), tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True
    )
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

    invoice_id = fields.Many2one('account.move', string='Vendor Bill', readonly=True, copy=False)
    payslip_id = fields.Many2one('hr.payslip', string='Payslip Ref.', readonly=True, copy=False)
    salary_adjustment_line_id = fields.Many2one('salary.adjustment.line', string='Salary Adjustment Line Ref.', readonly=True, copy=False)
    is_manager = fields.Boolean(
        compute='_compute_is_manager',
        default=lambda self: self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
    )

    def _compute_is_manager(self):
        is_mgr = self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
        for rec in self:
            rec.is_manager = is_mgr

    def _get_employee_contract(self):
        self.ensure_one()
        if not self.employee_id:
            return False
        contract = self.employee_id.sudo().contract_id
        if not contract:
            contract = self.env['hr.contract'].sudo().search([
                ('employee_id', '=', self.employee_id.id),
                ('state', '=', 'open')
            ], limit=1)
        if not contract:
            contract = self.env['hr.contract'].sudo().search([
                ('employee_id', '=', self.employee_id.id)
            ], limit=1)
        return contract

    @api.constrains('amount', 'employee_id')
    def _check_advance_amount(self):
        for rec in self:
            if rec.state in ('draft', 'requested') and rec.employee_id:
                contract = rec._get_employee_contract()
                if contract and contract.wage and rec.amount > contract.wage:
                    raise ValidationError(_("Advance amount greater than salary amount."))

    @api.onchange('amount', 'employee_id')
    def _onchange_amount(self):
        if self.employee_id and self.amount:
            contract = self._get_employee_contract()
            if contract and contract.wage and self.amount > contract.wage:
                return {
                    'warning': {
                        'title': _("Validation Error"),
                        'message': _("Advance amount greater than salary amount."),
                    }
                }

    @api.model_create_multi
    def create(self, vals_list):
        is_manager = self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
        for vals in vals_list:
            if not vals.get('employee_id') and self.env.user.employee_id:
                vals['employee_id'] = self.env.user.employee_id.id
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('salary.advance')
                if seq:
                    vals['name'] = seq
                else:
                    ref_date = fields.Date.from_string(vals.get('date') or fields.Date.today())
                    vals['name'] = f"ADV/{ref_date.strftime('%Y/%m')}/{fields.Datetime.now().strftime('%M%S')}"
            # Standard users can only create in draft status
            if not is_manager:
                if vals.get('state') and vals.get('state') != 'draft':
                    raise UserError(_("Users can only create Advance Salary requests in Draft state."))
                if vals.get('is_approved'):
                    raise UserError(_("You are not allowed to approve Advance Salary requests."))
                if self.env.user.employee_id and vals.get('employee_id') and vals['employee_id'] != self.env.user.employee_id.id:
                    raise UserError(_("You can only create Advance Salary requests for yourself."))
        records = super().create(vals_list)
        for rec in records:
            if rec.state == 'approved':
                rec._create_vendor_bill()
        return records

    def write(self, vals):
        is_manager = self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
        if not is_manager:
            for rec in self:
                # Disallow modifying non-draft requests unless it's just chatter / activity updates
                # or resetting to draft from requested/rejected
                allowed_keys = {'message_follower_ids', 'activity_ids', 'message_ids'}
                if vals.get('state') == 'draft' and rec.state in ('requested', 'rejected'):
                    allowed_keys.add('state')
                if rec.state != 'draft' and set(vals.keys()) - allowed_keys:
                    raise UserError(_("You cannot modify an Advance Salary request that is not in draft status."))
                # Disallow non-managers from directly setting state to approved/rejected or is_approved
                if 'state' in vals and vals['state'] not in ('draft', 'requested'):
                    raise UserError(_("You are not allowed to change the status to %s.") % vals['state'])
                if vals.get('is_approved'):
                    raise UserError(_("You are not allowed to approve Advance Salary requests."))
                if self.env.user.employee_id and vals.get('employee_id') and vals['employee_id'] != self.env.user.employee_id.id:
                    raise UserError(_("You can only create Advance Salary requests for yourself."))
        res = super().write(vals)
        if vals.get('state') == 'approved':
            self._create_vendor_bill()
        return res

    def action_request(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft advance salary requests can be submitted."))
            contract = rec._get_employee_contract()
            if not contract or not contract.wage:
                raise ValidationError(_("Define a contract for the employee"))
            if rec.amount > contract.wage:
                raise ValidationError(_("Advance amount greater than salary amount."))
        self.write({'state': 'requested'})

    def _create_vendor_bill(self):
        for rec in self:
            if not rec.invoice_id and rec.amount > 0:
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
                        'name': f"Salary Advance for {rec.employee_id.name} (Ref: {rec.name})",
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

    def action_approve(self):
        if not self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') and not self.env.is_superuser():
            raise UserError(_("Only a Salary Adjustment Manager or Administrator can approve Advance Salary requests."))
        for rec in self:
            contract = rec._get_employee_contract()
            if not contract or not contract.wage:
                raise ValidationError(_("Define a contract for the employee"))
            if rec.amount > contract.wage:
                raise ValidationError(_("Advance amount greater than salary amount."))
        self.write({'state': 'approved'})
        self._create_vendor_bill()

        for rec in self:
            if not rec.payslip_id:
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
                    payslip = self.env['hr.payslip'].sudo().create(payslip_vals)
                    payslip.sudo().onchange_employee()
                    payslip.sudo().action_compute_sheet()
                    rec.sudo().write({'payslip_id': payslip.id})

    def action_reject(self):
        if not self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') and not self.env.is_superuser():
            raise UserError(_("Only a Salary Adjustment Manager or Administrator can reject Advance Salary requests."))
        self.write({'state': 'rejected'})

    def action_draft(self):
        is_manager = self.env.user.has_group('salary_adjustment.group_salary_adjustment_manager') or self.env.user.has_group('base.group_system') or self.env.is_superuser()
        for rec in self:
            if not is_manager:
                if rec.create_uid != self.env.user:
                    raise UserError(_("You can only reset your own Advance Salary requests to draft."))
                if rec.state not in ('requested', 'rejected'):
                    raise UserError(_("You can only reset Advance Salary requests that are in Requested or Rejected status."))
        self.write({'state': 'draft'})
        for rec in self:
            if rec.payslip_id and rec.payslip_id.state == 'draft':
                p = rec.payslip_id.sudo()
                rec.write({'payslip_id': False})
                try:
                    p.action_compute_sheet()
                except Exception:
                    pass
