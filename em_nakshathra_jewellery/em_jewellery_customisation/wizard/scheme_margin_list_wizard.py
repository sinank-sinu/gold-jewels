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

        if self.is_redeemed:
            redemptions = self.env['scheme.redemption'].search([
                ('date', '>=', self.start_date),
                ('date', '<=', self.end_date),
            ])
            schemes = redemptions.mapped('scheme_id')
            if not schemes:
                raise UserError("No redeemed schemes found within the selected date range.")
        else:
            insts = self.env['jewellery.scheme.installment'].search([
                ('state', '=', 'paid'),
                ('date', '>=', self.start_date),
                ('date', '<=', self.end_date),
                ('enrollment_id.is_redeemed', '=', False),
            ])
            schemes = insts.mapped('enrollment_id')
            if not schemes:
                raise UserError("No non-redeemed schemes with paid installments found within the selected date range.")

        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'is_redeemed': self.is_redeemed,
        }

        return self.env.ref('em_jewellery_customisation.action_report_scheme_margin_list').report_action(schemes, data=data)
