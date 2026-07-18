from odoo import models, fields, api
from odoo.exceptions import UserError

class SchemeMarginListWizard(models.TransientModel):
    _name = 'scheme.margin.list.wizard'
    _description = 'Scheme Margin List Wizard'

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    is_redeemed = fields.Boolean(string="Redeemed Filter")

    def action_print_report(self):
        self.ensure_one()
        if self.start_date > self.end_date:
            raise UserError("Start Date cannot be greater than End Date.")

        domain = [('is_redeemed', '=', self.is_redeemed)]
        schemes = self.env['jewellery.scheme.enrollment'].search(domain)

        if not schemes:
            raise UserError("No schemes found for the selected filter.")

        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
        }

        return self.env.ref('em_jewellery_customisation.action_report_scheme_margin_list').report_action(schemes, data=data)
