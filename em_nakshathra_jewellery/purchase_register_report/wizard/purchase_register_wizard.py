# -*- coding: utf-8 -*-

from datetime import datetime, time

from odoo import models, fields


class PurchaseRegisterWizard(models.TransientModel):
    _name = 'purchase.register.wizard'
    _description = 'Purchase Register Wizard'

    date_from = fields.Date(string="From Date", required=True)
    date_to = fields.Date(string="To Date", required=True)
    branch_ids = fields.Many2many('res.branch', string='Branches')

    def action_download_report(self):
        domain = [
            ('date_order', '>=', datetime.combine(self.date_from, time.min)),
            ('date_order', '<=', datetime.combine(self.date_to, time.max)),
            ('state', 'in', ['purchase', 'done'])
        ]
        
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
        
        purchase_orders = self.env['purchase.order'].search(domain)

        data = {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'branch_ids': self.branch_ids.ids,
            'po_ids': purchase_orders.ids
        }

        return self.env.ref('purchase_register_report.action_purchase_register_xlsx').report_action(purchase_orders, data=data)
