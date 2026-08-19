import io
from collections import defaultdict
from odoo import http
from odoo.http import request

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

class StockSummaryReportController(http.Controller):

    @http.route('/metal_ledger/export_stock_summary', type='http', auth='user')
    def export_stock_summary_report(self, start_date=None, end_date=None, branch_name=None, **kwargs):
        # Fetch report lines generated for the current user (Detailed Label-level export)
        report_lines = request.env['stock.summary.report.line'].sudo().search([
            ('create_uid', '=', request.env.user.id)
        ])
        
        if not report_lines:
            return "No report data found. Please generate the report from the wizard first."

        output = io.BytesIO()
        if not xlsxwriter:
            return "xlsxwriter library not found in the environment."

        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Stock Summary Detailed')

        # Formats
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center'})
        border_format = workbook.add_format({'border': 1})
        num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.000'})
        pcs_format = workbook.add_format({'border': 1, 'num_format': '#,##0'})

        # Worksheet Layout
        worksheet.set_column('A:A', 30)  # Product
        worksheet.set_column('B:Z', 15)  # Data columns

        # Title
        worksheet.merge_range('A1:Z1', 'Stock Summary Report (Detailed)', title_format)
        
        # Header Info
        worksheet.write('A2', f'Period: {start_date} to {end_date}', border_format)
        worksheet.write('A3', f'Branch: {branch_name}', border_format)

        # Headers
        headers = [
            'Product', 'Label', 'Type', 'Variety', 'Design', 'Size', 'Stone Colour', 'Metal Colour', 'Purity', 'Ageing',
            'Opening PCs', 'Opening Gross', 'Opening Net',
            'In PCs', 'In Gross', 'In Net',
            'Out PCs', 'Out Gross', 'Out Net',
            'Closing PCs', 'Closing Gross', 'Closing Net',
            'Avg Inventory', 'Turnover Ratio', 'No of Days', 'DIO', 'Min Stock', 'Stock Gap'
        ]
        
        row = 5
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)

        row += 1
        for line in report_lines:
            worksheet.write(row, 0, line.product_id.display_name or line.product_template_id.display_name, border_format)
            worksheet.write(row, 1, line.label_id.name if line.label_id else '', border_format)
            worksheet.write(row, 2, line.type_value or '', border_format)
            worksheet.write(row, 3, line.variety_value or '', border_format)
            worksheet.write(row, 4, line.design_value or '', border_format)
            worksheet.write(row, 5, line.size_value or '', border_format)
            worksheet.write(row, 6, line.stone_colour_value or '', border_format)
            worksheet.write(row, 7, line.metal_colour_value or '', border_format)
            worksheet.write(row, 8, line.purity_id.name if line.purity_id else '', border_format)
            
            ageing_val = getattr(line, 'ageing', 0) or 0
            worksheet.write(row, 9, ageing_val, border_format)

            worksheet.write(row, 10, line.opening_pcs, pcs_format)
            worksheet.write(row, 11, line.opening_gross_weight, num_format)
            worksheet.write(row, 12, line.opening_net_weight, num_format)
            worksheet.write(row, 13, line.in_pcs, pcs_format)
            worksheet.write(row, 14, line.in_gross_weight, num_format)
            worksheet.write(row, 15, line.in_net_weight, num_format)
            worksheet.write(row, 16, line.out_pcs, pcs_format)
            worksheet.write(row, 17, line.out_gross_weight, num_format)
            worksheet.write(row, 18, line.out_net_weight, num_format)
            worksheet.write(row, 19, line.closing_pcs, pcs_format)
            worksheet.write(row, 20, line.closing_gross_weight, num_format)
            worksheet.write(row, 21, line.closing_net_weight, num_format)
            worksheet.write(row, 22, line.average_inventory, num_format)
            worksheet.write(row, 23, line.turnover_ratio, num_format)
            worksheet.write(row, 24, line.no_of_days, border_format)
            worksheet.write(row, 25, line.dio, border_format)
            worksheet.write(row, 26, line.min_stock_level, num_format)
            worksheet.write(row, 27, line.stock_gap, num_format)
            row += 1

        workbook.close()
        output.seek(0)

        filename = 'Stock_Summary_Detailed.xlsx'
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename={filename};')
            ]
        )

    @http.route('/metal_ledger/export_stock_summary_grouped', type='http', auth='user')
    def export_stock_summary_grouped_report(self, start_date=None, end_date=None, branch_name=None, **kwargs):
        # Fetch report lines generated for the current user (Product-grouped Summary export)
        report_lines = request.env['stock.summary.report.line'].sudo().search([
            ('create_uid', '=', request.env.user.id)
        ])
        
        if not report_lines:
            return "No report data found. Please generate the report from the wizard first."

        output = io.BytesIO()
        if not xlsxwriter:
            return "xlsxwriter library not found in the environment."

        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Product Summary')

        # Formats
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center'})
        border_format = workbook.add_format({'border': 1})
        num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.000'})
        pcs_format = workbook.add_format({'border': 1, 'num_format': '#,##0'})
        int_format = workbook.add_format({'border': 1, 'num_format': '#,##0'})
        dec2_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})

        # Worksheet Layout
        worksheet.set_column('A:A', 30)  # Product
        worksheet.set_column('B:Z', 15)  # Data columns

        # Title
        worksheet.merge_range('A1:Z1', 'Stock Summary Report (Product Grouped)', title_format)
        
        # Header Info
        worksheet.write('A2', f'Period: {start_date} to {end_date}', border_format)
        worksheet.write('A3', f'Branch: {branch_name}', border_format)

        # Headers with 6 Variant columns
        headers = [
            'Product', 'Type', 'Variety', 'Design', 'Size', 'Stone Colour', 'Metal Colour',
            'Ageing',
            'Opening PCs', 'Opening Gross', 'Opening Net',
            'In PCs', 'In Gross', 'In Net',
            'Out PCs', 'Out Gross', 'Out Net',
            'Closing PCs', 'Closing Gross', 'Closing Net',
            'Avg Inventory', 'No of Days', 'Min Stock', 'Turnover Ratio', 'DIO', 'Stock Gap'
        ]
        
        row = 5
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)

        # Group lines strictly by Product Variant ID to ensure 100% unique variant rows
        grouped_data = defaultdict(list)
        for line in report_lines:
            if line.product_id:
                p_key = ('product', line.product_id.id)
            elif line.product_template_id:
                p_key = ('template', line.product_template_id.id)
            else:
                p_key = ('unknown', line.id)
            grouped_data[p_key].append(line)

        row += 1
        for p_key, lines in grouped_data.items():
            count = len(lines)
            sample_line = lines[0]
            if sample_line.product_id:
                p_name = sample_line.product_id.display_name
            elif sample_line.product_template_id:
                p_name = sample_line.product_template_id.display_name
            else:
                p_name = 'Unknown'
            
            type_val = sample_line.type_value or ''
            variety_val = sample_line.variety_value or ''
            design_val = sample_line.design_value or ''
            size_val = sample_line.size_value or ''
            stone_col_val = sample_line.stone_colour_value or ''
            metal_col_val = sample_line.metal_colour_value or ''
            
            ageing_avg = round(sum(l.ageing for l in lines) / count) if count else 0
            o_pcs_sum = sum(l.opening_pcs for l in lines)
            o_gross_sum = sum(l.opening_gross_weight for l in lines)
            o_net_sum = sum(l.opening_net_weight for l in lines)
            
            in_pcs_sum = sum(l.in_pcs for l in lines)
            in_gross_sum = sum(l.in_gross_weight for l in lines)
            in_net_sum = sum(l.in_net_weight for l in lines)
            
            out_pcs_sum = sum(l.out_pcs for l in lines)
            out_gross_sum = sum(l.out_gross_weight for l in lines)
            out_net_sum = sum(l.out_net_weight for l in lines)
            
            c_pcs_sum = sum(l.closing_pcs for l in lines)
            c_gross_sum = sum(l.closing_gross_weight for l in lines)
            c_net_sum = sum(l.closing_net_weight for l in lines)
            
            avg_inv_val = (o_gross_sum + c_gross_sum) / 2.0
            if avg_inv_val <= 0.0 and out_gross_sum > 0.0:
                avg_inv_val = out_gross_sum / 4.0
            no_of_days_val = lines[0].no_of_days if lines else 0
            min_stock_val = lines[0].min_stock_level if lines else 0.0
            turnover_val = (out_gross_sum / avg_inv_val) if avg_inv_val > 0.0001 else 0.0
            dio_val = round(no_of_days_val / turnover_val) if turnover_val > 0.0001 else (no_of_days_val if avg_inv_val > 0.0001 else 0)
            stock_gap_val = c_gross_sum - min_stock_val

            worksheet.write(row, 0, p_name, border_format)
            worksheet.write(row, 1, type_val, border_format)
            worksheet.write(row, 2, variety_val, border_format)
            worksheet.write(row, 3, design_val, border_format)
            worksheet.write(row, 4, size_val, border_format)
            worksheet.write(row, 5, stone_col_val, border_format)
            worksheet.write(row, 6, metal_col_val, border_format)
            worksheet.write(row, 7, ageing_avg, int_format)
            worksheet.write(row, 8, o_pcs_sum, pcs_format)
            worksheet.write(row, 9, o_gross_sum, num_format)
            worksheet.write(row, 10, o_net_sum, num_format)
            worksheet.write(row, 11, in_pcs_sum, pcs_format)
            worksheet.write(row, 12, in_gross_sum, num_format)
            worksheet.write(row, 13, in_net_sum, num_format)
            worksheet.write(row, 14, out_pcs_sum, pcs_format)
            worksheet.write(row, 15, out_gross_sum, num_format)
            worksheet.write(row, 16, out_net_sum, num_format)
            worksheet.write(row, 17, c_pcs_sum, pcs_format)
            worksheet.write(row, 18, c_gross_sum, num_format)
            worksheet.write(row, 19, c_net_sum, num_format)
            worksheet.write(row, 20, avg_inv_val, num_format)
            worksheet.write(row, 21, no_of_days_val, int_format)
            worksheet.write(row, 22, min_stock_val, num_format)
            worksheet.write(row, 23, turnover_val, dec2_format)
            worksheet.write(row, 24, dio_val, int_format)
            worksheet.write(row, 25, stock_gap_val, num_format)
            row += 1

        workbook.close()
        output.seek(0)

        filename = 'Stock_Summary_Product_Grouped.xlsx'
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename={filename};')
            ]
        )
