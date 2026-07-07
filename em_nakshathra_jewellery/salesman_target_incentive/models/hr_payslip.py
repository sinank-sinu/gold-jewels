from odoo import models, fields


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_payslip_done(self):

        res = super().action_payslip_done()

        for payslip in self:

            employee = payslip.employee_id

            targets = self.env['salesman.target'].search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'confirmed'),
                ('is_achieved', '=', True),
                ('payslip_id', '=', False),
            ])

            for target in targets:
                target.write({
                    'payslip_id': payslip.id,
                    'state': 'paid',
                    'payment_date': fields.Date.today(),
                    'paid_amount': target.earned_incentive,
                })

        return res