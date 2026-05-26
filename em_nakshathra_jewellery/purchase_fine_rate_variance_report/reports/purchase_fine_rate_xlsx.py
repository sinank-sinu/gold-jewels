from odoo import models
from datetime import datetime


class PurchaseFineRateXlsx(models.AbstractModel):
    _name = 'report.purchase_fine_rate_variance_report.po_fine_rate_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, purchase_orders):

        sheet = workbook.add_worksheet('Fine Rate Variance')

        # =====================================================
        # FORMATS
        # =====================================================

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
            'bg_color': '#D9D9D9',
        })

        text_format = workbook.add_format({
            'border': 1,
        })

        number_format = workbook.add_format({
            'border': 1,
            'num_format': '0.000',
        })

        positive_diff_format = workbook.add_format({
            'border': 1,
            'num_format': '0.000',
            'bold': True,
            'font_color': 'green',
        })

        negative_diff_format = workbook.add_format({
            'border': 1,
            'num_format': '0.000',
            'bold': True,
            'font_color': 'red',
        })

        total_header_format = workbook.add_format({
            'bold': True,
            'border': 1,
            'align': 'right',
            'bg_color': '#D9D9D9',
        })

        # =====================================================
        # COLUMN WIDTHS
        # =====================================================

        sheet.set_column('A:A', 20)
        sheet.set_column('B:B', 30)
        sheet.set_column('C:C', 35)
        sheet.set_column('D:D', 12)
        sheet.set_column('E:G', 18)

        row = 0

        # =====================================================
        # TITLE
        # =====================================================

        sheet.merge_range(
            row, 0, row, 6,
            'Purchase Fine Rate Variance Report',
            title_format
        )

        row += 2

        # =====================================================
        # FILTER DETAILS
        # =====================================================

        sheet.write(row, 0, 'From Date', header_format)
        sheet.write(row, 1, str(data.get('date_from', '')), text_format)

        row += 1

        sheet.write(row, 0, 'To Date', header_format)
        sheet.write(row, 1, str(data.get('date_to', '')), text_format)

        row += 2

        # =====================================================
        # TABLE HEADERS
        # =====================================================

        sheet.write(row, 0, 'Purchase Ref', header_format)
        sheet.write(row, 1, 'Vendor', header_format)
        sheet.write(row, 2, 'Product', header_format)
        sheet.write(row, 3, 'Qty', header_format)
        sheet.write(row, 4, 'PO Fine Rate', header_format)
        sheet.write(row, 5, 'Current Fine Rate', header_format)
        sheet.write(row, 6, 'Difference', header_format)

        row += 1

        # =====================================================
        # LATEST FINE RATE
        # =====================================================

        latest_rate_rec = self.env['fine.rate.master'].search(
            [],
            order='date desc,id desc',
            limit=1
        )

        latest_fine_rate = latest_rate_rec.fine_rate or 0.0

        total_difference = 0.0

        # =====================================================
        # DATA LINES
        # =====================================================

        for po in purchase_orders:

            for line in po.order_line:

                po_rate = line.gold_rate or 0.0

                difference = latest_fine_rate - po_rate

                total_difference += difference

                diff_format = (
                    positive_diff_format
                    if difference >= 0
                    else negative_diff_format
                )

                sheet.write(row, 0, po.name or '', text_format)

                sheet.write(row, 1,
                            po.partner_id.name or '',
                            text_format)

                sheet.write(row, 2,
                            line.product_id.display_name or '',
                            text_format)

                sheet.write(row, 3,
                            line.product_qty,
                            number_format)

                sheet.write(row, 4,
                            po_rate,
                            number_format)

                sheet.write(row, 5,
                            latest_fine_rate,
                            number_format)

                sheet.write(row, 6,
                            difference,
                            diff_format)

                row += 1

        # =====================================================
        # TOTAL
        # =====================================================

        total_format = (
            positive_diff_format
            if total_difference >= 0
            else negative_diff_format
        )

        sheet.merge_range(
            row, 0, row, 5,
            'Total Difference',
            total_header_format
        )

        sheet.write(row, 6, total_difference, total_format)