import io
from collections import defaultdict
from odoo import http
from odoo.http import request

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

def _format_str(val):
    if not val:
        return ''
    if isinstance(val, dict):
        return val.get('en_US') or (next(iter(val.values())) if val else '')
    return str(val)

class StockSummaryReportController(http.Controller):

    @http.route('/metal_ledger/export_stock_summary', type='http', auth='user')
    def export_stock_summary_report(self, start_date=None, end_date=None, branch_name=None, **kwargs):
        # Fetch report lines using fast SQL dictfetchall to eliminate ORM cache memory overhead
        query = """
            SELECT 
                l.id, l.product_id, l.product_template_id, l.label_id, l.type_value, l.variety_value,
                l.design_value, l.size_value, l.stone_colour_value, l.metal_colour_value, l.purity_id,
                l.ageing, l.opening_pcs, l.opening_gross_weight, l.opening_net_weight,
                l.in_pcs, l.in_gross_weight, l.in_net_weight,
                l.out_pcs, l.out_gross_weight, l.out_net_weight,
                l.closing_pcs, l.closing_gross_weight, l.closing_net_weight,
                l.average_inventory, l.turnover_ratio, l.no_of_days, l.dio, l.min_stock_level, l.stock_gap,
                pp.default_code, pt.name as template_name, pl.name as label_name, gp.name as purity_name
            FROM stock_summary_report_line l
            LEFT JOIN product_product pp ON l.product_id = pp.id
            LEFT JOIN product_template pt ON (l.product_template_id = pt.id OR pp.product_tmpl_id = pt.id)
            LEFT JOIN product_label pl ON l.label_id = pl.id
            LEFT JOIN gold_purity gp ON l.purity_id = gp.id
            WHERE l.create_uid = %s
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
            p_code = _format_str(line.get('default_code'))
            t_name = _format_str(line.get('template_name'))
            p_base = f"[{p_code}] {t_name}" if p_code else t_name

            attr_parts = [
                _format_str(line.get('type_value')) or 'None',
                _format_str(line.get('variety_value')) or 'None',
                _format_str(line.get('design_value')) or 'None',
                _format_str(line.get('size_value')) or 'None',
                _format_str(line.get('stone_colour_value')) or 'None',
                _format_str(line.get('metal_colour_value')) or 'None',
            ]
            if line.get('product_id') or any(p != 'None' for p in attr_parts):
                var_suffix = f" ({', '.join(attr_parts)})"
            else:
                var_suffix = ""
            p_display = f"{p_base}{var_suffix}"

            worksheet.write(row, 0, p_display, border_format)
            worksheet.write(row, 1, _format_str(line.get('label_name')), border_format)
            worksheet.write(row, 2, _format_str(line.get('type_value')), border_format)
            worksheet.write(row, 3, _format_str(line.get('variety_value')), border_format)
            worksheet.write(row, 4, _format_str(line.get('design_value')), border_format)
            worksheet.write(row, 5, _format_str(line.get('size_value')), border_format)
            worksheet.write(row, 6, _format_str(line.get('stone_colour_value')), border_format)
            worksheet.write(row, 7, _format_str(line.get('metal_colour_value')), border_format)
            worksheet.write(row, 8, _format_str(line.get('purity_name')), border_format)
            
            ageing_val = line.get('ageing') or 0
            worksheet.write(row, 9, ageing_val, border_format)

            worksheet.write(row, 10, line.get('opening_pcs') or 0, pcs_format)
            worksheet.write(row, 11, line.get('opening_gross_weight') or 0.0, num_format)
            worksheet.write(row, 12, line.get('opening_net_weight') or 0.0, num_format)
            worksheet.write(row, 13, line.get('in_pcs') or 0, pcs_format)
            worksheet.write(row, 14, line.get('in_gross_weight') or 0.0, num_format)
            worksheet.write(row, 15, line.get('in_net_weight') or 0.0, num_format)
            worksheet.write(row, 16, line.get('out_pcs') or 0, pcs_format)
            worksheet.write(row, 17, line.get('out_gross_weight') or 0.0, num_format)
            worksheet.write(row, 18, line.get('out_net_weight') or 0.0, num_format)
            worksheet.write(row, 19, line.get('closing_pcs') or 0, pcs_format)
            worksheet.write(row, 20, line.get('closing_gross_weight') or 0.0, num_format)
            worksheet.write(row, 21, line.get('closing_net_weight') or 0.0, num_format)
            worksheet.write(row, 22, line.get('average_inventory') or 0.0, num_format)
            worksheet.write(row, 23, line.get('turnover_ratio') or 0.0, num_format)
            worksheet.write(row, 24, line.get('no_of_days') or 0, border_format)
            worksheet.write(row, 25, line.get('dio') or 0, border_format)
            worksheet.write(row, 26, line.get('min_stock_level') or 0.0, num_format)
            worksheet.write(row, 27, line.get('stock_gap') or 0.0, num_format)
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
        # Fetch report lines using fast SQL dictfetchall
        query = """
            SELECT 
                l.id, l.product_id, l.product_template_id, l.type_value, l.variety_value,
                l.design_value, l.size_value, l.stone_colour_value, l.metal_colour_value, l.purity_id,
                l.ageing, l.opening_pcs, l.opening_gross_weight, l.opening_net_weight,
                l.in_pcs, l.in_gross_weight, l.in_net_weight,
                l.out_pcs, l.out_gross_weight, l.out_net_weight,
                l.closing_pcs, l.closing_gross_weight, l.closing_net_weight,
                l.average_inventory, l.turnover_ratio, l.no_of_days, l.dio, l.min_stock_level, l.stock_gap,
                pp.default_code, pt.name as template_name, gp.name as purity_name
            FROM stock_summary_report_line l
            LEFT JOIN product_product pp ON l.product_id = pp.id
            LEFT JOIN product_template pt ON (l.product_template_id = pt.id OR pp.product_tmpl_id = pt.id)
            LEFT JOIN gold_purity gp ON l.purity_id = gp.id
            WHERE l.create_uid = %s
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

        # Headers with 6 Variant columns + Purity
        headers = [
            'Product', 'Type', 'Variety', 'Design', 'Size', 'Stone Colour', 'Metal Colour', 'Purity',
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

        grouped_data = defaultdict(list)
        for line in report_lines:
            if line.get('product_id'):
                p_key = ('product', line['product_id'])
            elif line.get('product_template_id'):
                p_key = ('template', line['product_template_id'])
            else:
                p_key = ('unknown', line['id'])
            grouped_data[p_key].append(line)

        row += 1
        for p_key, lines in grouped_data.items():
            count = len(lines)
            sample_line = lines[0]
            p_code = _format_str(sample_line.get('default_code'))
            t_name = _format_str(sample_line.get('template_name')) or 'Unknown'
            p_base = f"[{p_code}] {t_name}" if p_code else t_name
            
            type_val = _format_str(sample_line.get('type_value'))
            variety_val = _format_str(sample_line.get('variety_value'))
            design_val = _format_str(sample_line.get('design_value'))
            size_val = _format_str(sample_line.get('size_value'))
            stone_col_val = _format_str(sample_line.get('stone_colour_value'))
            metal_col_val = _format_str(sample_line.get('metal_colour_value'))
            purity_val = _format_str(sample_line.get('purity_name'))

            attr_parts = [
                type_val or 'None',
                variety_val or 'None',
                design_val or 'None',
                size_val or 'None',
                stone_col_val or 'None',
                metal_col_val or 'None',
            ]
            if sample_line.get('product_id') or any(p != 'None' for p in attr_parts):
                var_suffix = f" ({', '.join(attr_parts)})"
            else:
                var_suffix = ""
            p_name = f"{p_base}{var_suffix}"
            
            ageing_avg = round(sum(l.get('ageing') or 0 for l in lines) / count) if count else 0
            o_pcs_sum = sum(l.get('opening_pcs') or 0 for l in lines)
            o_gross_sum = sum(l.get('opening_gross_weight') or 0.0 for l in lines)
            o_net_sum = sum(l.get('opening_net_weight') or 0.0 for l in lines)
            
            in_pcs_sum = sum(l.get('in_pcs') or 0 for l in lines)
            in_gross_sum = sum(l.get('in_gross_weight') or 0.0 for l in lines)
            in_net_sum = sum(l.get('in_net_weight') or 0.0 for l in lines)
            
            out_pcs_sum = sum(l.get('out_pcs') or 0 for l in lines)
            out_gross_sum = sum(l.get('out_gross_weight') or 0.0 for l in lines)
            out_net_sum = sum(l.get('out_net_weight') or 0.0 for l in lines)
            
            c_pcs_sum = sum(l.get('closing_pcs') or 0 for l in lines)
            c_gross_sum = sum(l.get('closing_gross_weight') or 0.0 for l in lines)
            c_net_sum = sum(l.get('closing_net_weight') or 0.0 for l in lines)
            
            avg_inv_val = (o_gross_sum + c_gross_sum) / 2.0
            if avg_inv_val <= 0.0 and out_gross_sum > 0.0:
                avg_inv_val = out_gross_sum / 4.0
            no_of_days_val = lines[0].get('no_of_days') or 0 if lines else 0
            min_stock_val = lines[0].get('min_stock_level') or 0.0 if lines else 0.0
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
            worksheet.write(row, 7, purity_val, border_format)
            worksheet.write(row, 8, ageing_avg, int_format)
            worksheet.write(row, 9, o_pcs_sum, pcs_format)
            worksheet.write(row, 10, o_gross_sum, num_format)
            worksheet.write(row, 11, o_net_sum, num_format)
            worksheet.write(row, 12, in_pcs_sum, pcs_format)
            worksheet.write(row, 13, in_gross_sum, num_format)
            worksheet.write(row, 14, in_net_sum, num_format)
            worksheet.write(row, 15, out_pcs_sum, pcs_format)
            worksheet.write(row, 16, out_gross_sum, num_format)
            worksheet.write(row, 17, out_net_sum, num_format)
            worksheet.write(row, 18, c_pcs_sum, pcs_format)
            worksheet.write(row, 19, c_gross_sum, num_format)
            worksheet.write(row, 20, c_net_sum, num_format)
            worksheet.write(row, 21, avg_inv_val, num_format)
            worksheet.write(row, 22, no_of_days_val, int_format)
            worksheet.write(row, 23, min_stock_val, num_format)
            worksheet.write(row, 24, turnover_val, dec2_format)
            worksheet.write(row, 25, dio_val, int_format)
            worksheet.write(row, 26, stock_gap_val, num_format)
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
