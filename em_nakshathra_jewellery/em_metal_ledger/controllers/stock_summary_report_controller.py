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
        int_format = workbook.add_format({'border': 1, 'num_format': '#,##0'})
        dec2_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})

        total_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1})
        total_num_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'num_format': '#,##0.000'})
        total_pcs_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'num_format': '#,##0'})
        total_int_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'num_format': '#,##0'})
        total_dec2_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'num_format': '#,##0.00'})

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
        tot_o_pcs = tot_o_gross = tot_o_net = 0.0
        tot_in_pcs = tot_in_gross = tot_in_net = 0.0
        tot_out_pcs = tot_out_gross = tot_out_net = 0.0
        tot_c_pcs = tot_c_gross = tot_c_net = 0.0
        tot_avg_inv = tot_min_stock = tot_stock_gap = 0.0
        sample_no_days = 0

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

            o_pcs = line.get('opening_pcs') or 0
            o_gross = line.get('opening_gross_weight') or 0.0
            o_net = line.get('opening_net_weight') or 0.0
            in_pcs = line.get('in_pcs') or 0
            in_gross = line.get('in_gross_weight') or 0.0
            in_net = line.get('in_net_weight') or 0.0
            out_pcs = line.get('out_pcs') or 0
            out_gross = line.get('out_gross_weight') or 0.0
            out_net = line.get('out_net_weight') or 0.0
            c_pcs = line.get('closing_pcs') or 0
            c_gross = line.get('closing_gross_weight') or 0.0
            c_net = line.get('closing_net_weight') or 0.0
            avg_inv = line.get('average_inventory') or 0.0
            min_stock = line.get('min_stock_level') or 0.0
            stock_gap = line.get('stock_gap') or 0.0
            sample_no_days = line.get('no_of_days') or sample_no_days

            tot_o_pcs += o_pcs
            tot_o_gross += o_gross
            tot_o_net += o_net
            tot_in_pcs += in_pcs
            tot_in_gross += in_gross
            tot_in_net += in_net
            tot_out_pcs += out_pcs
            tot_out_gross += out_gross
            tot_out_net += out_net
            tot_c_pcs += c_pcs
            tot_c_gross += c_gross
            tot_c_net += c_net
            tot_avg_inv += avg_inv
            tot_min_stock += min_stock
            tot_stock_gap += stock_gap

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

            worksheet.write(row, 10, o_pcs, pcs_format)
            worksheet.write(row, 11, o_gross, num_format)
            worksheet.write(row, 12, o_net, num_format)
            worksheet.write(row, 13, in_pcs, pcs_format)
            worksheet.write(row, 14, in_gross, num_format)
            worksheet.write(row, 15, in_net, num_format)
            worksheet.write(row, 16, out_pcs, pcs_format)
            worksheet.write(row, 17, out_gross, num_format)
            worksheet.write(row, 18, out_net, num_format)
            worksheet.write(row, 19, c_pcs, pcs_format)
            worksheet.write(row, 20, c_gross, num_format)
            worksheet.write(row, 21, c_net, num_format)
            worksheet.write(row, 22, avg_inv, num_format)
            worksheet.write(row, 23, line.get('turnover_ratio') or 0.0, num_format)
            worksheet.write(row, 24, line.get('no_of_days') or 0, border_format)
            worksheet.write(row, 25, line.get('dio') or 0, border_format)
            worksheet.write(row, 26, min_stock, num_format)
            worksheet.write(row, 27, stock_gap, num_format)
            row += 1

        # TOTAL Row
        tot_turnover = (tot_out_gross / tot_avg_inv) if tot_avg_inv > 0.0001 else 0.0
        tot_dio = round(sample_no_days / tot_turnover) if tot_turnover > 0.0001 else (sample_no_days if tot_avg_inv > 0.0001 else 0)

        worksheet.write(row, 0, 'TOTAL', total_format)
        for col_idx in range(1, 10):
            worksheet.write(row, col_idx, '', total_format)

        worksheet.write(row, 10, tot_o_pcs, total_pcs_format)
        worksheet.write(row, 11, tot_o_gross, total_num_format)
        worksheet.write(row, 12, tot_o_net, total_num_format)
        worksheet.write(row, 13, tot_in_pcs, total_pcs_format)
        worksheet.write(row, 14, tot_in_gross, total_num_format)
        worksheet.write(row, 15, tot_in_net, total_num_format)
        worksheet.write(row, 16, tot_out_pcs, total_pcs_format)
        worksheet.write(row, 17, tot_out_gross, total_num_format)
        worksheet.write(row, 18, tot_out_net, total_num_format)
        worksheet.write(row, 19, tot_c_pcs, total_pcs_format)
        worksheet.write(row, 20, tot_c_gross, total_num_format)
        worksheet.write(row, 21, tot_c_net, total_num_format)
        worksheet.write(row, 22, tot_avg_inv, total_num_format)
        worksheet.write(row, 23, tot_turnover, total_dec2_format)
        worksheet.write(row, 24, sample_no_days, total_int_format)
        worksheet.write(row, 25, tot_dio, total_int_format)
        worksheet.write(row, 26, tot_min_stock, total_num_format)
        worksheet.write(row, 27, tot_stock_gap, total_num_format)

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
                pp.default_code, pt.name as template_name, gp.name as purity_name,
                COALESCE(l.product_template_id, pp.product_tmpl_id) as actual_tmpl_id
            FROM stock_summary_report_line l
            LEFT JOIN product_product pp ON l.product_id = pp.id
            LEFT JOIN product_template pt ON pt.id = COALESCE(l.product_template_id, pp.product_tmpl_id)
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
        worksheet = workbook.add_worksheet('Product Summary')

        # Formats
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center'})
        border_format = workbook.add_format({'border': 1})
        num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.000'})
        pcs_format = workbook.add_format({'border': 1, 'num_format': '#,##0'})
        int_format = workbook.add_format({'border': 1, 'num_format': '#,##0'})
        dec2_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})

        total_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1})
        total_num_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'num_format': '#,##0.000'})
        total_pcs_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'num_format': '#,##0'})
        total_int_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'num_format': '#,##0'})
        total_dec2_format = workbook.add_format({'bold': True, 'bg_color': '#FFF2CC', 'border': 1, 'num_format': '#,##0.00'})

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

        # Group strictly by Product Template so each product appears in a single line
        grouped_data = defaultdict(list)
        for line in report_lines:
            tmpl_id = line.get('actual_tmpl_id') or line.get('product_template_id')
            if tmpl_id:
                p_key = tmpl_id
            elif line.get('product_id'):
                p_key = ('product', line['product_id'])
            else:
                p_key = ('line', line['id'])
            grouped_data[p_key].append(line)

        def _get_joined(lines, field_name):
            vals = []
            for l in lines:
                v = _format_str(l.get(field_name))
                if v and v != 'None' and v not in vals:
                    vals.append(v)
            return ', '.join(vals) if vals else ''

        row += 1
        tot_o_pcs = tot_o_gross = tot_o_net = 0.0
        tot_in_pcs = tot_in_gross = tot_in_net = 0.0
        tot_out_pcs = tot_out_gross = tot_out_net = 0.0
        tot_c_pcs = tot_c_gross = tot_c_net = 0.0
        tot_avg_inv = tot_min_stock = tot_stock_gap = 0.0
        sample_no_days = 0

        for p_key, lines in grouped_data.items():
            count = len(lines)
            sample_line = lines[0]
            
            p_code = ''
            for l in lines:
                if l.get('default_code'):
                    p_code = _format_str(l.get('default_code'))
                    break
            t_name = _format_str(sample_line.get('template_name')) or 'Unknown'
            p_name = f"[{p_code}] {t_name}" if p_code else t_name
            
            type_val = _get_joined(lines, 'type_value')
            variety_val = _get_joined(lines, 'variety_value')
            design_val = _get_joined(lines, 'design_value')
            size_val = _get_joined(lines, 'size_value')
            stone_col_val = _get_joined(lines, 'stone_colour_value')
            metal_col_val = _get_joined(lines, 'metal_colour_value')
            purity_val = _get_joined(lines, 'purity_name')

            total_c_pcs_line = sum(l.get('closing_pcs') or 0 for l in lines)
            if total_c_pcs_line > 0:
                ageing_avg = round(sum((l.get('ageing') or 0) * (l.get('closing_pcs') or 0) for l in lines) / total_c_pcs_line)
            else:
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
            sample_no_days = no_of_days_val
            
            # Unique min stock values across lines for this product
            unique_min_stocks = set(l.get('min_stock_level') or 0.0 for l in lines)
            min_stock_val = sum(unique_min_stocks) if unique_min_stocks else 0.0

            turnover_val = (out_gross_sum / avg_inv_val) if avg_inv_val > 0.0001 else 0.0
            dio_val = round(no_of_days_val / turnover_val) if turnover_val > 0.0001 else (no_of_days_val if avg_inv_val > 0.0001 else 0)
            stock_gap_val = c_gross_sum - min_stock_val

            tot_o_pcs += o_pcs_sum
            tot_o_gross += o_gross_sum
            tot_o_net += o_net_sum
            tot_in_pcs += in_pcs_sum
            tot_in_gross += in_gross_sum
            tot_in_net += in_net_sum
            tot_out_pcs += out_pcs_sum
            tot_out_gross += out_gross_sum
            tot_out_net += out_net_sum
            tot_c_pcs += c_pcs_sum
            tot_c_gross += c_gross_sum
            tot_c_net += c_net_sum
            tot_avg_inv += avg_inv_val
            tot_min_stock += min_stock_val
            tot_stock_gap += stock_gap_val

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

        # TOTAL Row
        tot_turnover = (tot_out_gross / tot_avg_inv) if tot_avg_inv > 0.0001 else 0.0
        tot_dio = round(sample_no_days / tot_turnover) if tot_turnover > 0.0001 else (sample_no_days if tot_avg_inv > 0.0001 else 0)

        worksheet.write(row, 0, 'TOTAL', total_format)
        for col_idx in range(1, 9):
            worksheet.write(row, col_idx, '', total_format)

        worksheet.write(row, 9, tot_o_pcs, total_pcs_format)
        worksheet.write(row, 10, tot_o_gross, total_num_format)
        worksheet.write(row, 11, tot_o_net, total_num_format)
        worksheet.write(row, 12, tot_in_pcs, total_pcs_format)
        worksheet.write(row, 13, tot_in_gross, total_num_format)
        worksheet.write(row, 14, tot_in_net, total_num_format)
        worksheet.write(row, 15, tot_out_pcs, total_pcs_format)
        worksheet.write(row, 16, tot_out_gross, total_num_format)
        worksheet.write(row, 17, tot_out_net, total_num_format)
        worksheet.write(row, 18, tot_c_pcs, total_pcs_format)
        worksheet.write(row, 19, tot_c_gross, total_num_format)
        worksheet.write(row, 20, tot_c_net, total_num_format)
        worksheet.write(row, 21, tot_avg_inv, total_num_format)
        worksheet.write(row, 22, sample_no_days, total_int_format)
        worksheet.write(row, 23, tot_min_stock, total_num_format)
        worksheet.write(row, 24, tot_turnover, total_dec2_format)
        worksheet.write(row, 25, tot_dio, total_int_format)
        worksheet.write(row, 26, tot_stock_gap, total_num_format)

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
