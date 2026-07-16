from odoo import models


class JewelleryReportXlsx(models.AbstractModel):
    _name = 'report.em_jewellery_reports.jewellery_report_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, wizards):
        for wizard in wizards:
            self._generate_item_detail_report(workbook, wizard)

    def _generate_item_detail_report(self, workbook, wizard):
        sheet = workbook.add_worksheet('Item Details Traceability')

        # Formats
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 16,
            'font_color': '#1D2A44',
            'align': 'left',
            'valign': 'vcenter'
        })
        
        meta_format = workbook.add_format({
            'font_size': 10,
            'bold': True,
            'align': 'left'
        })
        
        meta_val_format = workbook.add_format({
            'font_size': 10,
            'align': 'left'
        })

        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1D2A44',
            'font_color': '#FFFFFF',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True
        })

        data_left = workbook.add_format({'align': 'left', 'valign': 'top', 'border': 1, 'font_size': 10})
        data_center = workbook.add_format({'align': 'center', 'valign': 'top', 'border': 1, 'font_size': 10})
        data_number = workbook.add_format({'align': 'right', 'valign': 'top', 'border': 1, 'num_format': '0.000', 'font_size': 10})
        data_wrap = workbook.add_format({'align': 'left', 'valign': 'top', 'border': 1, 'text_wrap': True, 'font_size': 9})

        total_format = workbook.add_format({
            'bold': True,
            'bg_color': '#F5F5F5',
            'border': 1,
            'num_format': '0.000',
            'align': 'right',
            'valign': 'vcenter',
            'font_size': 10
        })
        
        total_label_format = workbook.add_format({
            'bold': True,
            'bg_color': '#F5F5F5',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 10
        })

        # Set Row Heights
        sheet.set_row(0, 35)
        sheet.set_row(5, 20)
        sheet.set_row(6, 20)

        # Title
        sheet.merge_range('A1:L1', 'Nakshathra Jewellery — Item Details Report', title_format)

        # Meta Information
        sheet.write('A3', 'From Date:', meta_format)
        sheet.write('B3', str(wizard.date_from) if wizard.date_from else '', meta_val_format)
        sheet.write('A4', 'To Date:', meta_format)
        sheet.write('B4', str(wizard.date_to) if wizard.date_to else '', meta_val_format)

        # Table Headers
        sheet.merge_range(5, 0, 6, 0, 'Product Item', header_format)
        sheet.merge_range(5, 1, 6, 1, 'Date', header_format)
        sheet.merge_range(5, 2, 6, 2, 'Ref', header_format)
        sheet.merge_range(5, 3, 5, 5, 'Inward', header_format)
        sheet.merge_range(5, 6, 5, 9, 'Outward', header_format)
        sheet.merge_range(5, 10, 5, 11, 'Closing', header_format)

        sheet.write(6, 3, 'Gross Wt', header_format)
        sheet.write(6, 4, 'Net Wt', header_format)
        sheet.write(6, 5, 'Diamond Wt', header_format)
        sheet.write(6, 6, 'Gross Wt', header_format)
        sheet.write(6, 7, 'Net Wt', header_format)
        sheet.write(6, 8, 'Diamond Wt', header_format)
        sheet.write(6, 9, 'Other Wt', header_format)
        sheet.write(6, 10, 'Gross Wt', header_format)
        sheet.write(6, 11, 'Net Wt', header_format)

        # Data Rows
        row = 7
        lines = wizard.item_detail_line_ids
        for line in lines:
            sheet.write(row, 0, line.product_id.name or '', data_left)
            sheet.write(row, 1, str(line.date) if line.date else '', data_center)
            sheet.write(row, 2, line.ref or '', data_center)
            
            sheet.write(row, 3, line.inward_gross_weight or '', data_number)
            sheet.write(row, 4, line.inward_net_weight or '', data_number)
            sheet.write(row, 5, line.inward_diamond_weight or '', data_number)
            
            sheet.write(row, 6, line.outward_gross_weight or '', data_number)
            sheet.write(row, 7, line.outward_net_weight or '', data_number)
            sheet.write(row, 8, line.outward_diamond_weight or '', data_number)
            sheet.write(row, 9, line.outward_other_weight or '', data_number)
            
            sheet.write(row, 10, line.closing_gross_weight, data_number)
            sheet.write(row, 11, line.closing_net_weight, data_number)
            row += 1

        # Totals Row
        sheet.merge_range(f'A{row+1}:C{row+1}', 'Total', total_label_format)
        sheet.write_formula(row, 3, f'=SUM(D8:D{row})', total_format)
        sheet.write_formula(row, 4, f'=SUM(E8:E{row})', total_format)
        sheet.write_formula(row, 5, f'=SUM(F8:F{row})', total_format)
        sheet.write_formula(row, 6, f'=SUM(G8:G{row})', total_format)
        sheet.write_formula(row, 7, f'=SUM(H8:H{row})', total_format)
        sheet.write_formula(row, 8, f'=SUM(I8:I{row})', total_format)
        sheet.write_formula(row, 9, f'=SUM(J8:J{row})', total_format)
        sheet.write(row, 10, '', total_label_format)
        sheet.write(row, 11, '', total_label_format)

        # Set Column Widths
        sheet.set_column(0, 0, 30)   # Product Item
        sheet.set_column(1, 1, 12)   # Date
        sheet.set_column(2, 2, 15)   # Ref
        sheet.set_column(3, 5, 16)   # Inward Weights
        sheet.set_column(6, 9, 16)   # Outward Weights
        sheet.set_column(10, 11, 16) # Closing Weights

    def _generate_stock_weight_report(self, workbook, wizard):
        sheet = workbook.add_worksheet('Stock Weights Summary')

        # Formats
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 16,
            'font_color': '#1D2A44',
            'align': 'left',
            'valign': 'vcenter'
        })
        
        meta_format = workbook.add_format({
            'font_size': 10,
            'bold': True,
            'align': 'left'
        })
        
        meta_val_format = workbook.add_format({
            'font_size': 10,
            'align': 'left'
        })

        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1D2A44',
            'font_color': '#FFFFFF',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True
        })

        data_left = workbook.add_format({'align': 'left', 'valign': 'top', 'border': 1, 'font_size': 10})
        data_center = workbook.add_format({'align': 'center', 'valign': 'top', 'border': 1, 'font_size': 10})
        data_qty = workbook.add_format({'align': 'right', 'valign': 'top', 'border': 1, 'num_format': '#,##0', 'font_size': 10})
        data_number = workbook.add_format({'align': 'right', 'valign': 'top', 'border': 1, 'num_format': '0.000', 'font_size': 10})

        total_format = workbook.add_format({
            'bold': True,
            'bg_color': '#F5F5F5',
            'border': 1,
            'num_format': '0.000',
            'align': 'right',
            'valign': 'vcenter',
            'font_size': 10
        })
        
        total_qty_format = workbook.add_format({
            'bold': True,
            'bg_color': '#F5F5F5',
            'border': 1,
            'num_format': '#,##0',
            'align': 'right',
            'valign': 'vcenter',
            'font_size': 10
        })
        
        total_label_format = workbook.add_format({
            'bold': True,
            'bg_color': '#F5F5F5',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 10
        })

        # Set Row Heights
        sheet.set_row(0, 35)
        sheet.set_row(5, 30)

        # Title
        sheet.merge_range('A1:K1', 'Nakshathra Jewellery — Stock Weights Summary Report', title_format)

        # Meta Information
        sheet.write('A3', 'Print Date:', meta_format)
        sheet.write('B3', fields.Date.context_today(wizard).strftime('%Y-%m-%d'), meta_val_format)

        # Table Headers
        headers = [
            'Product', 'Category', 'Purity', 'Location', 'Branch',
            'Qty in Stock', 'Total Gross Wt (g)', 'Total Net Wt (g)', 'Total Diamond Wt (g)', 'Total Stone Wt (g)', 'Total Other Wt (g)'
        ]
        
        for col_idx, header in enumerate(headers):
            sheet.write(5, col_idx, header, header_format)

        # Data Rows
        row = 6
        lines = wizard.stock_weight_line_ids
        for line in lines:
            sheet.write(row, 0, line.product_id.name or '', data_left)
            sheet.write(row, 1, line.category_id.name or '', data_left)
            sheet.write(row, 2, line.purity_id.name or '', data_center)
            sheet.write(row, 3, line.location_id.complete_name or '', data_left)
            sheet.write(row, 4, line.branch_id.name or '', data_center)
            
            sheet.write(row, 5, line.quantity, data_qty)
            sheet.write(row, 6, line.gross_weight, data_number)
            sheet.write(row, 7, line.net_weight, data_number)
            sheet.write(row, 8, line.diamond_weight, data_number)
            sheet.write(row, 9, line.stone_weight, data_number)
            sheet.write(row, 10, line.other_weight, data_number)
            row += 1

        # Totals Row
        sheet.merge_range(f'A{row+1}:E{row+1}', 'Total', total_label_format)
        sheet.write_formula(row, 5, f'=SUM(F7:F{row})', total_qty_format)
        sheet.write_formula(row, 6, f'=SUM(G7:G{row})', total_format)
        sheet.write_formula(row, 7, f'=SUM(H7:H{row})', total_format)
        sheet.write_formula(row, 8, f'=SUM(I7:I{row})', total_format)
        sheet.write_formula(row, 9, f'=SUM(J7:J{row})', total_format)
        sheet.write_formula(row, 10, f'=SUM(K7:K{row})', total_format)

        # Set Column Widths
        sheet.set_column(0, 0, 30)   # Product
        sheet.set_column(1, 1, 20)   # Category
        sheet.set_column(2, 2, 10)   # Purity
        sheet.set_column(3, 3, 25)   # Location
        sheet.set_column(4, 4, 15)   # Branch
        sheet.set_column(5, 5, 14)   # Qty
        sheet.set_column(6, 10, 18)  # Weights
