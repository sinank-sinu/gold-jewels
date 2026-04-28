import io
import json
from odoo import http
from odoo.http import request
from odoo.tools import date_utils

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class StockCheckReportController(http.Controller):

    @http.route('/stock_check/export_report', type='http', auth='user')
    def export_stock_check_report(self, report_id, report_type='manager', **kwargs):
        report = request.env['jewellery.weekly.stock.check'].browse(int(report_id))
        if not report.exists():
            return request.not_found()

        output = io.BytesIO()
        
        # Fallback if xlsxwriter is not available
        if not xlsxwriter:
            return "xlsxwriter library not found in the environment. Please contact administrator."

        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Stock Check Report')
        
        # Set Column Widths
        worksheet.set_column('A:A', 40)  # Product
        worksheet.set_column('B:H', 15)  # Other columns
        
        # Formats
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center'
        })
        title_format = workbook.add_format({'bold': True, 'font_size': 14})
        match_format = workbook.add_format({'bg_color': '#C6EFCE', 'border': 1})
        mismatch_format = workbook.add_format({'bg_color': '#FFC7CE', 'border': 1})
        border_format = workbook.add_format({'border': 1})

        # Header Info
        worksheet.write('A1', f'Weekly Stock Check ({report_type.capitalize()})', title_format)
        worksheet.write('A2', f'Reference: {report.name}')
        worksheet.write('A3', f'Branch: {report.branch_id.name}')
        worksheet.write('A4', f'Location: {report.location_id.name}')
        worksheet.write('A5', f'Date: {report.date}')

        # Table Headers
        row = 7
        col = 0
        if report_type == 'manager':
            headers = ['Product', 'Label', 'System Qty', 'System Weight', 'Counted Labels', 'Counted Weight', 'Diff Label', 'Diff Weight', 'Status']
        else:
            headers = ['Product', 'Label', 'Counted Labels', 'Counted Weight']
            
        for header in headers:
            worksheet.write(row, col, header, header_format)
            col += 1
            
        # Lines
        row += 1
        for line in report.line_ids:
            col = 0
            if report_type == 'manager':
                current_format = match_format if line.is_matched else mismatch_format if line.manual_qty != 0 else border_format
                worksheet.write(row, col, line.product_id.display_name, current_format)
                worksheet.write(row, col+1, line.label_id.name or '', current_format)
                worksheet.write(row, col+2, line.system_qty, current_format)
                worksheet.write(row, col+3, line.system_weight, current_format)
                worksheet.write(row, col+4, line.manual_qty, current_format)
                worksheet.write(row, col+5, line.manual_weight, current_format)
                worksheet.write(row, col+6, line.difference_qty, current_format)
                worksheet.write(row, col+7, line.difference_weight, current_format)
                worksheet.write(row, col+8, 'Matched' if line.is_matched else 'Mismatch', current_format)
            else:
                worksheet.write(row, col, line.product_id.display_name, border_format)
                worksheet.write(row, col+1, line.label_id.name or '', border_format)
                worksheet.write(row, col+2, line.manual_qty, border_format)
                worksheet.write(row, col+3, line.manual_weight, border_format)
            row += 1

        # Second Worksheet: Template Summary
        summary_sheet = workbook.add_worksheet('Template Summary')
        summary_sheet.set_column('A:A', 40)
        summary_sheet.set_column('B:G', 15)

        summary_sheet.write('A1', 'Product Template Summary', title_format)
        summary_sheet.write('A2', f'Reference: {report.name}')
        summary_sheet.write('A3', f'Date: {report.date}')

        row = 5
        col = 0
        if report_type == 'manager':
            summary_headers = ['Product Template', 'Total Labels', 'Total Weight', 'Counted Labels', 'Counted Weight', 'Diff Label', 'Diff Weight']
        else:
            summary_headers = ['Product Template', 'Counted Labels', 'Counted Weight']

        for header in summary_headers:
            summary_sheet.write(row, col, header, header_format)
            col += 1

        row += 1
        for summary in report.template_summary_ids:
            col = 0
            if report_type == 'manager':
                summary_sheet.write(row, col, summary.product_tmpl_id.name, border_format)
                summary_sheet.write(row, col+1, summary.system_qty, border_format)
                summary_sheet.write(row, col+2, summary.system_weight, border_format)
                summary_sheet.write(row, col+3, summary.manual_qty, border_format)
                summary_sheet.write(row, col+4, summary.manual_weight, border_format)
                summary_sheet.write(row, col+5, summary.difference_qty, border_format)
                summary_sheet.write(row, col+6, summary.difference_weight, border_format)
            else:
                summary_sheet.write(row, col, summary.product_tmpl_id.name, border_format)
                summary_sheet.write(row, col+1, summary.manual_qty, border_format)
                summary_sheet.write(row, col+2, summary.manual_weight, border_format)
            row += 1

        workbook.close()
        output.seek(0)
        
        filename = f'Stock_Check_{report_type}_{report.name}.xlsx'
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename={filename};')
            ]
        )
