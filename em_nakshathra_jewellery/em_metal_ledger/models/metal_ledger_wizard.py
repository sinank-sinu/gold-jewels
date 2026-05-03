from odoo import models, fields, api, _
from odoo.exceptions import UserError

class MetalLedgerWizard(models.TransientModel):
    _name = 'metal.ledger.wizard'
    _description = 'Metal Ledger Report Wizard'

    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    branch_id = fields.Many2one('res.branch', string='Branch')
    partner_id = fields.Many2one('res.partner', string='Partner')

    def action_print_report(self):
        domain = []
        if self.start_date:
            domain.append(('date', '>=', self.start_date))
        if self.end_date:
            domain.append(('date', '<=', self.end_date))
        if self.branch_id:
            domain.append(('branch_id', '=', self.branch_id.id))
        if self.partner_id:
            domain.append(('partner_id', '=', self.partner_id.id))
        
        records = self.env['metal.ledger'].search(domain, order='date asc, id asc')
        if not records:
            raise UserError(_("No records found for the selected filters."))
        
        return self.env.ref('em_metal_ledger.action_report_metal_ledger').report_action(records)


    def action_print_xlsx(self):
        domain = []
        if self.start_date:
            domain.append(('date', '>=', self.start_date))
        if self.end_date:
            domain.append(('date', '<=', self.end_date))
        if self.branch_id:
            domain.append(('branch_id', '=', self.branch_id.id))
        if self.partner_id:
            domain.append(('partner_id', '=', self.partner_id.id))

        records = self.env['metal.ledger'].search(domain, order='date asc, id asc')

        if not records:
            raise UserError(_("No records found for the selected filters."))

        return self.env.ref('em_metal_ledger.action_report_metal_ledger_xlsx').report_action(records)