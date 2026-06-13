from odoo import models, fields


class CapitalGainWizard(models.TransientModel):
    _name = 'capital.gain.wizard'
    _description = 'Purchase Capital Gain Wizard'

    date_from = fields.Date(string="From Date", required=True)
    date_to = fields.Date(string="To Date", required=True)

    def action_print_report(self):
        purchase_orders = self.env['purchase.order'].search([
            ('date_order', '>=', self.date_from),
            ('date_order', '<=', self.date_to),
            ('state', 'in', ['purchase', 'done'])
        ])

        data = {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'po_ids': purchase_orders.ids
        }

        return self.env.ref('purchase_fine_rate_variance_report.action_purchase_capital_gain_xlsx').report_action(purchase_orders, data=data)