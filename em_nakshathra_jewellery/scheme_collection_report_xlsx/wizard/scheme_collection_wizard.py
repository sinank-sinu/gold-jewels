from odoo import models, fields

class SchemeCollectionReportWizard(models.TransientModel):
    _name = 'scheme.collection.report.wizard'
    _description = 'Scheme Collection Report Wizard'

    start_date = fields.Date(string='Start Date', required=True, default=fields.Date.today)
    end_date = fields.Date(string='End Date', required=True, default=fields.Date.today)
    branch_ids = fields.Many2many('res.branch', string='Branch(es)')

    def action_generate_xlsx(self):
        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'branch_ids': self.branch_ids.ids if self.branch_ids else False,
        }
        return self.env.ref('scheme_collection_report_xlsx.action_report_scheme_collection_xlsx').report_action(self, data=data)
