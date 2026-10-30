# -*- coding: utf-8 -*-
#############################################################################
#    A part of Open HRMS Project <https://www.openhrms.com>
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EmployeeTransfer(models.Model):
    """Model for managing Employee Transfers."""
    _name = 'employee.transfer'
    _description = 'Employee Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "id desc"

    def _find_current_user_employee(self):
        """Find the employee record linked to current user across company boundaries."""
        emp = self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.env.uid),
            ('active', '=', True),
        ], limit=1)
        if not emp:
            emp = self.env['hr.employee'].sudo().search([
                ('work_contact_id', '=', self.env.user.partner_id.id),
                ('active', '=', True),
            ], limit=1)
        if not emp:
            emp = self.env['hr.employee'].sudo().search([
                ('name', '=ilike', self.env.user.name),
                ('active', '=', True),
            ], limit=1)
        return emp

    def _is_transfer_admin(self):
        """Check whether current user is an administrator who can manage all transfers."""
        user = self.env.user
        return bool(
            user.has_group('hr_employee_transfer.group_employee_transfer_admin')
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
            or self.env.is_admin()
        )

    def _default_responsible_employee_id(self):
        """Get the default employee for the responsible_employee_id field."""
        emp = self._find_current_user_employee()
        return emp.id if emp else False

    def _default_employee_id(self):
        """Default to the employee record linked to the logged-in user."""
        emp = self._find_current_user_employee()
        return emp.id if emp else False

    @api.model
    def default_get(self, fields_list):
        """Pre-populate employee, company, branch and responsible on new record creation."""
        res = super(EmployeeTransfer, self).default_get(fields_list)
        is_admin = self._is_transfer_admin()
        res['is_hr_manager'] = is_admin

        emp = False
        emp_id = res.get('employee_id')
        if emp_id:
            emp = self.env['hr.employee'].sudo().browse(emp_id)
        else:
            emp = self._find_current_user_employee()
            if emp:
                res['employee_id'] = emp.id

        if emp:
            if emp.company_id and emp.company_id not in self.env.user.company_ids:
                self.env.user.sudo().write({'company_ids': [(4, emp.company_id.id)]})

            if emp.company_id:
                res['company_id'] = emp.company_id.id
            if 'branch_id' in fields_list:
                res['branch_id'] = (
                    emp.branch_id.id
                    or (emp.user_id and emp.user_id.branch_id and emp.user_id.branch_id.id)
                    or False
                )
            if 'responsible_employee_id' in fields_list and not res.get('responsible_employee_id'):
                user_emp = self._find_current_user_employee()
                res['responsible_employee_id'] = user_emp.id if user_emp else emp.id

        source_comp_id = res.get('company_id') or (emp and emp.company_id and emp.company_id.id)
        target_comp_id = res.get('transfer_company_id')
        res['is_same_company'] = bool(
            source_comp_id and target_comp_id
            and source_comp_id == target_comp_id
        )
        return res

    name = fields.Char(
        string='Name', help='Name of the Transfer',
        copy=False, default=lambda self: _('New'), readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        default=_default_employee_id,
        tracking=True,
        help='Choose the employee you intend to transfer')
    old_employee_id = fields.Many2one(
        'hr.employee', string='Previous Employee',
        copy=False, readonly=True,
        help='Original employee record before cross-company transfer')
    new_employee_id = fields.Many2one(
        'hr.employee', string='New Employee',
        copy=False, readonly=True,
        help='New employee record created in target company')
    contract_id = fields.Many2one(
        'hr.contract', string='New Contract',
        copy=False, readonly=True,
        help='New contract created in the target company')
    transfer_date = fields.Date(
        string='Date', default=fields.Date.context_today,
        tracking=True,
        help="Transfer date")
    company_id = fields.Many2one(
        'res.company', string='Current Company',
        related='employee_id.company_id', store=True, readonly=True,
        tracking=True,
        help="Current Company of transfer")
    branch_id = fields.Many2one(
        'res.branch', string='Current Branch',
        compute='_compute_branch_id', store=True, readonly=False,
        tracking=True,
        help="Current Branch of employee")
    transfer_company_id = fields.Many2one(
        'res.company', string='Transfer To Company',
        help="Select the company to which the employee is being transferred",
        copy=False, required=True, tracking=True)
    transfer_branch_id = fields.Many2one(
        'res.branch', string='Transfer Branch',
        domain="[('company_id', '=', transfer_company_id)]",
        copy=False, tracking=True,
        help="Select the branch to which the employee is being transferred")
    is_same_company = fields.Boolean(
        string='Is Same Company Transfer',
        compute='_compute_is_same_company',
        help="Indicates whether the transfer is between branches within the same company")
    has_existing_contract = fields.Boolean(
        string='Has Existing Contract',
        compute='_compute_has_existing_contract',
        help="Checks if the employee already has a contract in the target company or within the same company")
    state = fields.Selection(
        [('draft', 'Draft'), ('requested', 'Requested'),
         ('transfer', 'Approved'), ('done', 'Done'), ('cancel', 'Cancelled')],
        string='Status', readonly=True, copy=False, default='draft',
        tracking=True,
        help="""Draft: Transfer is created.
        Requested: Transfer is submitted by employee and waiting for administrator approval.
        Approved: Transfer is approved by administrator.
        Done: Employee is joined/received in the transferred Company/Branch.
        Cancelled: Transfer is cancelled.""")
    note = fields.Text(
        string='Reason / Notes',
        help="Specify reasons or notes for the transfer")
    responsible_employee_id = fields.Many2one(
        comodel_name='hr.employee', string='Responsible',
        default=_default_responsible_employee_id, readonly=True,
        help="The person responsible for approving/processing the transfer.")
    def _default_is_hr_manager(self):
        """Default is_hr_manager for new records based on admin access."""
        return self._is_transfer_admin()

    is_hr_manager = fields.Boolean(
        string='Is HR Manager',
        default=_default_is_hr_manager,
        compute='_compute_is_hr_manager')

    @api.depends_context('uid')
    def _compute_is_hr_manager(self):
        """Check whether current user has Administrator access on Employee Transfer."""
        is_admin = self._is_transfer_admin()
        for transfer in self:
            transfer.is_hr_manager = is_admin


    @api.depends('employee_id', 'employee_id.branch_id', 'employee_id.user_id.branch_id')
    def _compute_branch_id(self):
        """Compute current branch from employee record or user record."""
        for transfer in self:
            if transfer.state not in ('draft',) and transfer.branch_id:
                continue
            emp = transfer.sudo().employee_id
            transfer.branch_id = (
                emp.branch_id
                or (emp.user_id and emp.user_id.branch_id)
                or False
            ) if emp else False

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """Set branch_id and company_id dynamically when employee is selected in form."""
        if self.employee_id:
            self.company_id = self.employee_id.company_id
            self.branch_id = (
                self.employee_id.branch_id
                or (self.employee_id.user_id and self.employee_id.user_id.branch_id)
                or False
            )
            source_comp = self.employee_id.company_id or self.company_id
            self.is_same_company = bool(
                source_comp and self.transfer_company_id
                and source_comp == self.transfer_company_id
            )
            self.has_existing_contract = self.is_same_company or bool(self._get_existing_target_contract())
        else:
            self.company_id = False
            self.branch_id = False
            self.is_same_company = False
            self.has_existing_contract = False

    @api.onchange('transfer_company_id')
    def _onchange_transfer_company_id(self):
        """Clear branch if not belonging to chosen transfer company."""
        if self.transfer_branch_id and self.transfer_branch_id.company_id != self.transfer_company_id:
            self.transfer_branch_id = False
        source_comp = self.employee_id.company_id or self.company_id
        self.is_same_company = bool(
            source_comp and self.transfer_company_id
            and source_comp == self.transfer_company_id
        )
        self.has_existing_contract = self.is_same_company or bool(self._get_existing_target_contract())

    @api.depends('company_id', 'transfer_company_id', 'employee_id', 'employee_id.company_id')
    def _compute_is_same_company(self):
        """Determine if transfer is between branches of the same company."""
        for transfer in self:
            source_comp = transfer.employee_id.company_id or transfer.company_id
            target_comp = transfer.transfer_company_id
            transfer.is_same_company = bool(
                source_comp and target_comp
                and source_comp.id == target_comp.id
            )

    def _get_existing_target_contract(self):
        """Find an existing contract for the employee in the target company or linked to this transfer."""
        self.ensure_one()
        if self.contract_id and self.contract_id.state != 'cancel':
            return self.contract_id

        target_company = self.transfer_company_id or self.company_id
        source_employee = (self.old_employee_id or self.employee_id).sudo()
        target_employee = (self.new_employee_id or source_employee).sudo()

        if not target_company or not source_employee:
            return self.env['hr.contract']

        # 1. Contract linked to this transfer (safely handle NewId during onchanges)
        transfer_id = self._origin.id if self._origin else (self.id if isinstance(self.id, int) else False)
        if transfer_id:
            existing = self.env['hr.contract'].sudo().search([
                ('emp_transfer', '=', transfer_id),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if existing:
                return existing

        # 2. Contract for employee in target company
        domain = [
            ('company_id', '=', target_company.id),
            ('state', '!=', 'cancel'),
        ]
        conditions = [('employee_id', '=', target_employee.id)]
        if source_employee != target_employee:
            conditions.append(('employee_id', '=', source_employee.id))
        if source_employee.user_id:
            conditions.append(('employee_id.user_id', '=', source_employee.user_id.id))
        if source_employee.work_contact_id:
            conditions.append(('employee_id.work_contact_id', '=', source_employee.work_contact_id.id))

        if len(conditions) > 1:
            domain = ['|'] * (len(conditions) - 1) + conditions + domain
        else:
            domain = conditions + domain

        existing = self.env['hr.contract'].sudo().search(domain, limit=1)
        return existing

    @api.depends('employee_id', 'employee_id.company_id', 'company_id', 'transfer_company_id', 'contract_id')
    def _compute_has_existing_contract(self):
        """Check if the employee already has a contract in the target company or if transfer is within the same company."""
        for transfer in self:
            source_comp = transfer.employee_id.company_id or transfer.company_id
            target_comp = transfer.transfer_company_id or transfer.company_id

            # If same company transfer, employee already has contract in this company
            if source_comp and target_comp and source_comp.id == target_comp.id:
                transfer.has_existing_contract = True
                continue

            existing = transfer._get_existing_target_contract()
            transfer.has_existing_contract = bool(existing)

    @api.constrains('employee_id')
    def _check_employee_id(self):
        """Validate employee permission for transfer request."""
        for transfer in self:
            if not transfer._is_transfer_admin():
                user_emp = self.env['hr.employee'].search([
                    ('user_id', '=', self.env.uid)], limit=1)
                if not user_emp:
                    raise ValidationError(_(
                        'Your user account is not linked to any employee record. '
                        'Only employees can request a transfer.'))
                if transfer.employee_id != user_emp:
                    raise ValidationError(_(
                        'Only the administrator can change the employee on a transfer request.'))

    @api.constrains('employee_id', 'state')
    def _check_pending_transfers(self):
        """Ensure no duplicate pending transfers for the same employee."""
        for transfer in self:
            if transfer.state in ('draft', 'requested', 'transfer') and transfer.employee_id:
                t_id = transfer._origin.id if transfer._origin else (transfer.id if isinstance(transfer.id, int) else False)
                domain = [
                    ('employee_id', '=', transfer.employee_id.id),
                    ('state', 'in', ('draft', 'requested', 'transfer'))
                ]
                if t_id:
                    domain.insert(0, ('id', '!=', t_id))
                pending = self.search(domain, limit=1)
                if pending:
                    raise ValidationError(_(
                        'There is already an active transfer request for employee %s.'
                    ) % transfer.employee_id.name)

    @api.constrains('transfer_company_id', 'transfer_branch_id', 'state')
    def _check_transfer_target(self):
        """Ensure target branch is selected if target company has branches."""
        for transfer in self:
            if transfer.state not in ('draft', 'cancel') and transfer.transfer_company_id:
                branch_count = self.env['res.branch'].search_count([
                    ('company_id', '=', transfer.transfer_company_id.id)])
                if branch_count > 0 and not transfer.transfer_branch_id:
                    raise ValidationError(_(
                        'Please select a target Branch for company %s.'
                    ) % transfer.transfer_company_id.name)

    def action_submit_request(self):
        """Employee submits transfer request for Administrator approval."""
        for transfer in self:
            if transfer.state != 'draft':
                raise UserError(_('Only draft transfer requests can be submitted.'))
            if not transfer.transfer_company_id:
                raise UserError(_('Please select a target Company for the transfer.'))
            branch_count = self.env['res.branch'].search_count([
                ('company_id', '=', transfer.transfer_company_id.id)])
            if branch_count > 0 and not transfer.transfer_branch_id:
                raise UserError(_(
                    'Please select a target Branch for company %s.'
                ) % transfer.transfer_company_id.name)
            transfer.state = 'requested'

    def action_approve(self):
        """Administrator approves transfer request."""
        if not self.env.user.has_group('hr_employee_transfer.group_employee_transfer_admin'):
            raise UserError(_('Only an Employee Transfer Administrator can approve transfer requests.'))
        for transfer in self:
            if transfer.state not in ('draft', 'requested'):
                raise UserError(_('Only draft or requested transfers can be approved.'))
            if not transfer.transfer_company_id:
                raise UserError(_('Please select a target Company.'))
            approver_emp = self.env['hr.employee'].sudo().search([
                ('user_id', '=', self.env.uid)], limit=1)
            if approver_emp:
                transfer.responsible_employee_id = approver_emp.id
            transfer.state = 'transfer'

    def action_transfer(self):
        """Compatibility action for direct transfer approval."""
        return self.action_approve()

    def _get_or_create_target_employee(self):
        """Find or create the employee record in the target company."""
        self.ensure_one()
        source_company = (self.old_employee_id or self.employee_id).company_id or self.company_id
        target_company = self.transfer_company_id or self.company_id
        if source_company and target_company and source_company == target_company:
            return self.employee_id

        if self.new_employee_id:
            return self.new_employee_id

        source_employee = (self.old_employee_id or self.employee_id).sudo().with_context(skip_duplicate_phone_check=True)

        existing_target_emp = False
        if source_employee.user_id:
            existing_target_emp = self.env['hr.employee'].sudo().with_context(active_test=False).search([
                ('company_id', '=', self.transfer_company_id.id),
                ('user_id', '=', source_employee.user_id.id),
            ], limit=1)

        if not existing_target_emp and source_employee.work_contact_id:
            existing_target_emp = self.env['hr.employee'].sudo().with_context(active_test=False).search([
                ('company_id', '=', self.transfer_company_id.id),
                ('work_contact_id', '=', source_employee.work_contact_id.id),
            ], limit=1)

        if not existing_target_emp:
            existing_target_emp = self.env['hr.employee'].sudo().with_context(active_test=False).search([
                ('company_id', '=', self.transfer_company_id.id),
                ('name', '=ilike', source_employee.name),
            ], limit=1)

        if existing_target_emp:
            new_emp = existing_target_emp
            emp_vals = {
                'active': True,
                'branch_id': self.transfer_branch_id.id if self.transfer_branch_id else False,
            }
            if source_employee.user_id:
                # Clean up any other employee in target company holding this user_id to prevent hr_employee_user_uniq violation
                other_emps = self.env['hr.employee'].sudo().with_context(active_test=False).search([
                    ('company_id', '=', self.transfer_company_id.id),
                    ('user_id', '=', source_employee.user_id.id),
                    ('id', '!=', new_emp.id),
                ])
                if other_emps:
                    other_emps.sudo().write({'user_id': False})
                emp_vals['user_id'] = source_employee.user_id.id
            new_emp.sudo().write(emp_vals)
        else:
            employee_data = source_employee.sudo().read([
                'name', 'private_email', 'gender',
                'identification_id', 'passport_id', 'work_email',
                'work_phone', 'mobile_phone', 'job_id',
            ])[0]
            del employee_data['id']

            # Map job_id to target company if restricted
            if employee_data.get('job_id'):
                old_job = self.env['hr.job'].sudo().browse(employee_data['job_id'][0])
                if old_job.company_id and old_job.company_id != self.transfer_company_id:
                    matched_job = self.env['hr.job'].sudo().search([
                        ('name', '=ilike', old_job.name),
                        '|', ('company_id', '=', False), ('company_id', '=', self.transfer_company_id.id)
                    ], limit=1)
                    employee_data['job_id'] = matched_job.id if matched_job else False
                else:
                    employee_data['job_id'] = old_job.id

            if source_employee.work_contact_id:
                employee_data['work_contact_id'] = source_employee.work_contact_id.id

            employee_data.update({
                'company_id': self.transfer_company_id.id,
                'branch_id': self.transfer_branch_id.id if self.transfer_branch_id else False,
                'user_id': source_employee.user_id.id if source_employee.user_id else False,
            })
            new_emp = self.env['hr.employee'].sudo().with_context(skip_duplicate_phone_check=True).create(employee_data)

        if source_employee.work_contact_id:
            # Ensure work contact partner is accessible across companies
            source_employee.work_contact_id.sudo().with_context(skip_duplicate_phone_check=True).write({
                'company_id': False
            })

        # Update linked user's allowed companies, current company and branch
        if source_employee.user_id:
            user = source_employee.user_id.with_company(self.transfer_company_id).sudo().with_context(skip_duplicate_phone_check=True)
            user_vals = {
                'company_ids': [(4, self.transfer_company_id.id)],
                'company_id': self.transfer_company_id.id,
            }
            if self.transfer_branch_id:
                user_vals['branch_ids'] = [(4, self.transfer_branch_id.id)]
                user_vals['branch_id'] = self.transfer_branch_id.id
            user.write(user_vals)

        self.write({
            'old_employee_id': source_employee.id,
            'new_employee_id': new_emp.id,
        })
        return new_emp

    def _get_source_contract(self):
        """Fetch the already created contract of the employee to copy details from."""
        self.ensure_one()
        source_employee = (self.old_employee_id or self.employee_id).sudo()

        domain = [
            ('employee_id', '=', source_employee.id),
            ('state', '!=', 'cancel'),
        ]
        if self.company_id:
            domain.append(('company_id', '=', self.company_id.id))
        old_contract = self.env['hr.contract'].sudo().search(domain, order='date_start desc, id desc', limit=1)

        if not old_contract:
            old_contract = self.env['hr.contract'].sudo().search([
                ('employee_id', '=', source_employee.id),
                ('state', '!=', 'cancel'),
            ], order='date_start desc, id desc', limit=1)

        if not old_contract and source_employee.user_id:
            old_contract = self.env['hr.contract'].sudo().search([
                ('employee_id.user_id', '=', source_employee.user_id.id),
                ('state', '!=', 'cancel'),
            ], order='date_start desc, id desc', limit=1)

        if not old_contract and source_employee.work_contact_id:
            old_contract = self.env['hr.contract'].sudo().search([
                ('employee_id.work_contact_id', '=', source_employee.work_contact_id.id),
                ('state', '!=', 'cancel'),
            ], order='date_start desc, id desc', limit=1)

        if not old_contract:
            old_contract = self.env['hr.contract'].sudo().search([
                ('employee_id', '=', source_employee.id),
            ], order='date_start desc, id desc', limit=1)

        return old_contract

    def _prepare_contract_vals_from_source(self, old_contract, target_employee, target_company):
        """Build contract values by copying all details from the source contract."""
        self.ensure_one()
        vals = {
            'name': _("Contract - %s") % target_employee.name,
            'employee_id': target_employee.id,
            'company_id': target_company.id,
            'date_start': self.transfer_date or fields.Date.today(),
            'wage': old_contract.wage or 0.0,
            'emp_transfer': self.id,
            'state': 'draft',
        }

        # Contract settings & types
        if hasattr(old_contract, 'schedule_pay') and old_contract.schedule_pay:
            vals['schedule_pay'] = old_contract.schedule_pay
        if hasattr(old_contract, 'contract_type_id') and old_contract.contract_type_id:
            vals['contract_type_id'] = old_contract.contract_type_id.id
        if hasattr(old_contract, 'structure_type_id') and old_contract.structure_type_id:
            vals['structure_type_id'] = old_contract.structure_type_id.id
        if hasattr(old_contract, 'notice_days'):
            vals['notice_days'] = old_contract.notice_days
        if hasattr(old_contract, 'notes') and old_contract.notes:
            vals['notes'] = old_contract.notes
        if hasattr(old_contract, 'trial_date_end') and old_contract.trial_date_end:
            vals['trial_date_end'] = old_contract.trial_date_end

        # Salary allowances
        for field_name in [
            'da', 'hra', 'travel_allowance', 'meal_allowance',
            'medical_allowance', 'other_allowance'
        ]:
            if field_name in old_contract._fields:
                vals[field_name] = getattr(old_contract, field_name)

        # Provident Fund (PF)
        for field_name in [
            'apply_pf', 'pf_employee_rate', 'pf_employer_rate',
            'pf_enforce_ceiling', 'pf_wage_ceiling', 'custom_monthly_pf'
        ]:
            if field_name in old_contract._fields:
                vals[field_name] = getattr(old_contract, field_name)

        # Employees' State Insurance (ESI)
        for field_name in [
            'apply_esi', 'esi_employee_rate', 'esi_employer_rate',
            'esi_wage_limit', 'custom_monthly_esi',
            'esi_contribution_start', 'esi_contribution_end'
        ]:
            if field_name in old_contract._fields:
                vals[field_name] = getattr(old_contract, field_name)

        # Tax Deducted at Source (TDS)
        for field_name in [
            'apply_tds', 'tds_include_cess', 'tds_standard_deduction',
            'custom_monthly_tds'
        ]:
            if field_name in old_contract._fields:
                vals[field_name] = getattr(old_contract, field_name)

        # Job Position (company-aware)
        if old_contract.job_id:
            if old_contract.job_id.company_id and old_contract.job_id.company_id != target_company:
                matched_job = self.env['hr.job'].sudo().search([
                    ('name', '=ilike', old_contract.job_id.name),
                    '|', ('company_id', '=', False), ('company_id', '=', target_company.id)
                ], limit=1)
                vals['job_id'] = matched_job.id if matched_job else False
            else:
                vals['job_id'] = old_contract.job_id.id
        elif target_employee.job_id:
            vals['job_id'] = target_employee.job_id.id

        # Department (company-aware)
        if old_contract.department_id:
            if old_contract.department_id.company_id and old_contract.department_id.company_id != target_company:
                matched_dept = self.env['hr.department'].sudo().search([
                    ('name', '=ilike', old_contract.department_id.name),
                    '|', ('company_id', '=', False), ('company_id', '=', target_company.id)
                ], limit=1)
                vals['department_id'] = matched_dept.id if matched_dept else False
            else:
                vals['department_id'] = old_contract.department_id.id
        elif target_employee.department_id:
            vals['department_id'] = target_employee.department_id.id

        # Working Schedule (company-aware)
        cal = old_contract.resource_calendar_id
        if cal:
            if cal.company_id and cal.company_id != target_company:
                matched_cal = self.env['resource.calendar'].sudo().search([
                    ('name', '=ilike', cal.name),
                    '|', ('company_id', '=', False), ('company_id', '=', target_company.id)
                ], limit=1)
                cal = matched_cal or target_company.resource_calendar_id
            vals['resource_calendar_id'] = cal.id if cal else False
        elif target_company.resource_calendar_id:
            vals['resource_calendar_id'] = target_company.resource_calendar_id.id

        # Payroll Structure (company-aware)
        if 'struct_id' in old_contract._fields and old_contract.struct_id:
            struct = old_contract.struct_id
            if struct.company_id and struct.company_id != target_company:
                matched_struct = self.env['hr.payroll.structure'].sudo().search([
                    ('name', '=ilike', struct.name),
                    '|', ('company_id', '=', False), ('company_id', '=', target_company.id)
                ], limit=1)
                vals['struct_id'] = matched_struct.id if matched_struct else False
            else:
                vals['struct_id'] = struct.id

        # Salary Journal (company-aware)
        if 'journal_id' in old_contract._fields and old_contract.journal_id:
            if old_contract.journal_id.company_id == target_company:
                vals['journal_id'] = old_contract.journal_id.id
            else:
                salary_journal = self.env['account.journal'].sudo().search([
                    ('company_id', '=', target_company.id),
                    ('type', '=', 'general'),
                ], limit=1)
                if salary_journal:
                    vals['journal_id'] = salary_journal.id

        # Analytic Account (company-aware)
        if 'analytic_account_id' in old_contract._fields and old_contract.analytic_account_id:
            if not old_contract.analytic_account_id.company_id or old_contract.analytic_account_id.company_id == target_company:
                vals['analytic_account_id'] = old_contract.analytic_account_id.id

        # HR Responsible
        if hasattr(old_contract, 'hr_responsible_id') and old_contract.hr_responsible_id:
            if not old_contract.hr_responsible_id.company_id or target_company in old_contract.hr_responsible_id.company_ids:
                vals['hr_responsible_id'] = old_contract.hr_responsible_id.id

        # Keep only fields valid on hr.contract model
        ContractModel = self.env['hr.contract']
        return {k: v for k, v in vals.items() if k in ContractModel._fields}

    def _create_or_update_target_contract(self):
        """Create new contract or update existing contract with details from source contract."""
        self.ensure_one()
        source_company = (self.old_employee_id or self.employee_id).company_id or self.company_id
        target_company = self.transfer_company_id or self.company_id

        # Do not create contracts for transfers within the same company
        if source_company and target_company and source_company == target_company:
            return False

        if not self.employee_id:
            raise UserError(_('Please select an employee first.'))
        if not self.transfer_company_id:
            raise UserError(_('Please select a target Company for the transfer.'))

        target_employee = self._get_or_create_target_employee()

        # Check if contract already exists
        existing_contract = self._get_existing_target_contract()
        if existing_contract:
            if not self.contract_id:
                self.write({'contract_id': existing_contract.id})
            if not existing_contract.emp_transfer:
                existing_contract.sudo().write({'emp_transfer': self.id})
            return existing_contract

        old_contract = self._get_source_contract()
        if not old_contract:
            raise ValidationError(
                _('No contract created for employee "%s". Please create a contract before proceeding.')
                % (self.old_employee_id or self.employee_id).name
            )

        vals = self._prepare_contract_vals_from_source(old_contract, target_employee, target_company)
        new_contract = self.env['hr.contract'].sudo().with_context(skip_transfer_done=True).create(vals)
        self.write({'contract_id': new_contract.id})
        return new_contract

    def action_create_contract(self):
        """Button action on Employee Transfer to fetch details from existing contract and fill in new contract."""
        self.ensure_one()
        if not self._is_transfer_admin():
            raise UserError(_('Only an Employee Transfer Administrator can create contracts.'))

        source_company = (self.old_employee_id or self.employee_id).company_id or self.company_id
        target_company = self.transfer_company_id or self.company_id
        if source_company and target_company and source_company == target_company:
            raise UserError(_(
                'Contract creation is not applicable for branch transfers within the same company. '
                'Contracts are only created when transferring an employee to a different company.'
            ))

        new_contract = self._create_or_update_target_contract()
        if not new_contract:
            raise UserError(_('Could not create contract for cross-company transfer.'))

        return {
            'name': _('Transferred Employee Contract'),
            'view_mode': 'form',
            'res_model': 'hr.contract',
            'res_id': new_contract.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
        }

    def action_receive_employee(self):
        """Execute transfer and complete contract creation in target company."""
        self.ensure_one()
        if not self._is_transfer_admin():
            raise UserError(_('Only an Employee Transfer Administrator can complete transfers.'))
        if self.state != 'transfer':
            raise UserError(_('Only approved transfers in status "Approved" can be completed.'))

        self = self.sudo().with_context(skip_duplicate_phone_check=True)
        source_employee = (self.old_employee_id or self.employee_id).sudo().with_context(skip_duplicate_phone_check=True)

        source_company = source_employee.company_id or self.company_id
        target_company = self.transfer_company_id or self.company_id

        if source_company and target_company and source_company == target_company:
            # Transfer within same company: update branch directly; NO contract created
            source_employee.sudo().write({
                'branch_id': self.transfer_branch_id.id if self.transfer_branch_id else False,
            })
            if source_employee.user_id and self.transfer_branch_id:
                branch_comp = self.transfer_branch_id.company_id or target_company
                source_employee.user_id.sudo().with_company(branch_comp).write({
                    'branch_ids': [(4, self.transfer_branch_id.id)],
                    'branch_id': self.transfer_branch_id.id,
                })

            # Check if employee has an existing active contract to link
            existing_contract = self.contract_id
            if not existing_contract or existing_contract.state == 'cancel':
                existing_contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', source_employee.id),
                    ('state', '!=', 'cancel'),
                ], limit=1)

            self.write({
                'state': 'done',
                'contract_id': existing_contract.id if existing_contract else False,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Branch Transfer Complete'),
                    'message': _('Employee %s has been transferred to branch %s.') % (
                        source_employee.name,
                        self.transfer_branch_id.name if self.transfer_branch_id else 'None'
                    ),
                    'sticky': False,
                    'type': 'success',
                }
            }
        else:
            # Cross-company transfer
            new_emp = self._get_or_create_target_employee()

            # Check if employee already has a contract in target company or linked to transfer
            existing_contract = self._get_existing_target_contract()
            if existing_contract:
                # Employee already has contract in target company -> no need to create new
                new_contract = existing_contract
                if not new_contract.emp_transfer:
                    new_contract.sudo().write({'emp_transfer': self.id})
                created_new = False
            else:
                # Employee does not have a contract in target company -> create new from source contract
                old_contract = self._get_source_contract()
                if not old_contract:
                    raise ValidationError(
                        _('No contract created for employee "%s". Please create a contract before completing the transfer.')
                        % source_employee.name
                    )
                new_contract = self._create_or_update_target_contract()
                created_new = True

            # Archive the previous employee record
            if source_employee != new_emp:
                source_employee.sudo().write({'active': False})

            # Finalize transfer record
            self.write({
                'old_employee_id': source_employee.id,
                'new_employee_id': new_emp.id,
                'contract_id': new_contract.id if new_contract else False,
                'state': 'done',
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Transfer Complete'),
                    'message': _('Employee %s has been transferred to %s.') % (
                        new_emp.name,
                        self.transfer_company_id.name,
                    ),
                    'sticky': False,
                    'type': 'success',
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }

    def cancel_transfer(self):
        """Transfer cancel function."""
        is_admin = self.env.user.has_group('hr_employee_transfer.group_employee_transfer_admin')
        for transfer in self:
            if not is_admin and (
                    not transfer.employee_id.user_id or transfer.employee_id.user_id != self.env.user):
                raise UserError(_('You can only cancel your own transfer request.'))
            transfer.state = 'cancel'

    def action_draft(self):
        """Reset transfer to draft state."""
        if not self.env.user.has_group('hr_employee_transfer.group_employee_transfer_admin'):
            raise UserError(_('Only an Employee Transfer Administrator can reset transfers to draft.'))
        for transfer in self:
            transfer.state = 'draft'

    def action_view_contract(self):
        """Smart button action to view created contract."""
        self.ensure_one()
        if not self.contract_id:
            raise UserError(_('No contract associated with this transfer.'))
        if self.contract_id.company_id and self.contract_id.company_id not in self.env.companies:
            raise UserError(_(
                "To view this contract, please select '%s' in the company switcher (top-right)."
            ) % self.contract_id.company_id.name)
        return {
            'name': _('Contract'),
            'view_mode': 'form',
            'res_model': 'hr.contract',
            'res_id': self.contract_id.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
        }

    def action_view_new_employee(self):
        """Smart button action to view new employee."""
        self.ensure_one()
        if not self.new_employee_id:
            raise UserError(_('No new employee record created.'))
        if self.new_employee_id.company_id and self.new_employee_id.company_id not in self.env.companies:
            raise UserError(_(
                "To view this employee, please select '%s' in the company switcher (top-right)."
            ) % self.new_employee_id.company_id.name)
        return {
            'name': _('New Employee'),
            'view_mode': 'form',
            'res_model': 'hr.employee',
            'res_id': self.new_employee_id.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
        }

    def write(self, vals):
        """Restrict modification by non-HR users when record is not draft."""
        is_admin = self._is_transfer_admin()
        if 'employee_id' in vals and not is_admin:
            raise UserError(_('Only administrators can change the employee on a transfer request.'))
        if 'employee_id' in vals and vals.get('employee_id'):
            emp = self.env['hr.employee'].sudo().browse(vals['employee_id'])
            if emp.company_id:
                vals['company_id'] = emp.company_id.id
            if 'branch_id' not in vals:
                vals['branch_id'] = (
                    emp.branch_id.id
                    or (emp.user_id and emp.user_id.branch_id.id)
                    or False
                )
        if not is_admin:
            for transfer in self:
                if transfer.state != 'draft' and not (set(vals.keys()) <= {'state'} and vals.get('state') in ('requested', 'cancel')):
                    raise UserError(_(
                        'You cannot modify a transfer request that is not in draft state.'))
        return super().write(vals)

    def unlink(self):
        """Restrict deletion of non-draft transfers."""
        for transfer in self:
            if transfer.state != 'draft':
                raise UserError(_(
                    'You cannot delete a transfer request that is not in draft state.'))
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        """Create new employee transfer records with formatted name."""
        for vals in vals_list:
            if vals.get('employee_id'):
                emp = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                vals['name'] = _("Transfer: %s") % emp.name
                if emp.company_id:
                    vals['company_id'] = emp.company_id.id
                if not vals.get('branch_id'):
                    vals['branch_id'] = (
                        emp.branch_id.id
                        or (emp.user_id and emp.user_id.branch_id.id)
                        or False
                    )
            else:
                vals['name'] = _("Transfer: New")
        return super().create(vals_list)
