from odoo import models, api, fields

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    advance_ids = fields.One2many(
        'salary.advance', 'payslip_id',
        string='Salary Advances',
        readonly=True
    )
    loan_line_ids = fields.One2many(
        'salary.loan.line', 'payslip_id',
        string='Loan Installments',
        readonly=True
    )

    def get_inputs(self, contract_ids, date_from, date_to):
        if isinstance(contract_ids, list):
            contracts = self.env['hr.contract'].sudo().browse(contract_ids)
        else:
            contracts = contract_ids.sudo()

        # 1. Resolve structure ids (fallback to payslip struct_id if contract has none)
        structure_ids = contracts.get_all_structures()
        if not structure_ids and self and hasattr(self, 'struct_id') and self.struct_id:
            structure_ids = list(set(self.struct_id._get_parent_structure().ids))

        # 2. Compute base inputs based on resolved structure
        res = []
        if structure_ids:
            rule_ids = self.env['hr.payroll.structure'].browse(structure_ids).get_all_rules()
            sorted_rule_ids = [id for id, sequence in sorted(rule_ids, key=lambda x: x[1])]
            inputs = self.env['hr.salary.rule'].browse(sorted_rule_ids).mapped('input_ids')
            for contract in contracts:
                for input_val in inputs:
                    res.append({
                        'name': input_val.name,
                        'code': input_val.code,
                        'contract_id': contract.id,
                        'date_from': date_from,
                        'date_to': date_to,
                    })
        else:
            res = super(HrPayslip, self).get_inputs(contract_ids, date_from, date_to)

        # 3. Handle Salary Advance (SAD) and Loan (LO) inputs
        employee = contracts[0].employee_id if contracts else self.employee_id
        if employee and contracts:
            contract = contracts[0]
            
            # Find current payslip IDs (including virtual ones) to allow recalculation of already-linked advances/loans
            payslip_ids = [False]
            if self:
                for p in self:
                    if p.id:
                        payslip_ids.append(p.id)
                    if hasattr(p, '_origin') and p._origin and p._origin.id:
                        payslip_ids.append(p._origin.id)
            payslip_ids = list(set(pid for pid in payslip_ids if pid is not None))

            # Find approved, undeducted advances in the period or linked to this payslip
            advances = self.env['salary.advance'].search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'approved'),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('payslip_id', 'in', payslip_ids),
                ('salary_adjustment_line_id', '=', False)
            ])
            total_amount = sum(advances.mapped('amount'))
            if total_amount > 0:
                sad_found = False
                for result in res:
                    if result.get('code') == 'SAD':
                        result['amount'] = total_amount
                        sad_found = True
                if not sad_found:
                    res.append({
                        'name': 'Salary Advance Deduction',
                        'code': 'SAD',
                        'amount': total_amount,
                        'contract_id': contract.id,
                        'date_from': date_from,
                        'date_to': date_to,
                    })

            # Check for custom salary.loan.line installment deductions
            loan_lines = self.env['salary.loan.line'].search([
                ('employee_id', '=', employee.id),
                ('loan_id.state', '=', 'approved'),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('paid', '=', False),
                ('payslip_id', 'in', payslip_ids)
            ])
            total_loan_amount = sum(loan_lines.mapped('amount'))
            if total_loan_amount > 0:
                lo_found = False
                for result in res:
                    if result.get('code') == 'LO':
                        result['amount'] = total_loan_amount
                        lo_found = True
                if not lo_found:
                    res.append({
                        'name': 'Loan Deduction',
                        'code': 'LO',
                        'amount': total_loan_amount,
                        'contract_id': contract.id,
                        'date_from': date_from,
                        'date_to': date_to,
                    })

            # Check for loans (LO) if ohrms_loan is installed (fallback/compatibility)
            if 'hr.loan' in self.env:
                loans = self.env['hr.loan'].search([
                    ('employee_id', '=', employee.id),
                    ('state', '=', 'approve')
                ])
                for loan in loans:
                    for loan_line in loan.loan_lines:
                        if (date_from <= loan_line.date <= date_to and
                                not loan_line.paid):
                            lo_found = False
                            for result in res:
                                if result.get('code') == 'LO':
                                    result['amount'] = loan_line.amount
                                    result['loan_line_id'] = loan_line.id
                                    lo_found = True
                            if not lo_found:
                                res.append({
                                    'name': 'Loan Deduction',
                                    'code': 'LO',
                                    'amount': loan_line.amount,
                                    'contract_id': contract.id,
                                    'date_from': date_from,
                                    'date_to': date_to,
                                    'loan_line_id': loan_line.id,
                                })
        return res

    @api.onchange('struct_id')
    def onchange_struct_id(self):
        if self.struct_id and self.contract_id:
            # Recompute worked days and inputs
            date_from = self.date_from
            date_to = self.date_to
            contracts = self.contract_id
            
            worked_days_line_ids = self.get_worked_day_lines(contracts, date_from, date_to)
            worked_days_lines = self.worked_days_line_ids.browse([])
            for r in worked_days_line_ids:
                worked_days_lines += worked_days_lines.new(r)
            self.worked_days_line_ids = worked_days_lines
            
            input_line_ids = self.get_inputs(contracts, date_from, date_to)
            input_lines = self.input_line_ids.browse([])
            for r in input_line_ids:
                input_lines += input_lines.new(r)
            self.input_line_ids = input_lines

    @api.onchange('employee_id')
    def onchange_employee(self):
        res = super(HrPayslip, self).onchange_employee()
        # If struct_id is not set but we have a contract, default to Base structure and compute inputs
        if not self.struct_id and self.contract_id:
            base_struct = self.env.ref('hr_payroll_community.structure_base', raise_if_not_found=False)
            if base_struct:
                self.struct_id = base_struct.id
                self.onchange_struct_id()
        return res

    def action_compute_sheet(self):
        for payslip in self:
            # Auto-link approved advances in this period that don't have a payslip linked yet
            advances = self.env['salary.advance'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('state', '=', 'approved'),
                ('date', '>=', payslip.date_from),
                ('date', '<=', payslip.date_to),
                ('payslip_id', 'in', [False, payslip.id]),
                ('salary_adjustment_line_id', '=', False)
            ])
            adv_to_link = advances.filtered(lambda a: not a.payslip_id)
            if adv_to_link:
                adv_to_link.write({'payslip_id': payslip.id})

            # Auto-link approved unpaid loan installment lines in this period
            loan_lines = self.env['salary.loan.line'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('loan_id.state', '=', 'approved'),
                ('date', '>=', payslip.date_from),
                ('date', '<=', payslip.date_to),
                ('paid', '=', False),
                ('payslip_id', 'in', [False, payslip.id])
            ])
            loan_to_link = loan_lines.filtered(lambda l: not l.payslip_id)
            if loan_to_link:
                loan_to_link.write({'payslip_id': payslip.id})

            contract = payslip.sudo().contract_id
            if contract:
                # Compute current inputs
                input_line_ids = payslip.sudo().get_inputs(contract, payslip.date_from, payslip.date_to)
                
                # If there are no inputs currently, write them directly
                if not payslip.input_line_ids:
                    input_lines = [(0, 0, r) for r in input_line_ids]
                    payslip.sudo().write({'input_line_ids': input_lines})
                else:
                    # Update existing inputs or insert missing ones
                    existing_inputs = {line.code: line for line in payslip.input_line_ids}
                    new_lines = []
                    for r in input_line_ids:
                        code = r.get('code')
                        if code in existing_inputs:
                            if code in ('SAD', 'LO'):
                                write_vals = {'amount': r.get('amount', 0.0)}
                                if 'loan_line_id' in r:
                                    write_vals['loan_line_id'] = r.get('loan_line_id')
                                existing_inputs[code].sudo().write(write_vals)
                            elif r.get('amount') is not None:
                                existing_inputs[code].sudo().write({'amount': r.get('amount')})
                        else:
                            new_lines.append((0, 0, r))
                    if new_lines:
                        payslip.sudo().write({'input_line_ids': new_lines})
                        
        return super(HrPayslip, self.sudo()).action_compute_sheet()

    def action_payslip_done(self):
        res = super(HrPayslip, self).action_payslip_done()
        for payslip in self:
            # 1. Handle Advances
            advances = self.env['salary.advance'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('state', '=', 'approved'),
                ('date', '>=', payslip.date_from),
                ('date', '<=', payslip.date_to),
                ('payslip_id', 'in', [False, payslip.id]),
                ('salary_adjustment_line_id', '=', False)
            ])
            if advances:
                advances.write({'payslip_id': payslip.id})

            # 2. Handle Custom Loan Lines
            loan_lines = self.env['salary.loan.line'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('loan_id.state', '=', 'approved'),
                ('date', '>=', payslip.date_from),
                ('date', '<=', payslip.date_to),
                ('paid', '=', False),
                ('payslip_id', 'in', [False, payslip.id])
            ])
            if loan_lines:
                loan_lines.write({
                    'paid': True,
                    'payslip_id': payslip.id
                })
                # If all installments of a loan are paid, close the loan
                for loan in loan_lines.mapped('loan_id'):
                    if all(line.paid for line in loan.line_ids):
                        loan.write({'state': 'closed'})

        return res

    def action_payslip_draft(self):
        res = super(HrPayslip, self).action_payslip_draft()
        for payslip in self:
            # 1. Reset Advances
            advances = self.env['salary.advance'].search([
                ('payslip_id', '=', payslip.id)
            ])
            if advances:
                advances.write({'payslip_id': False})

            # 2. Reset Custom Loan Lines
            loan_lines = self.env['salary.loan.line'].search([
                ('payslip_id', '=', payslip.id)
            ])
            if loan_lines:
                loan_lines.write({
                    'paid': False,
                    'payslip_id': False
                })
                for loan in loan_lines.mapped('loan_id'):
                    if loan.state == 'closed':
                        loan.write({'state': 'approved'})

        return res

    def action_payslip_cancel(self):
        res = super(HrPayslip, self).action_payslip_cancel()
        for payslip in self:
            # 1. Reset Advances
            advances = self.env['salary.advance'].search([
                ('payslip_id', '=', payslip.id)
            ])
            if advances:
                advances.write({'payslip_id': False})

            # 2. Reset Custom Loan Lines
            loan_lines = self.env['salary.loan.line'].search([
                ('payslip_id', '=', payslip.id)
            ])
            if loan_lines:
                loan_lines.write({
                    'paid': False,
                    'payslip_id': False
                })
                for loan in loan_lines.mapped('loan_id'):
                    if loan.state == 'closed':
                        loan.write({'state': 'approved'})

        return res
