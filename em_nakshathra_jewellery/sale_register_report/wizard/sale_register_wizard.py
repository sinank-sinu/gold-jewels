# -*- coding: utf-8 -*-

from odoo import models, fields


class SaleRegisterWizard(models.TransientModel):
    _name = 'sale.register.wizard'
    _description = 'Sale Register Wizard'

    date_from = fields.Date(string="From Date", required=True)
    date_to = fields.Date(string="To Date", required=True)
    branch_ids = fields.Many2many('res.branch', string='Branches')

    def action_download_report(self):
        domain = [
            ('date_order', '>=', self.date_from),
            ('date_order', '<=', self.date_to),
            ('state', 'in', ['sale', 'done'])
        ]
        
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
        
        sale_orders = self.env['sale.order'].search(domain)

        data = {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'branch_ids': self.branch_ids.ids,
            'so_ids': sale_orders.ids
        }

        return self.env.ref('sale_register_report.action_sale_register_xlsx').report_action(sale_orders, data=data)
