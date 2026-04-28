from odoo import models


class ProductMovementXlsx(models.AbstractModel):
    _name = 'report.product_movement_report_pdf.product_movement_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, wizard):

        sheet = workbook.add_worksheet('Product Movement')

        # Formats
        bold = workbook.add_format({'bold': True})
        header = workbook.add_format({'bold': True, 'align': 'center', 'border': 1})
        text = workbook.add_format({'border': 1})
        number = workbook.add_format({'border': 1})

        # Title
        sheet.merge_range('A1:C1', 'Product Movement Report', bold)

        # Date Range
        sheet.write('A3', 'From:', bold)
        sheet.write('B3', data.get('date_from'))

        sheet.write('A4', 'To:', bold)
        sheet.write('B4', data.get('date_to'))

        # Table Headers
        row = 6
        sheet.write(row, 0, 'Product', header)
        sheet.write(row, 1, 'Category', header)
        sheet.write(row, 2, 'Quantity', header)

        # Data Rows
        row += 1
        for r in data.get('rows', []):
            sheet.write(row, 0, r.get('name', ''), text)
            sheet.write(row, 1, r.get('category', ''), text)
            sheet.write(row, 2, r.get('qty', 0), number)
            row += 1

        # Auto column width
        sheet.set_column(0, 0, 30)
        sheet.set_column(1, 1, 25)
        sheet.set_column(2, 2, 15)