from odoo import models, fields, api
import logging
from datetime import datetime
import io
import xlsxwriter
from odoo.tools import float_round

_logger = logging.getLogger(__name__)

class JobWorkReportWizard(models.TransientModel):
    _name = 'job.work.report.wizard'
    _description = 'Job Work Report Wizard'

    date_from = fields.Date(string='Date From', required=True, default=fields.Date.today)
    date_to = fields.Date(string='Date To', required=True, default=fields.Date.today)
    branch_ids = fields.Many2many('res.branch', string='Branches')
    partner_id = fields.Many2one('res.partner', string='Job Worker')
    job_type = fields.Selection([
        ('gold_only', 'Gold Only'),
        ('gold_alloy', 'Gold + Alloy')
    ], string='Job Type')
    type = fields.Selection([
        ('issue', 'Issue'),
        ('receive', 'Receive')
    ], string='Type')

    def action_generate_report(self):
        """Generate XLSX report for Job Work Report"""
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to)
        ]
        
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))

        records = self.env['job.work.report'].search(domain, order='date asc, id asc')
        
        if not records:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Records Found',
                    'message': 'No job work records found for the selected criteria.',
                    'type': 'warning',
                }
            }

        # Create XLSX file
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Job Work Report')

        # Define formats
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4F81BD',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        
        date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
        number_format = workbook.add_format({'num_format': '#,##0.000'})
        total_format = workbook.add_format({
            'bold': True,
            'bg_color': '#D7E4BD',
            'border': 1,
            'num_format': '#,##0.000'
        })

        # Set column widths
        worksheet.set_column('A:A', 12)  # Date
        worksheet.set_column('B:B', 20)  # Voucher Name
        worksheet.set_column('C:C', 10)  # Type
        worksheet.set_column('D:D', 15)  # Branch
        worksheet.set_column('E:E', 15)  # Job Worker
        worksheet.set_column('F:F', 12)  # Job Type
        worksheet.set_column('G:G', 12)  # Gross Weight
        worksheet.set_column('H:H', 12)  # Fine Issue
        worksheet.set_column('I:I', 12)  # Fine Receipt
        worksheet.set_column('J:J', 12)  # Balance
        worksheet.set_column('K:K', 12)  # Purity

        # Write headers
        headers = ['Date', 'Voucher Name', 'Type', 'Branch', 'Job Worker', 'Job Type', 
                  'Gross Weight', 'Fine Issue', 'Fine Receipt', 'Balance', 'Purity']
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)

        # Write data
        row = 1
        total_gross = 0
        total_fine_issue = 0
        total_fine_receipt = 0
        
        for record in records:
            worksheet.write(row, 0, record.date, date_format)
            worksheet.write(row, 1, record.voucher_name or '')
            worksheet.write(row, 2, dict(record._fields['type'].selection).get(record.type, ''))
            worksheet.write(row, 3, record.branch_id.name if record.branch_id else '')
            worksheet.write(row, 4, record.partner_id.name if record.partner_id else '')
            worksheet.write(row, 5, dict(record._fields['job_type'].selection).get(record.job_type, ''))
            worksheet.write(row, 6, record.gross_weight or 0, number_format)
            worksheet.write(row, 7, record.stock_in or 0, number_format)
            worksheet.write(row, 8, record.stock_out or 0, number_format)
            worksheet.write(row, 9, record.balance_weight or 0, number_format)
            worksheet.write(row, 10, record.purity_id.name if record.purity_id else '')
            
            total_gross += record.gross_weight or 0
            total_fine_issue += record.stock_in or 0
            total_fine_receipt += record.stock_out or 0
            
            row += 1

        # Write totals
        worksheet.write(row, 5, 'TOTAL:', header_format)
        worksheet.write(row, 6, total_gross, total_format)
        worksheet.write(row, 7, total_fine_issue, total_format)
        worksheet.write(row, 8, total_fine_receipt, total_format)

        # Add report info at the top
        info_format = workbook.add_format({'bold': True, 'font_size': 12})
        worksheet.merge_range('A1:K1', 'JOB WORK REPORT', info_format)
        worksheet.merge_range('A2:K2', f'Period: {self.date_from} to {self.date_to}', workbook.add_format({'font_size': 10}))
        if self.partner_id:
            worksheet.merge_range('A3:K3', f'Job Worker: {self.partner_id.name}', workbook.add_format({'font_size': 10}))
        
        # Shift data down to make room for headers
        if row > 1:
            worksheet.set_row(0, 25)
            worksheet.set_row(1, 20)
            if self.partner_id:
                worksheet.set_row(2, 20)

        workbook.close()
        output.seek(0)

        # Create attachment
        filename = f'job_work_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': output.getvalue(),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        # Return download action
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _generate_xlsx_for_records(self, records):
        """Generate XLSX for specific records"""
        if not records:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Records',
                    'message': 'No records to export.',
                    'type': 'warning',
                }
            }

        # Create XLSX file
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Job Work Report')

        # Define formats
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4F81BD',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        
        date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
        number_format = workbook.add_format({'num_format': '#,##0.000'})
        total_format = workbook.add_format({
            'bold': True,
            'bg_color': '#D7E4BD',
            'border': 1,
            'num_format': '#,##0.000'
        })

        # Set column widths
        worksheet.set_column('A:A', 12)  # Date
        worksheet.set_column('B:B', 20)  # Voucher Name
        worksheet.set_column('C:C', 10)  # Type
        worksheet.set_column('D:D', 15)  # Branch
        worksheet.set_column('E:E', 15)  # Job Worker
        worksheet.set_column('F:F', 12)  # Job Type
        worksheet.set_column('G:G', 12)  # Gross Weight
        worksheet.set_column('H:H', 12)  # Fine Issue
        worksheet.set_column('I:I', 12)  # Fine Receipt
        worksheet.set_column('J:J', 12)  # Balance
        worksheet.set_column('K:K', 12)  # Purity

        # Write headers
        headers = ['Date', 'Voucher Name', 'Type', 'Branch', 'Job Worker', 'Job Type', 
                  'Gross Weight', 'Fine Issue', 'Fine Receipt', 'Balance', 'Purity']
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)

        # Write data
        row = 1
        total_gross = 0
        total_fine_issue = 0
        total_fine_receipt = 0
        
        for record in records.sorted('date'):
            worksheet.write(row, 0, record.date, date_format)
            worksheet.write(row, 1, record.voucher_name or '')
            worksheet.write(row, 2, dict(record._fields['type'].selection).get(record.type, ''))
            worksheet.write(row, 3, record.branch_id.name if record.branch_id else '')
            worksheet.write(row, 4, record.partner_id.name if record.partner_id else '')
            worksheet.write(row, 5, dict(record._fields['job_type'].selection).get(record.job_type, ''))
            worksheet.write(row, 6, record.gross_weight or 0, number_format)
            worksheet.write(row, 7, record.stock_in or 0, number_format)
            worksheet.write(row, 8, record.stock_out or 0, number_format)
            worksheet.write(row, 9, record.balance_weight or 0, number_format)
            worksheet.write(row, 10, record.purity_id.name if record.purity_id else '')
            
            total_gross += record.gross_weight or 0
            total_fine_issue += record.stock_in or 0
            total_fine_receipt += record.stock_out or 0
            
            row += 1

        # Write totals
        worksheet.write(row, 5, 'TOTAL:', header_format)
        worksheet.write(row, 6, total_gross, total_format)
        worksheet.write(row, 7, total_fine_issue, total_format)
        worksheet.write(row, 8, total_fine_receipt, total_format)

        # Add report info at the top
        info_format = workbook.add_format({'bold': True, 'font_size': 12})
        worksheet.merge_range('A1:K1', 'JOB WORK REPORT', info_format)
        worksheet.merge_range('A2:K2', f'Period: {records.sorted("date")[0].date} to {records.sorted("date")[-1].date}', workbook.add_format({'font_size': 10}))
        
        # Shift data down to make room for headers
        if row > 1:
            worksheet.set_row(0, 25)
            worksheet.set_row(1, 20)

        workbook.close()
        output.seek(0)

        # Create attachment
        filename = f'job_work_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': output.getvalue(),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        # Return download action
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
