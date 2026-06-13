from odoo import models, fields, api, _
from odoo.exceptions import UserError


class JobWorkXlsxWizard(models.TransientModel):
    _name = 'job.work.xlsx.wizard'
    _description = 'Job Work XLSX Report Wizard'

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    branch_ids = fields.Many2many('res.branch', string='Branches')
    partner_ids = fields.Many2many('res.partner', string='Partners')

    def action_generate_xlsx(self):
        domain = []
        if self.start_date:
            domain.append(('date', '>=', self.start_date))
        if self.end_date:
            domain.append(('date', '<=', self.end_date))
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
        if self.partner_ids:
            domain.append(('partner_id', 'in', self.partner_ids.ids))
        
        records = self.env['job.work.report'].search(domain, order='date asc, id asc')
        
        if not records:
            raise UserError(_("No records found for the selected filters."))
        
        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'branch_ids': self.branch_ids.ids,
            'branch_names': ', '.join(self.branch_ids.mapped('name')) if self.branch_ids else 'All Branches',
            'partner_ids': self.partner_ids.ids,
            'partner_names': ', '.join(self.partner_ids.mapped('name')) if self.partner_ids else 'All Partners',
        }
        
        return self.env.ref('job_work_xlsx.action_report_job_work_xlsx').report_action(
            records, data=data
        )
