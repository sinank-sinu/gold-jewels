from odoo import models, fields, _

class StockSummaryReportWizard(models.TransientModel):
    _inherit = 'stock.summary.report.wizard'

    def action_print_product_wise_xlsx(self):
        self.ensure_one()
        self.action_generate_report()
        branch_names = ', '.join(self.branch_ids.mapped('name')) if self.branch_ids else 'All Branches'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/metal_ledger/export_stock_summary_product_wise?start_date={self.start_date}&end_date={self.end_date}&branch_name={branch_names}',
            'target': 'self',
        }
