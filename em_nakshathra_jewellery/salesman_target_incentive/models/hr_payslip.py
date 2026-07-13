from odoo import models, fields, api


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    is_incentive_slip = fields.Boolean(
        string='Is Incentive Slip', 
        default=False,
    )

    @api.model
    def get_inputs(self, contracts, date_from, date_to):
        res = super(HrPayslip, self).get_inputs(contracts, date_from, date_to)

        is_incentive = self.env.context.get('default_is_incentive_slip', False)
        if not is_incentive:
            return res

        for contract in contracts:
            employee = contract.employee_id
            
            domain = [
                '|', '|',
                    ('employee_id', '=', employee.id),
                    ('salesman_id', '=', employee.user_id.id if employee.user_id else -1),
                    ('salesman_id.name', '=', employee.name),
                ('state', '=', 'confirmed'),
                ('is_achieved', '=', True),
                ('payslip_id', '=', False),
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

    def action_payslip_done(self):

        res = super().action_payslip_done()

        for payslip in self:
            if not payslip.is_incentive_slip:
                continue

            employee = payslip.employee_id

            domain = [
                '|', '|',
                    ('employee_id', '=', employee.id),
                    ('salesman_id', '=', employee.user_id.id if employee.user_id else False),
                    ('salesman_id.name', '=', employee.name),
                ('state', '=', 'confirmed'),
                ('is_achieved', '=', True),
                ('payslip_id', '=', False),
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