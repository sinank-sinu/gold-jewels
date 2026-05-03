from odoo import models
from datetime import datetime

class MetalLedgerXlsx(models.AbstractModel):
    _name = 'report.em_metal_ledger.metal_ledger_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, docs):

        sheet = workbook.add_worksheet('Metal Ledger')

        # =========================
        # Formats
        # =========================
        header_format = workbook.add_format({
            'bold': True,
            'border': 1,
            'align': 'center'
        })

        text_format = workbook.add_format({'border': 1})
        number_format = workbook.add_format({'border': 1, 'num_format': '0.000'})
        bold_format = workbook.add_format({'bold': True, 'border': 1, 'num_format': '0.000'})

        # =========================
        # Title
        # =========================
        sheet.merge_range('A1:K1', 'Metal Ledger Report', bold_format)

        # =========================
        # Headers
        # =========================
        headers = [
            '#', 'Date', 'Branch', 'Voucher / Ref', 'Type',
            'Metal', 'Metal Fine', 'MC Fine',
            'Fine Weight', 'Stock In', 'Stock Out'
        ]

        for col, header in enumerate(headers):
            sheet.write(2, col, header, header_format)

        # =========================
        # Column Width
        # =========================
        sheet.set_column('A:A', 5)
        sheet.set_column('B:B', 12)
        sheet.set_column('C:C', 18)
        sheet.set_column('D:D', 20)
        sheet.set_column('E:E', 12)
        sheet.set_column('F:F', 12)
        sheet.set_column('G:K', 15)

        # =========================
        # Data Rows
        # =========================
        row = 3
        row_no = 1

        total_metal_fine = 0.0
        total_mc_fine = 0.0
        total_fine_weight = 0.0
        total_stock_in = 0.0
        total_stock_out = 0.0

        docs = docs.sorted(key=lambda r: (r.date or '', r.branch_id.name or '', r.id))

        for rec in docs:
            sheet.write(row, 0, row_no, text_format)
            sheet.write(row, 1, str(rec.date or ''), text_format)
            sheet.write(row, 2, rec.branch_id.name or '', text_format)
            sheet.write(row, 3, rec.voucher_name or '', text_format)
            sheet.write(row, 4, (rec.transaction_type or '').capitalize(), text_format)
            sheet.write(row, 5, rec.metal_id.name or '', text_format)

            sheet.write(row, 6, rec.metal_fine, number_format)
            sheet.write(row, 7, rec.mc_fine, number_format)
            sheet.write(row, 8, rec.fine_weight, number_format)
            sheet.write(row, 9, rec.stock_in, number_format)
            sheet.write(row, 10, rec.stock_out, number_format)

            total_metal_fine += rec.metal_fine
            total_mc_fine += rec.mc_fine
            total_fine_weight += rec.fine_weight
            total_stock_in += rec.stock_in
            total_stock_out += rec.stock_out

            row += 1
            row_no += 1

        # =========================
        # Totals Row
        # =========================
        sheet.write(row, 0, '', bold_format)
        sheet.write(row, 1, '', bold_format)
        sheet.write(row, 2, '', bold_format)
        sheet.write(row, 3, '', bold_format)
        sheet.write(row, 4, '', bold_format)
        sheet.write(row, 5, 'Total', bold_format)

        sheet.write(row, 6, total_metal_fine, bold_format)
        sheet.write(row, 7, total_mc_fine, bold_format)
        sheet.write(row, 8, total_fine_weight, bold_format)
        sheet.write(row, 9, total_stock_in, bold_format)
        sheet.write(row, 10, total_stock_out, bold_format)