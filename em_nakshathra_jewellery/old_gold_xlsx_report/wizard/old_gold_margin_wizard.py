from odoo import models, fields

class OldGoldMarginWizard(models.TransientModel):
    _name = 'old.gold.margin.wizard'
    _description = 'Old Gold Margin Report Wizard'

    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    branch_ids = fields.Many2many('res.branch', string="Branches")
    
    def action_print_report(self):
        return self.env.ref(
            'old_gold_xlsx_report.old_gold_margin_xlsx_report'
        ).report_action(self)