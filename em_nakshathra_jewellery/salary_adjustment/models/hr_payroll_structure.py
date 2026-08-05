from odoo import models

class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    def init(self):
        super(HrPayrollStructure, self).init()
        # Ensure the SAD and LO rules are linked to the Base structure (ID 1)
        base_struct = self.env.ref('hr_payroll_community.structure_base', raise_if_not_found=False)
        sad_rule = self.env.ref('salary_adjustment.hr_rule_salary_advance', raise_if_not_found=False)
        lo_rule = self.env.ref('salary_adjustment.hr_rule_salary_loan', raise_if_not_found=False)
        
        if base_struct:
            if sad_rule and sad_rule not in base_struct.rule_ids:
                base_struct.write({'rule_ids': [(4, sad_rule.id)]})
            if lo_rule and lo_rule not in base_struct.rule_ids:
                base_struct.write({'rule_ids': [(4, lo_rule.id)]})
