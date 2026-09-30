from odoo import models

class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    def init(self):
        super(HrPayrollStructure, self).init()
        # Ensure the statutory and deduction rules are linked to structures
        base_struct = self.env.ref('hr_payroll_community.structure_base', raise_if_not_found=False)
        sales_struct = self.env.ref('salesman_target_incentive.hr_salary_structure_sales_incentive', raise_if_not_found=False)
        
        rule_refs = [
            'salary_adjustment.hr_rule_pf',
            'salary_adjustment.hr_rule_esi',
            'salary_adjustment.hr_rule_salary_advance',
            'salary_adjustment.hr_rule_salary_loan',
            'salary_adjustment.hr_rule_tds',
        ]
        rules = [self.env.ref(r, raise_if_not_found=False) for r in rule_refs]
        rules_to_unlink = self.env['hr.salary.rule'].search([('code', 'in', ['PF_EMP', 'ESI_EMP'])])
        
        for struct in [base_struct, sales_struct]:
            if struct:
                rules_to_add = []
                for rule in rules:
                    if rule and rule not in struct.rule_ids:
                        rules_to_add.append((4, rule.id))
                if rules_to_unlink:
                    for r in rules_to_unlink:
                        if r in struct.rule_ids:
                            rules_to_add.append((3, r.id))
                if rules_to_add:
                    struct.write({'rule_ids': rules_to_add})
