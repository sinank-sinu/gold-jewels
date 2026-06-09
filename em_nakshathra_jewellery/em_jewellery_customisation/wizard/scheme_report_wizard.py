from odoo import models, fields, api
from odoo.exceptions import UserError

class SchemeReportWizard(models.TransientModel):
    _name = 'scheme.report.wizard'
    _description = 'Scheme Report Wizard'

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)

    def action_print_combined_report(self):
        self.ensure_one()
        if self.start_date > self.end_date:
            raise UserError("Start Date cannot be greater than End Date.")

        domain = [
            ('create_date', '>=', self.start_date),
            ('create_date', '<=', self.end_date)
        ]
        
        schemes = self.env['jewellery.scheme.enrollment'].search(domain)

        if not schemes:
            raise UserError("No schemes found within the selected date range.")

        return self.env.ref('em_jewellery_customisation.action_report_scheme_redeem_margin').report_action(schemes)


