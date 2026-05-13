import io
from odoo import http
from odoo.http import request

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

class StockSummaryReportController(http.Controller):

    @http.route('/metal_ledger/export_stock_summary', type='http', auth='user')
    def export_stock_summary_report(self, start_date=None, end_date=None, branch_name=None, **kwargs):
        # Fetch report lines generated for the current user
        report_lines = request.env['stock.summary.report.line'].search([
            ('create_uid', '=', request.env.user.id)
        ])
        
        if not report_lines:
            return "No report data found. Please generate the report from the wizard first."

        output = io.BytesIO()
        if not xlsxwriter:
            return "xlsxwriter library not found in the environment."

        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Stock Summary Report')

        # Formats
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center'})
        border_format = workbook.add_format({'border': 1})
        num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.000'})
        pcs_format = workbook.add_format({'border': 1, 'num_format': '#,##0'})

        # Worksheet Layout
        worksheet.set_column('A:A', 30)  # Product
        worksheet.set_column('B:P', 15)  # Data columns

        # Title
        worksheet.merge_range('A1:T1', 'Stock Summary Report', title_format)
        
        # Header Info
        worksheet.write('A2', f'Period: {start_date} to {end_date}', border_format)
        worksheet.write('A3', f'Branch: {branch_name}', border_format)

        # Headers
        headers = [
            'Product', 'Caret', 'Opening PCs', 'Opening Gross', 'Opening Net',
            'In PCs', 'In Gross', 'In Net',
            'Out PCs', 'Out Gross', 'Out Net',
            'Closing PCs', 'Closing Gross', 'Closing Net',
            'Avg Inventory', 'Inv Turnover Ratio', 'No of Days', 'DIO', 'Min Stock', 'Stock Gap'
        ]
        
        row = 5
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)

        row += 1
        for line in report_lines:
            worksheet.write(row, 0, line.product_id.display_name or line.product_template_id.display_name, border_format)
            worksheet.write(row, 1, line.purity_id.name if line.purity_id else '', border_format)

            ageing_val = getattr(line, 'ageing', '')
            worksheet.write(row, 2, line.ageing_val, border_format)
            worksheet.write(row, 3, line.opening_pcs, pcs_format)
            worksheet.write(row, 4, line.opening_gross_weight, num_format)
            worksheet.write(row, 5, line.opening_net_weight, num_format)
            worksheet.write(row, 6, line.in_pcs, pcs_format)
            worksheet.write(row, 7, line.in_gross_weight, num_format)
            worksheet.write(row, 8, line.in_net_weight, num_format)
            worksheet.write(row, 9, line.out_pcs, pcs_format)
            worksheet.write(row, 10, line.out_gross_weight, num_format)
            worksheet.write(row, 11, line.out_net_weight, num_format)
            worksheet.write(row, 12, line.closing_pcs, pcs_format)
            worksheet.write(row, 13, line.closing_gross_weight, num_format)
            worksheet.write(row, 14, line.closing_net_weight, num_format)
            worksheet.write(row, 15, line.average_inventory, num_format)
            worksheet.write(row, 16, line.turnover_ratio, num_format)
            worksheet.write(row, 17, line.no_of_days, border_format)
            worksheet.write(row, 18, line.dio, border_format)
            worksheet.write(row, 19, line.min_stock_level, num_format)
            worksheet.write(row, 20, line.stock_gap, num_format)
            row += 1

        workbook.close()
        output.seek(0)

        filename = 'Stock_Summary_With_KPIS.xlsx'
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename={filename};')
            ]
        )
