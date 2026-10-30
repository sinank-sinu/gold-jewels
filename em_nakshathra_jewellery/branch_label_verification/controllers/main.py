# -*- coding: utf-8 -*-
import base64
from io import BytesIO
import xlsxwriter

from odoo import http, _
from odoo.http import request


class BranchLabelVerificationController(http.Controller):

    @http.route('/branch_label_verification/export_xlsx', type='http', auth='user')
    def export_verification_xlsx(self, id, **kwargs):
        audit = request.env['branch.label.verification'].browse(int(id))
        if not audit.exists():
            return request.not_found()

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Styling
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 16, 'font_color': '#FFFFFF',
            'bg_color': '#1E293B', 'align': 'center', 'valign': 'vcenter'
        })
        meta_label_fmt = workbook.add_format({
            'bold': True, 'font_size': 10, 'bg_color': '#F1F5F9', 'border': 1
        })
        meta_val_fmt = workbook.add_format({
            'font_size': 10, 'border': 1
        })
        kpi_title_fmt = workbook.add_format({
            'bold': True, 'font_size': 10, 'align': 'center', 'bg_color': '#E2E8F0', 'border': 1
        })
        kpi_val_fmt = workbook.add_format({
            'bold': True, 'font_size': 13, 'align': 'center', 'border': 1
        })
        th_fmt = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_color': '#FFFFFF',
            'bg_color': '#0F172A', 'align': 'center', 'valign': 'vcenter', 'border': 1
        })
        cell_fmt = workbook.add_format({
            'font_size': 10, 'border': 1, 'valign': 'vcenter'
        })
        num_fmt = workbook.add_format({
            'font_size': 10, 'border': 1, 'align': 'right', 'num_format': '#,##0.000'
        })
        center_fmt = workbook.add_format({
            'font_size': 10, 'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        badge_ver = workbook.add_format({
            'font_size': 10, 'bold': True, 'font_color': '#065F46', 'bg_color': '#D1FAE5', 'align': 'center', 'border': 1
        })
        badge_pen = workbook.add_format({
            'font_size': 10, 'bold': True, 'font_color': '#92400E', 'bg_color': '#FEF3C7', 'align': 'center', 'border': 1
        })
        badge_mis = workbook.add_format({
            'font_size': 10, 'bold': True, 'font_color': '#991B1B', 'bg_color': '#FEE2E2', 'align': 'center', 'border': 1
        })
        badge_ext = workbook.add_format({
            'font_size': 10, 'bold': True, 'font_color': '#5B21B6', 'bg_color': '#EDE9FE', 'align': 'center', 'border': 1
        })

        # ==========================================
        # Sheet 1: Summary Dashboard
        # ==========================================
        ws_sum = workbook.add_worksheet('Audit Summary')
        ws_sum.set_column('A:A', 5)
        ws_sum.set_column('B:C', 22)
        ws_sum.set_column('D:E', 22)
        ws_sum.set_column('F:G', 22)

        # Title
        ws_sum.merge_range('B2:G3', f"BRANCH LABEL VERIFICATION AUDIT REPORT — {audit.branch_id.name or 'Branch'}", title_fmt)

        # Meta Details
        ws_sum.write('B5', 'Audit Reference:', meta_label_fmt)
        ws_sum.write('C5', audit.name or '', meta_val_fmt)
        ws_sum.write('D5', 'Verification Date:', meta_label_fmt)
        ws_sum.write('E5', str(audit.date or ''), meta_val_fmt)
        ws_sum.write('F5', 'Status:', meta_label_fmt)
        ws_sum.write('G5', (audit.state or '').upper(), meta_val_fmt)

        ws_sum.write('B6', 'Branch:', meta_label_fmt)
        ws_sum.write('C6', audit.branch_id.name or '', meta_val_fmt)
        ws_sum.write('D6', 'Auditor / Verifier:', meta_label_fmt)
        ws_sum.write('E6', audit.user_id.name or '', meta_val_fmt)
        ws_sum.write('F6', 'Scope / Filter:', meta_label_fmt)
        ws_sum.write('G6', dict(audit._fields['label_filter'].selection).get(audit.label_filter, audit.label_filter), meta_val_fmt)

        # KPI Blocks
        ws_sum.write('B8', 'TOTAL EXPECTED', kpi_title_fmt)
        ws_sum.write('B9', f"{audit.total_expected_count} Items", kpi_val_fmt)
        ws_sum.write('B10', f"{audit.total_expected_gross_weight:.3f} g", meta_val_fmt)

        ws_sum.write('C8', 'VERIFIED LABELS', kpi_title_fmt)
        ws_sum.write('C9', f"{audit.verified_count} Items", kpi_val_fmt)
        ws_sum.write('C10', f"{audit.verified_gross_weight:.3f} g", meta_val_fmt)

        ws_sum.write('D8', 'PENDING ITEMS', kpi_title_fmt)
        ws_sum.write('D9', f"{audit.pending_count} Items", kpi_val_fmt)
        ws_sum.write('D10', f"{audit.pending_gross_weight:.3f} g", meta_val_fmt)

        ws_sum.write('E8', 'MISSING LABELS', kpi_title_fmt)
        ws_sum.write('E9', f"{audit.missing_count} Items", kpi_val_fmt)
        ws_sum.write('E10', f"{audit.missing_gross_weight:.3f} g", meta_val_fmt)

        ws_sum.write('F8', 'EXTRA / MISMATCH', kpi_title_fmt)
        ws_sum.write('F9', f"{audit.extra_count} Items", kpi_val_fmt)
        ws_sum.write('F10', f"{audit.extra_gross_weight:.3f} g", meta_val_fmt)

        ws_sum.write('G8', 'AUDIT PROGRESS', kpi_title_fmt)
        ws_sum.write('G9', f"{audit.progress_rate:.1f}%", kpi_val_fmt)
        ws_sum.write('G10', 'Completion Rate', meta_val_fmt)

        # Notes
        ws_sum.write('B12', 'Audit Remarks:', meta_label_fmt)
        ws_sum.merge_range('C12:G13', audit.notes or 'None', meta_val_fmt)

        # Signatures
        ws_sum.write('B16', 'Branch Manager Signature', meta_label_fmt)
        ws_sum.write('D16', 'Auditor Signature', meta_label_fmt)
        ws_sum.write('F16', 'Stock In-Charge Signature', meta_label_fmt)

        # ==========================================
        # Sheet 2: All Verification Lines
        # ==========================================
        ws_lines = workbook.add_worksheet('All Labels')
        headers = [
            'Sl', 'Status', 'Label Ref', 'Barcode', 'Product', 'Category',
            'Purity', 'Location', 'Gross Wt (g)', 'Net Wt (g)', 'Verified At', 'Verified By', 'Remarks'
        ]
        ws_lines.set_column('A:A', 6)
        ws_lines.set_column('B:B', 15)
        ws_lines.set_column('C:D', 18)
        ws_lines.set_column('E:E', 28)
        ws_lines.set_column('F:H', 18)
        ws_lines.set_column('I:J', 14)
        ws_lines.set_column('K:L', 20)
        ws_lines.set_column('M:M', 25)

        for col, h in enumerate(headers):
            ws_lines.write(0, col, h, th_fmt)

        row = 1
        for idx, line in enumerate(audit.line_ids, 1):
            st = line.status
            fmt_st = badge_ver if st == 'verified' else (badge_pen if st == 'pending' else (badge_mis if st == 'missing' else badge_ext))
            st_label = dict(line._fields['status'].selection).get(st, st)

            ws_lines.write(row, 0, idx, center_fmt)
            ws_lines.write(row, 1, st_label, fmt_st)
            ws_lines.write(row, 2, line.name or '', cell_fmt)
            ws_lines.write(row, 3, line.barcode or '', cell_fmt)
            ws_lines.write(row, 4, line.product_id.display_name or '', cell_fmt)
            ws_lines.write(row, 5, line.categ_id.name or '', cell_fmt)
            ws_lines.write(row, 6, line.purity_id.name or '', cell_fmt)
            ws_lines.write(row, 7, line.location_id.name or '', cell_fmt)
            ws_lines.write(row, 8, line.sale_gross_weight or 0.0, num_fmt)
            ws_lines.write(row, 9, line.sale_net_weight or 0.0, num_fmt)
            ws_lines.write(row, 10, str(line.verified_datetime or ''), center_fmt)
            ws_lines.write(row, 11, line.verified_by.name or '', cell_fmt)
            ws_lines.write(row, 12, line.notes or '', cell_fmt)
            row += 1

        # ==========================================
        # Sheet 3: Missing Labels
        # ==========================================
        ws_mis = workbook.add_worksheet('Missing Labels')
        ws_mis.set_column('A:A', 6)
        ws_mis.set_column('B:C', 18)
        ws_mis.set_column('D:D', 28)
        ws_mis.set_column('E:F', 18)
        ws_mis.set_column('G:H', 14)

        for col, h in enumerate(['Sl', 'Label Ref', 'Barcode', 'Product', 'Location', 'Purity', 'Gross Wt (g)', 'Net Wt (g)']):
            ws_mis.write(0, col, h, th_fmt)

        row = 1
        for idx, line in enumerate(audit.line_ids.filtered(lambda l: l.status == 'missing'), 1):
            ws_mis.write(row, 0, idx, center_fmt)
            ws_mis.write(row, 1, line.name or '', cell_fmt)
            ws_mis.write(row, 2, line.barcode or '', cell_fmt)
            ws_mis.write(row, 3, line.product_id.display_name or '', cell_fmt)
            ws_mis.write(row, 4, line.location_id.name or '', cell_fmt)
            ws_mis.write(row, 5, line.purity_id.name or '', cell_fmt)
            ws_mis.write(row, 6, line.sale_gross_weight or 0.0, num_fmt)
            ws_mis.write(row, 7, line.sale_net_weight or 0.0, num_fmt)
            row += 1

        # ==========================================
        # Sheet 4: Extra / Mismatched Labels
        # ==========================================
        ws_ext = workbook.add_worksheet('Extra & Foreign Branch')
        ws_ext.set_column('A:A', 6)
        ws_ext.set_column('B:C', 18)
        ws_ext.set_column('D:D', 28)
        ws_ext.set_column('E:F', 20)
        ws_ext.set_column('G:H', 14)
        ws_ext.set_column('I:I', 30)

        for col, h in enumerate(['Sl', 'Label Ref', 'Barcode', 'Product', 'Actual Branch', 'Location', 'Gross Wt (g)', 'Net Wt (g)', 'Issue / Remarks']):
            ws_ext.write(0, col, h, th_fmt)

        row = 1
        for idx, line in enumerate(audit.line_ids.filtered(lambda l: l.status == 'extra'), 1):
            ws_ext.write(row, 0, idx, center_fmt)
            ws_ext.write(row, 1, line.name or '', cell_fmt)
            ws_ext.write(row, 2, line.barcode or '', cell_fmt)
            ws_ext.write(row, 3, line.product_id.display_name or '', cell_fmt)
            ws_ext.write(row, 4, line.branch_id.name or '', cell_fmt)
            ws_ext.write(row, 5, line.location_id.name or '', cell_fmt)
            ws_ext.write(row, 6, line.sale_gross_weight or 0.0, num_fmt)
            ws_ext.write(row, 7, line.sale_net_weight or 0.0, num_fmt)
            ws_ext.write(row, 8, line.notes or '', cell_fmt)
            row += 1

        workbook.close()
        output.seek(0)
        xlsx_data = output.read()

        filename = f"Label_Verification_{audit.branch_id.name or 'Branch'}_{audit.date or fields.Date.today()}.xlsx".replace(' ', '_')
        return request.make_response(
            xlsx_data,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename={filename}'),
            ]
        )
