from odoo import models, fields

class SaleBelowMaxWizard(models.TransientModel):
    _name = 'sale.below.max.wizard'
    _description = 'Sale Below Maximum Report Wizard'

    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    branch_ids = fields.Many2many('res.branch', string='Branches')


    def action_print_xlsx(self):
        return self.env.ref(
            'sale_below_max_report.sale_below_max_xlsx_report'
        ).report_action(self)