# -*- coding: utf-8 -*-
import io
import json
from datetime import datetime
import xlsxwriter
from odoo import http
from odoo.http import request

class BranchPaymentBalanceController(http.Controller):

    @http.route('/branch_payment_balance/export_xlsx', type='http', auth='user', methods=['GET'])
    def export_xlsx(self, branch_id=None, date_from=None, date_to=None, **kwargs):
        """Generates and downloads an Excel report of the Treasury & Payment Balance."""
        report_model = request.env['branch.payment.balance.report']
        data = report_model.get_balance_summary(branch_id=branch_id, date_from=date_from, date_to=date_to)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Payment Balances')

        # Formatting styles
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 16, 'font_color': '#1e293b', 'align': 'center'
        })
        subtitle_fmt = workbook.add_format({
            'font_size': 11, 'font_color': '#64748b', 'align': 'center'
        })
        badge_fmt = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_color': '#0369a1', 'bg_color': '#e0f2fe',
            'align': 'center', 'border': 1, 'border_color': '#bae6fd'
        })
        th_fmt = workbook.add_format({
            'bold': True, 'font_size': 11, 'font_color': '#ffffff', 'bg_color': '#0f172a',
            'align': 'center', 'valign': 'vcenter', 'border': 1
        })
        cat_header_fmt = workbook.add_format({
            'bold': True, 'font_size': 11, 'font_color': '#ffffff', 'bg_color': '#334155',
            'align': 'left', 'valign': 'vcenter', 'border': 1
        })
        row_fmt = workbook.add_format({
            'font_size': 10, 'border': 1, 'border_color': '#e2e8f0', 'valign': 'vcenter'
        })
        num_fmt = workbook.add_format({
            'font_size': 10, 'border': 1, 'border_color': '#e2e8f0', 'num_format': '#,##0.00', 'align': 'right'
        })
        bold_num_fmt = workbook.add_format({
            'bold': True, 'font_size': 10, 'border': 1, 'border_color': '#94a3b8', 'num_format': '#,##0.00', 'align': 'right', 'bg_color': '#f8fafc'
        })
        total_th_fmt = workbook.add_format({
            'bold': True, 'font_size': 12, 'font_color': '#ffffff', 'bg_color': '#1e3a8a',
            'align': 'left', 'valign': 'vcenter', 'border': 1
        })
        total_num_fmt = workbook.add_format({
            'bold': True, 'font_size': 12, 'font_color': '#ffffff', 'bg_color': '#1e3a8a',
            'num_format': '#,##0.00', 'align': 'right', 'border': 1
        })

        # Set column widths
        sheet.set_column('A:A', 5)
        sheet.set_column('B:B', 32)
        sheet.set_column('C:C', 16)
        sheet.set_column('D:D', 24)
        sheet.set_column('E:E', 20)
        sheet.set_column('F:F', 20)
        sheet.set_column('G:G', 20)
        sheet.set_column('H:H', 22)

        company_name = request.env.company.name or 'Nakshathra Jewellery'
        branch_name = data.get('selected_branch_name', 'All Branches')
        d_from = data.get('date_from', '')
        d_to = data.get('date_to', '')

        # Title Block
        sheet.merge_range('B2:H2', company_name, title_fmt)
        sheet.merge_range('B3:H3', 'TREASURY & PAYMENT BALANCE REPORT (BANK, CASH, CARD, UPI)', subtitle_fmt)
        sheet.merge_range('B4:H4', f"Branch: {branch_name}   |   Period: {d_from} to {d_to}", badge_fmt)

        # ── 1. Category Summary Section ──
        row = 6
        sheet.merge_range(row, 1, row, 7, '1. OVERALL CATEGORY SUMMARY', cat_header_fmt)
        row += 1

        headers = ['#', 'Payment Medium', 'Category', 'Branch', 'Opening Balance', 'Debit (Receipts)', 'Credit (Payments)', 'Closing Balance']
        for col_idx, h in enumerate(headers, start=1):
            sheet.write(row, col_idx, h, th_fmt)
        row += 1

        cats = data.get('categories', {})
        cat_order = ['bank', 'cash', 'card', 'upi']
        cat_index = 1

        for c_key in cat_order:
            c = cats.get(c_key, {})
            c_name = c.get('name', c_key.upper())
            sheet.write(row, 1, cat_index, row_fmt)
            sheet.write(row, 2, c_name, row_fmt)
            sheet.write(row, 3, c_key.upper(), row_fmt)
            sheet.write(row, 4, branch_name, row_fmt)
            sheet.write(row, 5, c.get('opening', 0.0), num_fmt)
            sheet.write(row, 6, c.get('debit', 0.0), num_fmt)
            sheet.write(row, 7, c.get('credit', 0.0), num_fmt)
            sheet.write(row, 8, c.get('closing', 0.0), num_fmt)
            row += 1
            cat_index += 1

        # Summary Total Row
        tot = data.get('total', {})
        sheet.write(row, 1, '', total_th_fmt)
        sheet.write(row, 2, 'TOTAL TREASURY POSITION', total_th_fmt)
        sheet.write(row, 3, '', total_th_fmt)
        sheet.write(row, 4, '', total_th_fmt)
        sheet.write(row, 5, tot.get('opening', 0.0), total_num_fmt)
        sheet.write(row, 6, tot.get('debit', 0.0), total_num_fmt)
        sheet.write(row, 7, tot.get('credit', 0.0), total_num_fmt)
        sheet.write(row, 8, tot.get('closing', 0.0), total_num_fmt)
        row += 3

        # ── 2. Detailed Journal / Account Breakdown ──
        sheet.merge_range(row, 1, row, 7, '2. DETAILED JOURNAL / ACCOUNT BREAKDOWN', cat_header_fmt)
        row += 1

        for col_idx, h in enumerate(headers, start=1):
            sheet.write(row, col_idx, h, th_fmt)
        row += 1

        detail_idx = 1
        for c_key in cat_order:
            c = cats.get(c_key, {})
            j_list = c.get('journals_list', [])
            if not j_list:
                continue

            for j in j_list:
                sheet.write(row, 1, detail_idx, row_fmt)
                sheet.write(row, 2, j.get('name', ''), row_fmt)
                sheet.write(row, 3, c_key.upper(), row_fmt)
                sheet.write(row, 4, j.get('branch_name', branch_name), row_fmt)
                sheet.write(row, 5, j.get('opening', 0.0), num_fmt)
                sheet.write(row, 6, j.get('debit', 0.0), num_fmt)
                sheet.write(row, 7, j.get('credit', 0.0), num_fmt)
                sheet.write(row, 8, j.get('closing', 0.0), num_fmt)
                row += 1
                detail_idx += 1

            # Category Subtotal
            sheet.write(row, 1, '', bold_num_fmt)
            sheet.write(row, 2, f"Subtotal {c.get('name', c_key.upper())}", bold_num_fmt)
            sheet.write(row, 3, '', bold_num_fmt)
            sheet.write(row, 4, '', bold_num_fmt)
            sheet.write(row, 5, c.get('opening', 0.0), bold_num_fmt)
            sheet.write(row, 6, c.get('debit', 0.0), bold_num_fmt)
            sheet.write(row, 7, c.get('credit', 0.0), bold_num_fmt)
            sheet.write(row, 8, c.get('closing', 0.0), bold_num_fmt)
            row += 2

        workbook.close()
        output.seek(0)

        filename = f"Payment_Balance_{branch_name.replace(' ', '_')}_{d_from}_to_{d_to}.xlsx"
        return http.send_file(
            output,
            filename=filename,
            as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

