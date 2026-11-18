# -*- coding: utf-8 -*-
import io
from odoo import http, _
from odoo.http import request

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class BranchLabelVerificationController(http.Controller):

    @http.route('/branch_label_verification/export_xlsx', type='http', auth='user')
    def export_verification_xlsx(self, id, report_type=None, **kwargs):
        audit = request.env['branch.label.verification'].browse(int(id))
        if not audit.exists():
            return request.not_found()

        audit.check_access_rights('read')
        audit.check_access_rule('read')
        audit = audit.sudo()

        # Enforce security: Branch Manager sees full report; Billing users get blinded report
        is_manager = request.env.user.has_group(
            'branch_label_verification.group_branch_label_verification_branch_manager'
        ) or request.env.is_superuser()

        if not is_manager:
            report_type = 'billing'
        else:
            report_type = report_type or kwargs.get('report_type') or 'manager'

        if not xlsxwriter:
            return "xlsxwriter library not found in the environment. Please contact administrator."

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Styling
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center'
        })
        title_format = workbook.add_format({'bold': True, 'font_size': 14})
        match_format = workbook.add_format({'bg_color': '#C6EFCE', 'border': 1})
        mismatch_format = workbook.add_format({'bg_color': '#FFC7CE', 'border': 1})
        status_match_format = workbook.add_format({'bg_color': '#C6EFCE', 'border': 1, 'align': 'center'})
        status_mismatch_format = workbook.add_format({'bg_color': '#FFC7CE', 'border': 1, 'align': 'center'})
        border_format = workbook.add_format({'border': 1})

        # ==========================================
        # Sheet 1: Stock Check Report
        # ==========================================
        worksheet = workbook.add_worksheet('Stock Check Report')

        if report_type == 'manager':
            worksheet.set_column('A:A', 40)  # Product
            worksheet.set_column('B:I', 15)  # Other columns
        else:
            worksheet.set_column('A:A', 25)  # Label
            worksheet.set_column('B:C', 18)  # Counted Labels, Counted Weight

        # Header Metadata
        worksheet.write('A1', f'Weekly Stock Check ({report_type.capitalize()})', title_format)
        worksheet.write('A2', f'Reference: {audit.name or ""}')
        worksheet.write('A3', f'Branch: {audit.branch_id.name or ""}')
        locations_str = ", ".join(audit.location_ids.mapped('name')) if audit.location_ids else 'All'
        worksheet.write('A4', f'Location: {locations_str}')
        worksheet.write('A5', f'Date: {audit.date or ""}')

        # Table Headers (Row 8)
        row = 7
        col = 0
        if report_type == 'manager':
            headers = [
                'Product', 'Label', 'System Qty', 'System Weight',
                'Counted Labels', 'Counted Weight', 'Diff Label', 'Diff Weight', 'Status'
            ]
        else:
            headers = ['Label', 'Counted Labels', 'Counted Weight']

        for header in headers:
            worksheet.write(row, col, header, header_format)
            col += 1

        # Only include actual label verification lines (exclude vault, old gold, and diamond og)
        eligible_lines = audit.line_ids.filtered(
            lambda l: not l.is_vault_item and not l.is_old_gold and not l.is_diamond_og
        )
        items = []
        for line in eligible_lines:
            items.append({
                'tmpl_name': line.product_tmpl_id.name or '',
                'product_name': line.product_id.display_name or line.product_tmpl_id.name or '',
                'label_name': line.label_id.name or line.name or '',
                'system_qty': int(line.system_qty),
                'system_weight': round(line.system_weight or line.sale_gross_weight or 0.0, 2),
                'manual_qty': int(line.manual_qty),
                'manual_weight': round(line.manual_weight or line.manual_total_weight or 0.0, 2),
                'difference_qty': int(line.difference_qty),
                'difference_weight': round(line.difference_weight or 0.0, 2),
                'is_matched': bool(line.is_matched),
            })

        # Sort items by product template name, then product, then label
        items.sort(key=lambda x: (x['tmpl_name'].upper(), x['product_name'].upper(), x['label_name'].upper()))

        row = 8
        for item in items:
            col = 0
            if report_type == 'manager':
                current_format = match_format if item['is_matched'] else mismatch_format if item['manual_qty'] != 0 else border_format
                worksheet.write(row, col, item['product_name'], current_format)
                worksheet.write(row, col + 1, item['label_name'], current_format)
                worksheet.write(row, col + 2, item['system_qty'], current_format)
                worksheet.write(row, col + 3, item['system_weight'], current_format)
                worksheet.write(row, col + 4, item['manual_qty'], current_format)
                worksheet.write(row, col + 5, item['manual_weight'], current_format)
                worksheet.write(row, col + 6, item['difference_qty'], current_format)
                worksheet.write(row, col + 7, item['difference_weight'], current_format)
                worksheet.write(row, col + 8, 'Matched' if item['is_matched'] else 'Mismatch', current_format)
            else:
                worksheet.write(row, col, item['label_name'], border_format)
                worksheet.write(row, col + 1, item['manual_qty'], border_format)
                worksheet.write(row, col + 2, item['manual_weight'], border_format)
            row += 1

        # ==========================================
        # Sheet 2: Template Summary
        # ==========================================
        summary_sheet = workbook.add_worksheet('Template Summary')
        summary_sheet.set_column('A:A', 40)
        if report_type == 'manager':
            summary_sheet.set_column('B:H', 18)
        else:
            summary_sheet.set_column('B:D', 20)

        summary_sheet.write('A1', 'Product Template Summary', title_format)
        summary_sheet.write('A2', f'Reference: {audit.name or ""}')
        summary_sheet.write('A3', f'Date: {audit.date or ""}')

        row = 5
        col = 0
        if report_type == 'manager':
            summary_headers = [
                'Product Template', 'Total Labels', 'Total Weight',
                'Counted Labels', 'Counted Weight', 'Diff Label', 'Diff Weight', 'Counted Label Match'
            ]
        else:
            summary_headers = ['Product Template', 'Counted Labels', 'Counted Weight', 'Counted Label Match']

        for header in summary_headers:
            summary_sheet.write(row, col, header, header_format)
            col += 1

        sorted_summaries = audit.template_summary_ids.sorted(key=lambda s: (s.product_tmpl_id.name or '').upper())
        row = 6
        for summary in sorted_summaries:
            col = 0
            is_match = bool(summary.is_matched)
            match_status = 'Match' if is_match else 'Mismatch'
            match_fmt = status_match_format if is_match else status_mismatch_format

            if report_type == 'manager':
                summary_sheet.write(row, col, summary.product_tmpl_id.name or '', border_format)
                summary_sheet.write(row, col + 1, int(summary.system_qty), border_format)
                summary_sheet.write(row, col + 2, round(summary.system_weight or 0.0, 2), border_format)
                summary_sheet.write(row, col + 3, int(summary.manual_qty), border_format)
                summary_sheet.write(row, col + 4, round(summary.manual_weight or 0.0, 2), border_format)
                summary_sheet.write(row, col + 5, int(summary.difference_qty), border_format)
                summary_sheet.write(row, col + 6, round(summary.difference_weight or 0.0, 2), border_format)
                summary_sheet.write(row, col + 7, match_status, match_fmt)
            else:
                summary_sheet.write(row, col, summary.product_tmpl_id.name or '', border_format)
                summary_sheet.write(row, col + 1, int(summary.manual_qty), border_format)
                summary_sheet.write(row, col + 2, round(summary.manual_weight or 0.0, 2), border_format)
                summary_sheet.write(row, col + 3, match_status, match_fmt)
            row += 1

        workbook.close()
        output.seek(0)

        filename = f'Stock_Check_{report_type}_{audit.name.replace("/", "_")}.xlsx'
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename={filename};')
            ]
        )
