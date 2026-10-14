# -*- coding: utf-8 -*-
import io
import base64
from odoo import models, fields, api, _
from odoo.exceptions import UserError

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None


class LocationExcessWeightExportWizard(models.TransientModel):
    _name = 'location.excess.weight.export.wizard'
    _description = 'Export Location Excess Weight Report (Excel)'

    branch_ids = fields.Many2many('res.branch', string='Filter by Branches')
    status_filter = fields.Selection([
        ('all', 'All Locations'),
        ('excess', 'Only Excess Weight (Surplus)'),
        ('mismatch', 'All Mismatched (Excess or Shortage)'),
        ('verified', 'All Verified / Weighed Locations'),
    ], string='Status Filter', default='all', required=True)
    only_internal = fields.Boolean(string='Only Internal Stock Locations', default=True)

    excel_file = fields.Binary(string='Excel File', readonly=True)
    file_name = fields.Char(string='File Name', readonly=True)

    def action_export_xlsx(self):
        self.ensure_one()
        if not openpyxl:
            raise UserError(_("The 'openpyxl' Python library is required to generate this Excel report."))

        domain = []
        if self.only_internal:
            domain.append(('usage', '=', 'internal'))
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))

        locations = self.env['stock.location'].search(domain, order='branch_id, complete_name')
        locations._compute_location_weights()
        locations._compute_weight_difference()

        if self.status_filter == 'excess':
            locations = locations.filtered(lambda l: l.excess_weight > 0.0001)
        elif self.status_filter == 'mismatch':
            locations = locations.filtered(lambda l: l.weight_status in ('excess', 'shortage'))
        elif self.status_filter == 'verified':
            locations = locations.filtered(lambda l: l.weight_status != 'unverified')

        if not locations:
            raise UserError(_("No stock locations found matching the selected criteria."))

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Excess Weight Report"
        ws.views.sheetView[0].showGridLines = True

        # Styles
        title_font = Font(name='Segoe UI', size=16, bold=True, color='1E293B')
        sub_font = Font(name='Segoe UI', size=10, italic=True, color='64748B')
        header_font = Font(name='Segoe UI', size=11, bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='1E3A8A', end_color='1E3A8A', fill_type='solid')
        data_font = Font(name='Segoe UI', size=10)
        bold_font = Font(name='Segoe UI', size=10, bold=True)
        thin_border = Border(
            left=Side(style='thin', color='E2E8F0'),
            right=Side(style='thin', color='E2E8F0'),
            top=Side(style='thin', color='E2E8F0'),
            bottom=Side(style='thin', color='E2E8F0'),
        )
        total_fill = PatternFill(start_color='F1F5F9', end_color='F1F5F9', fill_type='solid')

        # Status fills
        excess_fill = PatternFill(start_color='FEE2E2', end_color='FEE2E2', fill_type='solid')
        excess_font = Font(name='Segoe UI', size=10, bold=True, color='991B1B')
        shortage_fill = PatternFill(start_color='FEF3C7', end_color='FEF3C7', fill_type='solid')
        shortage_font = Font(name='Segoe UI', size=10, bold=True, color='92400E')
        balanced_fill = PatternFill(start_color='DCFCE7', end_color='DCFCE7', fill_type='solid')
        balanced_font = Font(name='Segoe UI', size=10, bold=True, color='166534')

        # Title Block
        ws.merge_cells('A1:K1')
        ws['A1'] = "JEWELLERY STOCK LOCATION EXCESS WEIGHT REPORT"
        ws['A1'].font = title_font
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 32

        now_str = fields.Datetime.to_string(fields.Datetime.now())
        ws.merge_cells('A2:K2')
        ws['A2'] = f"Generated on: {now_str} | Filter: {dict(self._fields['status_filter'].selection).get(self.status_filter)}"
        ws['A2'].font = sub_font
        ws['A2'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[2].height = 18

        headers = [
            "SL",
            "Stock Location",
            "Branch",
            "Basis",
            "Active Labels",
            "Labels Wt (g)",
            "Quant Wt (g)",
            "System Wt (g)",
            "Physical Wt (g)",
            "Excess Wt (g)",
            "Shortage Wt (g)",
            "Status",
            "Last Weighed Date",
        ]

        row = 4
        ws.row_dimensions[row].height = 25
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=row, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        tot_labels = 0
        tot_lbl_wt = 0.0
        tot_quant_wt = 0.0
        tot_sys_wt = 0.0
        tot_phy_wt = 0.0
        tot_excess_wt = 0.0
        tot_shortage_wt = 0.0

        for idx, loc in enumerate(locations, 1):
            row += 1
            ws.row_dimensions[row].height = 20
            
            tot_labels += loc.system_label_count
            tot_lbl_wt += loc.system_label_weight
            tot_quant_wt += loc.system_quant_weight
            tot_sys_wt += loc.system_weight
            tot_phy_wt += loc.physical_weight
            tot_excess_wt += loc.excess_weight
            tot_shortage_wt += loc.shortage_weight

            ws.cell(row=row, column=1, value=idx).alignment = Alignment(horizontal='center')
            ws.cell(row=row, column=2, value=loc.complete_name or loc.name)
            ws.cell(row=row, column=3, value=loc.branch_id.name if loc.branch_id else "N/A")
            ws.cell(row=row, column=4, value="Labels" if loc.system_weight_basis == 'label' else "Quant")
            ws.cell(row=row, column=5, value=loc.system_label_count).number_format = '#,##0'
            ws.cell(row=row, column=6, value=loc.system_label_weight).number_format = '#,##0.000'
            ws.cell(row=row, column=7, value=loc.system_quant_weight).number_format = '#,##0.000'
            ws.cell(row=row, column=8, value=loc.system_weight).number_format = '#,##0.000'
            ws.cell(row=row, column=9, value=loc.physical_weight).number_format = '#,##0.000'

            excess_cell = ws.cell(row=row, column=10, value=loc.excess_weight)
            excess_cell.number_format = '#,##0.000'
            if loc.excess_weight > 0:
                excess_cell.fill = excess_fill
                excess_cell.font = excess_font

            shortage_cell = ws.cell(row=row, column=11, value=loc.shortage_weight)
            shortage_cell.number_format = '#,##0.000'
            if loc.shortage_weight > 0:
                shortage_cell.fill = shortage_fill
                shortage_cell.font = shortage_font

            status_label = dict(loc._fields['weight_status'].selection).get(loc.weight_status, 'Unverified')
            status_cell = ws.cell(row=row, column=12, value=status_label)
            status_cell.alignment = Alignment(horizontal='center')
            if loc.weight_status == 'excess':
                status_cell.fill = excess_fill
                status_cell.font = excess_font
            elif loc.weight_status == 'shortage':
                status_cell.fill = shortage_fill
                status_cell.font = shortage_font
            elif loc.weight_status == 'balanced':
                status_cell.fill = balanced_fill
                status_cell.font = balanced_font

            check_dt_str = fields.Datetime.to_string(loc.last_weight_check_date) if loc.last_weight_check_date else "Never"
            ws.cell(row=row, column=13, value=check_dt_str).alignment = Alignment(horizontal='center')

            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row=row, column=col_idx)
                c.border = thin_border
                if not c.font or c.font.name != 'Segoe UI':
                    c.font = data_font

        # Total Row
        row += 1
        ws.row_dimensions[row].height = 24
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        tot_title_cell = ws.cell(row=row, column=1, value="TOTAL SUMMARY")
        tot_title_cell.font = bold_font
        tot_title_cell.alignment = Alignment(horizontal='right', vertical='center')

        ws.cell(row=row, column=5, value=tot_labels).number_format = '#,##0'
        ws.cell(row=row, column=6, value=round(tot_lbl_wt, 3)).number_format = '#,##0.000'
        ws.cell(row=row, column=7, value=round(tot_quant_wt, 3)).number_format = '#,##0.000'
        ws.cell(row=row, column=8, value=round(tot_sys_wt, 3)).number_format = '#,##0.000'
        ws.cell(row=row, column=9, value=round(tot_phy_wt, 3)).number_format = '#,##0.000'
        ws.cell(row=row, column=10, value=round(tot_excess_wt, 3)).number_format = '#,##0.000'
        ws.cell(row=row, column=11, value=round(tot_shortage_wt, 3)).number_format = '#,##0.000'

        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(row=row, column=col_idx)
            c.border = thin_border
            c.fill = total_fill
            c.font = bold_font

        # Column widths
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.row in (1, 2):
                    continue
                val = str(cell.value or '')
                max_len = max(max_len, len(val))
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
        ws.column_dimensions['B'].width = 32

        fp = io.BytesIO()
        wb.save(fp)
        fp.seek(0)
        file_data = base64.b64encode(fp.read())
        fp.close()

        filename = f"Location_Excess_Weight_{fields.Date.today()}.xlsx"
        self.write({
            'excel_file': file_data,
            'file_name': filename,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model={self._name}&id={self.id}&field=excel_file&download=true&filename={filename}',
            'target': 'self',
        }
