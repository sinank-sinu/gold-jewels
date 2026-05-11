from odoo import models
from datetime import datetime


class PurchaseFineRateXlsx(models.AbstractModel):
    _name = 'report.purchase_fine_rate_variance_report.po_fine_rate_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, purchase_orders):

        sheet = workbook.add_worksheet('Fine Rate Variance')

        # =========================
        # Formats
        # =========================

        title_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'font_size': 14,
            'border': 1,
        })

        header_format = workbook.add_format({
            'bold': True,
            'border': 1,
            'align': 'center',
            'bg_color': '#D3D3D3',
        })

        text_format = workbook.add_format({
            'border': 1,
        })

        number_format = workbook.add_format({
            'border': 1,
            'num_format': '0.000',
        })

        difference_format = workbook.add_format({
            'border': 1,
            'num_format': '0.000',
            'bold': True,
        })

        # =========================
        # Column Width
        # =========================

        sheet.set_column('A:A', 35)
        sheet.set_column('B:B', 12)
        sheet.set_column('C:E', 18)

        row = 0

        # =========================
        # Latest Fine Rate
        # =========================

        latest_rate_rec = self.env['fine.rate.master'].search(
            [],
            order='date desc,id desc',
            limit=1
        )

        latest_fine_rate = latest_rate_rec.fine_rate or 0.0

        # =========================
        # Report Loop
        # =========================

        for po in purchase_orders:

            # Title
            sheet.merge_range(row, 0, row, 4,
                              f'Purchase Fine Rate Variance Report - {po.name}',
                              title_format)

            row += 2

            # PO Details
            sheet.write(row, 0, 'Vendor', header_format)
            sheet.write(row, 1, po.partner_id.name or '', text_format)

            row += 1

            sheet.write(row, 0, 'Purchase Order', header_format)
            sheet.write(row, 1, po.name or '', text_format)

            row += 1

            sheet.write(row, 0, 'Report Date', header_format)
            sheet.write(row, 1,
                        datetime.today().strftime('%d-%m-%Y %H:%M:%S'),
                        text_format)

            row += 2

            # Table Headers
            sheet.write(row, 0, 'Product', header_format)
            sheet.write(row, 1, 'Qty', header_format)
            sheet.write(row, 2, 'PO Fine Rate', header_format)
            sheet.write(row, 3, 'Current Fine Rate', header_format)
            sheet.write(row, 4, 'Difference', header_format)

            row += 1

            total_diff = 0.0

            for line in po.order_line:

                difference = latest_fine_rate - line.metal_amount

                total_diff += difference

                sheet.write(row, 0,
                            line.product_id.display_name or '',
                            text_format)

                sheet.write(row, 1,
                            line.product_qty,
                            number_format)

                sheet.write(row, 2,
                            line.metal_amount,
                            number_format)

                sheet.write(row, 3,
                            latest_fine_rate,
                            number_format)

                sheet.write(row, 4,
                            difference,
                            difference_format)

                row += 1

            # Total
            sheet.write(row, 3, 'Total Difference', header_format)
            sheet.write(row, 4, total_diff, difference_format)

            row += 3