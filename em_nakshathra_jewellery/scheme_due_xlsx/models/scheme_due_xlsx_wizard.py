from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date
from dateutil.relativedelta import relativedelta


class SchemeDueXlsxWizard(models.TransientModel):
    _name = 'scheme.due.xlsx.wizard'
    _description = 'Scheme Due XLSX Report Wizard'

    end_date = fields.Date(string='End Date', required=True, default=fields.Date.today)
    branch_ids = fields.Many2many('res.branch', string='Branches')
    partner_ids = fields.Many2many('res.partner', string='Partners')

    def action_generate_xlsx(self):
        domain = [('state', '=', 'running')]
        if self.end_date:
            domain.extend(['|', ('date_of_joining', '=', False), ('date_of_joining', '<=', self.end_date)])
            
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
        if self.partner_ids:
            domain.append(('partner_id', 'in', self.partner_ids.ids))
        
        records = self.env['jewellery.scheme.enrollment'].search(domain, order='date_of_joining asc, id asc')
        
        if not records:
            raise UserError(_("No running scheme records found for the selected filters."))
        
        data = {
            'end_date': self.end_date,
            'branch_ids': self.branch_ids.ids,
            'branch_names': ', '.join(self.branch_ids.mapped('name')) if self.branch_ids else 'All Branches',
            'partner_ids': self.partner_ids.ids,
            'partner_names': ', '.join(self.partner_ids.mapped('name')) if self.partner_ids else 'All Partners',
        }
        
        return self.env.ref('scheme_due_xlsx.action_report_scheme_due_xlsx').report_action(
            records, data=data
        )

