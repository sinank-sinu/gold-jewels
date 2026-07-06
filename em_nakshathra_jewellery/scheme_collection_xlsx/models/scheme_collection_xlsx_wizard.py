from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SchemeCollectionXlsxWizard(models.TransientModel):
    _name = 'scheme.collection.xlsx.wizard'
    _description = 'Scheme Collection XLSX Report Wizard'

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    branch_ids = fields.Many2many('res.branch', string='Branches')
    partner_ids = fields.Many2many('res.partner', string='Partners')

    def action_generate_xlsx(self):
        # Build the domain directly targetting installment lines matching criteria
        domain = [
            ('date', '>=', self.start_date),
            ('date', '<=', self.end_date)
        ]
        
        if self.branch_ids:
            # Filters lines where the parent scheme enrollment matches selected branches
            domain.append(('enrollment_id.branch_id', 'in', self.branch_ids.ids))
        if self.partner_ids:
            # Filters lines where the parent scheme enrollment matches selected customers
            domain.append(('enrollment_id.partner_id', 'in', self.partner_ids.ids))
        
        # Verify records exist before triggering spreadsheet generation
        line_count = self.env['jewellery.scheme.installment'].search_count(domain)
        if not line_count:
            raise UserError(_("No installment records found for the selected filters."))
        
        # Structure payload keys to align seamlessly with the report dictionary lookups
        data = {
            'date_from': self.start_date,
            'date_to': self.end_date,
            'branch_ids': self.branch_ids.ids,
            'partner_ids': self.partner_ids.ids,
        }
        
        # Pass 'self' (the wizard instance) so wizard_record inside the engine contains dates
        return self.env.ref('scheme_collection_xlsx.action_report_scheme_collection_xlsx').report_action(
            self, data=data
        )
