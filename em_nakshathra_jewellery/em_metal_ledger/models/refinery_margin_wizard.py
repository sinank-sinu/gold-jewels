from odoo import models, fields, _
from odoo.exceptions import UserError

class RefineryMarginWizard(models.TransientModel):
    _name = 'refinery.margin.wizard'
    _description = 'Refinery Margin XLSX Wizard'

    start_date = fields.Date(string='From Date')
    end_date = fields.Date(string='To Date')
    partner_ids = fields.Many2many('res.partner', string="Partners")

    def action_print_xlsx(self):
        domain = []

        if self.start_date:
            domain.append(('date', '>=', self.start_date))
        if self.end_date:
            domain.append(('date', '<=', self.end_date))

        if self.partner_ids:
            domain.append(('issue_id.refinery_partner_id', 'in', self.partner_ids.ids))
            # OR adjust based on your actual relation

        records = self.env['refinery.margin.report'].search(domain, order='date asc, id asc')

        if not records:
            from odoo.exceptions import UserError
            raise UserError("No records found"  )

        return self.env.ref('em_metal_ledger.action_report_refinery_margin_xlsx').report_action(
            records,
            data={
                'partner_ids': self.partner_ids.ids
            }
        )