import io
from collections import defaultdict
from odoo import http
from odoo.http import request
from odoo.addons.em_metal_ledger.controllers.stock_summary_report_controller import StockSummaryReportController, _format_str

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

class StockSummaryProductWiseController(StockSummaryReportController):

    @http.route('/metal_ledger/export_stock_summary_product_wise', type='http', auth='user')
    def export_stock_summary_product_wise_report(self, start_date=None, end_date=None, branch_name=None, **kwargs):
        # Fetch report lines using fast SQL dictfetchall
        query = """
            SELECT 
                l.id, l.product_template_id, l.purity_id,
                l.opening_pcs, l.opening_gross_weight, l.opening_net_weight,
                l.in_pcs, l.in_gross_weight, l.in_net_weight,
                l.out_pcs, l.out_gross_weight, l.out_net_weight,
                l.closing_pcs, l.closing_gross_weight, l.closing_net_weight,
                l.average_inventory, l.turnover_ratio, l.no_of_days, l.dio, l.min_stock_level, l.stock_gap,
                pt.default_code as template_code, pt.name as template_name, gp.name as purity_name
            FROM stock_summary_report_line l
            LEFT JOIN product_template pt ON l.product_template_id = pt.id
            LEFT JOIN gold_purity gp ON l.purity_id = gp.id
            WHERE l.create_uid = %s
              AND (pt.is_vault_item IS NULL OR pt.is_vault_item = FALSE)
            ORDER BY l.id ASC
        """
        request.env.cr.execute(query, (request.env.user.id,))
        report_lines = request.env.cr.dictfetchall()
        
        if not report_lines:
            return "No report data found. Please generate the report from the wizard first."

        output = io.BytesIO()
        if not xlsxwriter:
            return "xlsxwriter library not found in the environment."

        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Product Wise Summary')

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
        worksheet.set_column('B:T', 15)  # Data columns

        # Title
        worksheet.merge_range('A1:T1', 'Stock Summary Report (Product Wise)', title_format)
        
        # Header Info
        worksheet.write('A2', f'Period: {start_date} to {end_date}', border_format)
        worksheet.write('A3', f'Branch: {branch_name}', border_format)

        # Headers
        headers = [
            'Product', 'Purity',
            'Opening PCs', 'Opening Gross', 'Opening Net',
            'In PCs', 'In Gross', 'In Net',
            'Out PCs', 'Out Gross', 'Out Net',
            'Closing PCs', 'Closing Gross', 'Closing Net',
            'Avg Inventory', 'No of Days', 'Min Stock', 'Turnover Ratio', 'DIO', 'Stock Gap'
        ]
        
        row = 5
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)

        grouped_data = defaultdict(list)
        for line in report_lines:
            p_code = _format_str(line.get('template_code'))
            t_name = (_format_str(line.get('template_name')) or 'Unknown').strip()
            p_name = f"[{p_code}] {t_name}" if p_code else t_name
            grouped_data[p_name].append(line)

        row += 1
        for p_name, lines in sorted(grouped_data.items(), key=lambda x: x[0]):
            count = len(lines)
            sample_line = lines[0]

            purities = []
            for l in lines:
                p = _format_str(l.get('purity_name'))
                if p and p not in purities:
                    purities.append(p)
            purity_val = ', '.join(purities) if purities else ''

            o_pcs_sum = sum(float(l.get('opening_pcs') or 0.0) for l in lines)
            o_gross_sum = sum(float(l.get('opening_gross_weight') or 0.0) for l in lines)
            o_net_sum = sum(float(l.get('opening_net_weight') or 0.0) for l in lines)
            
            in_pcs_sum = sum(float(l.get('in_pcs') or 0.0) for l in lines)
            in_gross_sum = sum(float(l.get('in_gross_weight') or 0.0) for l in lines)
            in_net_sum = sum(float(l.get('in_net_weight') or 0.0) for l in lines)
            
            out_pcs_sum = sum(float(l.get('out_pcs') or 0.0) for l in lines)
            out_gross_sum = sum(float(l.get('out_gross_weight') or 0.0) for l in lines)
            out_net_sum = sum(float(l.get('out_net_weight') or 0.0) for l in lines)
            
            c_pcs_sum = sum(float(l.get('closing_pcs') or 0.0) for l in lines)
            c_gross_sum = sum(float(l.get('closing_gross_weight') or 0.0) for l in lines)
            c_net_sum = sum(float(l.get('closing_net_weight') or 0.0) for l in lines)
            
            avg_inv_val = (o_gross_sum + c_gross_sum) / 2.0
            if avg_inv_val <= 0.0 and out_gross_sum > 0.0:
                avg_inv_val = out_gross_sum / 4.0
            no_of_days_val = lines[0].get('no_of_days') or 0 if lines else 0
            min_stock_val = sum(float(l.get('min_stock_level') or 0.0) for l in lines)
            turnover_val = (out_gross_sum / avg_inv_val) if avg_inv_val > 0.0001 else 0.0
            dio_val = round(no_of_days_val / turnover_val) if turnover_val > 0.0001 else (no_of_days_val if avg_inv_val > 0.0001 else 0)
            stock_gap_val = c_gross_sum - min_stock_val

            worksheet.write(row, 0, p_name, border_format)
            worksheet.write(row, 1, purity_val, border_format)
            worksheet.write(row, 2, o_pcs_sum, pcs_format)
            worksheet.write(row, 3, o_gross_sum, num_format)
            worksheet.write(row, 4, o_net_sum, num_format)
            worksheet.write(row, 5, in_pcs_sum, pcs_format)
            worksheet.write(row, 6, in_gross_sum, num_format)
            worksheet.write(row, 7, in_net_sum, num_format)
            worksheet.write(row, 8, out_pcs_sum, pcs_format)
            worksheet.write(row, 9, out_gross_sum, num_format)
            worksheet.write(row, 10, out_net_sum, num_format)
            worksheet.write(row, 11, c_pcs_sum, pcs_format)
            worksheet.write(row, 12, c_gross_sum, num_format)
            worksheet.write(row, 13, c_net_sum, num_format)
            worksheet.write(row, 14, avg_inv_val, num_format)
            worksheet.write(row, 15, no_of_days_val, int_format)
            worksheet.write(row, 16, min_stock_val, num_format)
            worksheet.write(row, 17, turnover_val, dec2_format)
            worksheet.write(row, 18, dio_val, int_format)
            worksheet.write(row, 19, stock_gap_val, num_format)
            row += 1

        workbook.close()
        output.seek(0)

        filename = 'Stock_Summary_Product_Wise.xlsx'
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename={filename};')
            ]
        )
