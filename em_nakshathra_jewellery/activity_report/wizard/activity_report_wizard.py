# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import datetime
from collections import defaultdict


class ActivityReportWizard(models.TransientModel):
    _name = 'activity.report.wizard'
    _description = 'Activity Report Wizard'

    date_from = fields.Date(string='From Date', required=True, default=datetime.date.today().replace(day=1))
    date_to = fields.Date(string='To Date', required=True, default=datetime.date.today())
    branch_ids = fields.Many2many('res.branch', string='Branches')
    user_ids = fields.Many2many('res.users', string='Users')

    def action_generate_report(self):
        """
        Generate activity report and export to xlsx
        """
        self.ensure_one()
        
        # Validate date range
        if self.date_from > self.date_to:
            raise UserError(_('From Date must be less than or equal to To Date'))
        
        # Get data for report
        report_data = self._get_report_data()
        
        # Export to xlsx
        return self._export_xlsx(report_data)

    def _get_report_data(self):
        """
        Get report data based on selected filters
        """
        self.ensure_one()
        data = []
        
        # Get users to report - if no users selected, get all users
        users = self.user_ids if self.user_ids else self.env['res.users'].sudo().search([])
        print(f"Total users to report: {len(users)}")
        
        # For each user, get counts
        for user in users:
            user_data = {
                'user': user.name,
                'branches': ', '.join(self.branch_ids.mapped('name')) if self.branch_ids else 'All Branches',
            }
            
            # Sale Order count
            sale_domain = [
                ('date_order', '>=', self.date_from),
                ('date_order', '<=', self.date_to),
                ('user_id', '=', user.id),
            ]
            if self.branch_ids:
                sale_domain += ['|', ('branch_id', 'in', self.branch_ids.ids), ('branch_id', '=', False)]
            sale_count = self.env['sale.order'].sudo().search_count(sale_domain)
            user_data['sale_order_count'] = sale_count

            # Purchase Order count
            purchase_domain = [
                ('date_order', '>=', self.date_from),
                ('date_order', '<=', self.date_to),
                ('create_uid', '=', user.id),
            ]
            if self.branch_ids:
                purchase_domain += ['|', ('branch_id', 'in', self.branch_ids.ids), ('branch_id', '=', False)]
            purchase_count = self.env['purchase.order'].sudo().search_count(purchase_domain)
            user_data['purchase_order_count'] = purchase_count
            print(f"User: {user.name}, Purchase Order Domain: {purchase_domain}, Count: {purchase_count}")
            
            # Vendor Bill count
            vendor_bill_domain = [
                ('invoice_date', '>=', self.date_from),
                ('invoice_date', '<=', self.date_to),
                ('move_type', '=', 'in_invoice'),
                ('create_uid', '=', user.id),
            ]
            if self.branch_ids:
                vendor_bill_domain += ['|', ('branch_id', 'in', self.branch_ids.ids), ('branch_id', '=', False)]
            vendor_bill_count = self.env['account.move'].sudo().search_count(vendor_bill_domain)
            user_data['vendor_bill_count'] = vendor_bill_count

            # Customer Invoice count
            customer_invoice_domain = [
                ('invoice_date', '>=', self.date_from),
                ('invoice_date', '<=', self.date_to),
                ('move_type', '=', 'out_invoice'),
                ('create_uid', '=', user.id),
            ]
            if self.branch_ids:
                customer_invoice_domain += ['|', ('branch_id', 'in', self.branch_ids.ids), ('branch_id', '=', False)]
            customer_invoice_count = self.env['account.move'].sudo().search_count(customer_invoice_domain)
            user_data['customer_invoice_count'] = customer_invoice_count

            # Customer Invoice Payment Receipt count
            customer_payment_domain = [
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
                ('partner_type', '=', 'customer'),
                ('create_uid', '=', user.id),
            ]
            if self.branch_ids:
                customer_payment_domain += ['|', ('branch_id', 'in', self.branch_ids.ids), ('branch_id', '=', False)]
            customer_payment_count = self.env['account.payment'].sudo().search_count(customer_payment_domain)
            user_data['customer_payment_count'] = customer_payment_count

            # Vendor Invoice Payment Receipt count
            vendor_payment_domain = [
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
                ('partner_type', '=', 'supplier'),
                ('create_uid', '=', user.id),
            ]
            if self.branch_ids:
                vendor_payment_domain += ['|', ('branch_id', 'in', self.branch_ids.ids), ('branch_id', '=', False)]
            vendor_payment_count = self.env['account.payment'].sudo().search_count(vendor_payment_domain)
            user_data['vendor_payment_count'] = vendor_payment_count

            # Total transaction count
            user_data['transaction_count'] = (
                user_data['sale_order_count'] +
                user_data['purchase_order_count'] +
                user_data['vendor_bill_count'] +
                user_data['customer_invoice_count'] +
                user_data['customer_payment_count'] +
                user_data['vendor_payment_count']
            )
            
            # Add all users to see their data (even if 0)
            data.append(user_data)
        
        return data

    def _export_xlsx(self, data):
        """
        Export report data to xlsx file
        """
        import xlsxwriter
        import io
        import base64
        
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Activity Report')
        
        # Define formats
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4F81BD',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        
        cell_format = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter'
        })
        
        number_format = workbook.add_format({
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'num_format': '#,##0'
        })
        
        # Write headers
        headers = [
            'User',
            'Branches',
            'Transaction Count',
            'Sale Order Count',
            'Purchase Order Count',
            'Vendor Bill Count',
            'Customer Invoice Count',
            'Customer Payment Count',
            'Vendor Payment Count'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
            worksheet.set_column(col, col, 20)
        
        # Write data
        for row, record in enumerate(data, start=1):
            worksheet.write(row, 0, record['user'], cell_format)
            worksheet.write(row, 1, record['branches'], cell_format)
            worksheet.write(row, 2, record['transaction_count'], number_format)
            worksheet.write(row, 3, record['sale_order_count'], number_format)
            worksheet.write(row, 4, record['purchase_order_count'], number_format)
            worksheet.write(row, 5, record['vendor_bill_count'], number_format)
            worksheet.write(row, 6, record['customer_invoice_count'], number_format)
            worksheet.write(row, 7, record['customer_payment_count'], number_format)
            worksheet.write(row, 8, record['vendor_payment_count'], number_format)
        
        workbook.close()
        output.seek(0)
        
        # Create attachment
        filename = f'Activity_Report_{self.date_from}_{self.date_to}.xlsx'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.encodebytes(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
