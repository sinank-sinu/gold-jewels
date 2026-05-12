from odoo import http
from odoo.http import request, content_disposition
import io
import xlsxwriter
from datetime import datetime

class JobWorkReportController(http.Controller):

    @http.route('/web/job_work_report/export/<int:wizard_id>', type='http', auth='user')
    def export_job_work_report_xlsx(self, wizard_id, **kwargs):
        """Export Job Work Report as XLSX via HTTP request"""
        wizard = request.env['job.work.report.wizard'].browse(wizard_id)
        if not wizard.exists():
            return request.not_found()

        # Get filtered records
        domain = [
            ('date', '>=', wizard.date_from),
            ('date', '<=', wizard.date_to)
        ]
        
        if wizard.partner_id:
            domain.append(('partner_id', '=', wizard.partner_id.id))
        if wizard.job_type:
            domain.append(('job_type', '=', wizard.job_type))
        if wizard.type:
            domain.append(('type', '=', wizard.type))

        records = request.env['job.work.report'].search(domain, order='date asc, id asc')
        
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
        worksheet.set_column('A:A', 12)
        worksheet.set_column('B:B', 20)
        worksheet.set_column('C:C', 10)
        worksheet.set_column('D:D', 15)
        worksheet.set_column('E:E', 12)
        worksheet.set_column('F:F', 12)
        worksheet.set_column('G:G', 12)
        worksheet.set_column('H:H', 12)
        worksheet.set_column('I:I', 12)
        worksheet.set_column('J:J', 12)

        # Write headers
        headers = ['Date', 'Voucher Name', 'Type', 'Job Worker', 'Job Type', 
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
            worksheet.write(row, 3, record.partner_id.name if record.partner_id else '')
            worksheet.write(row, 4, dict(record._fields['job_type'].selection).get(record.job_type, ''))
            worksheet.write(row, 5, record.gross_weight or 0, number_format)
            worksheet.write(row, 6, record.stock_in or 0, number_format)
            worksheet.write(row, 7, record.stock_out or 0, number_format)
            worksheet.write(row, 8, record.balance_weight or 0, number_format)
            worksheet.write(row, 9, record.purity_id.name if record.purity_id else '')
            
            total_gross += record.gross_weight or 0
            total_fine_issue += record.stock_in or 0
            total_fine_receipt += record.stock_out or 0
            
            row += 1

        # Write totals
        worksheet.write(row, 4, 'TOTAL:', header_format)
        worksheet.write(row, 5, total_gross, total_format)
        worksheet.write(row, 6, total_fine_issue, total_format)
        worksheet.write(row, 7, total_fine_receipt, total_format)

        workbook.close()
        output.seek(0)

        # Prepare response
        filename = f'job_work_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        
        response = request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition(filename))
            ]
        )
        
        return response
