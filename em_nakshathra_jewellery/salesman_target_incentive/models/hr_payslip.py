from odoo import models, fields, api, _


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    is_incentive_slip = fields.Boolean(
        string='Is Incentive Slip', 
        default=False,
    )

    @api.onchange('employee_id', 'date_from', 'date_to')
    def onchange_employee(self):
        res = super(HrPayslip, self).onchange_employee()
        is_inc = (
            self.is_incentive_slip
            or (self.struct_id and self.struct_id.code == 'INC_STRUCT')
            or self.env.context.get('default_is_incentive_slip')
        )
        if is_inc:
            self.is_incentive_slip = True
            incentive_struct = self.env['hr.payroll.structure'].search([('code', '=', 'INC_STRUCT')], limit=1)
            if incentive_struct:
                self.struct_id = incentive_struct.id
            if self.contract_id and self.date_from and self.date_to:
                input_data = self.get_inputs(self.contract_id, self.date_from, self.date_to)
                input_lines = self.input_line_ids.browse([])
                for r in input_data:
                    input_lines += input_lines.new(r)
                self.input_line_ids = input_lines
        return res

    @api.onchange('contract_id')
    def onchange_contract_id(self):
        res = super(HrPayslip, self).onchange_contract_id()
        is_inc = (
            self.is_incentive_slip
            or (self.struct_id and self.struct_id.code == 'INC_STRUCT')
            or self.env.context.get('default_is_incentive_slip')
        )
        if is_inc:
            self.is_incentive_slip = True
            incentive_struct = self.env['hr.payroll.structure'].search([('code', '=', 'INC_STRUCT')], limit=1)
            if incentive_struct:
                self.struct_id = incentive_struct.id
            if self.contract_id and self.date_from and self.date_to:
                input_data = self.get_inputs(self.contract_id, self.date_from, self.date_to)
                input_lines = self.input_line_ids.browse([])
                for r in input_data:
                    input_lines += input_lines.new(r)
                self.input_line_ids = input_lines
        return res

    @api.model
    def get_inputs(self, contracts, date_from, date_to):
        res = super(HrPayslip, self).get_inputs(contracts, date_from, date_to)

        is_incentive = (
            self.env.context.get('default_is_incentive_slip', False)
            or (hasattr(self, 'is_incentive_slip') and self.is_incentive_slip)
            or (hasattr(self, 'struct_id') and self.struct_id and self.struct_id.code == 'INC_STRUCT')
        )
        if not is_incentive:
            return res

        for contract in contracts:
            employee = contract.employee_id
            
            domain = [
                '|', '|',
                    ('employee_id', '=', employee.id),
                    ('salesman_id', '=', employee.user_id.id if employee.user_id else -1),
                    ('salesman_id.name', '=', employee.name),
                ('state', 'in', ['confirmed', 'transferred', 'closed', 'paid']),
                ('is_achieved', '=', True),
                ('payslip_id', 'in', [False, self.id] if hasattr(self, 'id') and self.id else [False]),
                ('date_from', '<=', date_to),
                ('date_to', '>=', date_from),
            ]
            
            targets = self.env['salesman.target'].search(domain)
            
            total_incentive = sum(targets.mapped('earned_incentive'))
            
            if total_incentive > 0:
                found = False
                for r in res:
                    if r.get('code') in ['INC', 'TARGET_INC', 'INC_SALES'] and r.get('contract_id') == contract.id:
                        r['amount'] = total_incentive
                        r['code'] = 'INC_SALES'
                        found = True
                        break
                
                if not found:
                    res.append({
                        'name': 'Salesman Target Incentive',
                        'code': 'INC_SALES',
                        'amount': total_incentive,
                        'contract_id': contract.id,
                    })
                    
        return res

    def action_compute_sheet(self):
        for payslip in self:
            is_inc = (
                payslip.is_incentive_slip
                or (payslip.struct_id and payslip.struct_id.code == 'INC_STRUCT')
                or self.env.context.get('default_is_incentive_slip')
            )
            if is_inc:
                if not payslip.is_incentive_slip:
                    payslip.is_incentive_slip = True

                if not payslip.struct_id or payslip.struct_id.code != 'INC_STRUCT':
                    inc_struct = self.env['hr.payroll.structure'].search([('code', '=', 'INC_STRUCT')], limit=1)
                    if inc_struct:
                        payslip.struct_id = inc_struct.id

                employee = payslip.employee_id
                contract = payslip.contract_id or (
                    employee and self.get_contract(employee, payslip.date_from, payslip.date_to)
                    and self.env['hr.contract'].browse(self.get_contract(employee, payslip.date_from, payslip.date_to)[0])
                )

                domain = [
                    '|', '|',
                        ('employee_id', '=', employee.id),
                        ('salesman_id', '=', employee.user_id.id if employee.user_id else -1),
                        ('salesman_id.name', '=', employee.name),
                    ('state', 'in', ['confirmed', 'transferred', 'closed', 'paid']),
                    ('is_achieved', '=', True),
                    ('payslip_id', 'in', [False, payslip.id]),
                    ('date_from', '<=', payslip.date_to),
                    ('date_to', '>=', payslip.date_from),
                ]
                targets = self.env['salesman.target'].search(domain)
                total_incentive = sum(targets.mapped('earned_incentive'))

                inc_lines = payslip.input_line_ids.filtered(lambda l: l.code in ['INC_SALES', 'INC', 'TARGET_INC'])
                if inc_lines:
                    inc_lines.write({
                        'name': 'Salesman Target Incentive',
                        'code': 'INC_SALES',
                        'amount': total_incentive,
                        'contract_id': contract.id if contract else False,
                    })
                elif total_incentive > 0 or not payslip.input_line_ids:
                    self.env['hr.payslip.input'].create({
                        'payslip_id': payslip.id,
                        'name': 'Salesman Target Incentive',
                        'code': 'INC_SALES',
                        'amount': total_incentive,
                        'contract_id': contract.id if contract else False,
                    })

        return super(HrPayslip, self).action_compute_sheet()

    def action_payslip_done(self):
        res = super(HrPayslip, self).action_payslip_done()

        for payslip in self:
            is_inc = payslip.is_incentive_slip or (payslip.struct_id and payslip.struct_id.code == 'INC_STRUCT')
            if not is_inc:
                continue

            employee = payslip.employee_id

            domain = [
                '|', '|',
                    ('employee_id', '=', employee.id),
                    ('salesman_id', '=', employee.user_id.id if employee.user_id else -1),
                    ('salesman_id.name', '=', employee.name),
                ('state', 'in', ['confirmed', 'transferred', 'closed', 'paid']),
                ('is_achieved', '=', True),
                ('payslip_id', 'in', [False, payslip.id]),
                ('date_from', '<=', payslip.date_to),
                ('date_to', '>=', payslip.date_from),
            ]

            targets = self.env['salesman.target'].search(domain)

            for target in targets:
                target.write({
                    'payslip_id': payslip.id,
                    'state': 'paid',
                    'payment_date': fields.Date.today(),
                })

        return res

    def _restore_targets(self):
        for payslip in self:
            targets = self.env['salesman.target'].search([('payslip_id', '=', payslip.id)])
            for target in targets:
                prev_state = 'transferred' if target.is_transferred else (
                    'closed' if target.date_to and target.date_to < fields.Date.today() else 'confirmed'
                )
                target.write({
                    'payslip_id': False,
                    'payment_date': False,
                    'state': prev_state,
                })

    def action_payslip_cancel(self):
        self._restore_targets()
        return super(HrPayslip, self).action_payslip_cancel()

    def action_payslip_draft(self):
        self._restore_targets()
        return super(HrPayslip, self).action_payslip_draft()

    def unlink(self):
        self._restore_targets()
        return super(HrPayslip, self).unlink()