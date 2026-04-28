from odoo import models
from datetime import datetime, timedelta, time


class SchemeRedeemMarginXlsx(models.AbstractModel):
    _name = 'report.em_jewellery_customisation.scheme_redeem_margin_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, schemes):

        sheet = workbook.add_worksheet('Scheme Margin')

        bold = workbook.add_format({'bold': True})
        bold_underline = workbook.add_format({
            'bold': True,
            'underline': True
        })
        header_border = workbook.add_format({
            'bold': True,
            'top': 1,
            'bottom': 1
        })

        header_border_right = workbook.add_format({
            'bold': True,
            'top': 1,
            'bottom': 1,
            'align': 'right'
        })

        total_border = workbook.add_format({
            'bold': True,
            'top': 1,
            'bottom': 1
        })

        total_border_num = workbook.add_format({
            'bold': True,
            'top': 1,
            'bottom': 1,
            'num_format': '0.000',
            'align': 'right'
        })
        num_format = workbook.add_format({'num_format': '0.000', 'align': 'right'})
        num_format_3_bold = workbook.add_format({'num_format': '0.000','align': 'right','bold': True})
        date_format = workbook.add_format({'num_format': 'dd-mm-yyyy'})

        # Column widths
        sheet.set_column(0, 0, 15)
        sheet.set_column(1, 1, 18)
        sheet.set_column(2, 2, 18)
        sheet.set_column(3, 3, 15)
        sheet.set_column(4, 4, 15)
        sheet.set_column(5, 5, 20)
        sheet.set_column(6, 6, 15)

        row = 0

        for scheme in schemes:

            title = "Scheme Redeem Margin Report" if scheme.state == 'redeemed' \
                else "Scheme Non Redeem Margin Report"

            sheet.write(row, 0, title, bold_underline)
            row += 2

            # Customer
            sheet.write(row, 0, "Customer Name :", bold)
            sheet.write(row, 1, scheme.partner_id.name or '')
            row += 2

            # HEADER (INSTALLMENTS)
            headers = [
                'Date', 'Voucher Type', 'Voucher No',
                'Scheme Type', 'Amount',
                'Fine Rate Next Day 1 PM', 'Fine Qty'
            ]

            for col, h in enumerate(headers):
                # sheet.write(row, col, h, bold)
                if col in [5, 6]:
                    sheet.write(row, col, h, header_border_right)
                else:
                    sheet.write(row, col, h, header_border)

            row += 1

            total_amount = 0.0
            total_fine_qty = 0.0

            # INSTALLMENTS
            for inst in scheme.scheme_line_ids:

                fine_rate = 0.0

                if inst.date:
                    next_day = inst.date + timedelta(days=1)

                    start_dt = datetime.combine(next_day, time.min)
                    end_dt = datetime.combine(next_day, time.max)

                    rate_rec = self.env['gold.rate.update.log'].search([
                        ('rate_datetime', '>=', start_dt),
                        ('rate_datetime', '<=', end_dt),
                    ], order='rate_datetime desc', limit=1)

                    if rate_rec:
                        fine_rate = rate_rec.board_rate or 0.0
                fine_qty = inst.amount / fine_rate if fine_rate else 0.0

                sheet.write(row, 0, inst.date, date_format)
                sheet.write(row, 1, "Receipt", num_format)
                sheet.write(row, 2, inst.move_id.name if inst.move_id else '')
                sheet.write(row, 3, "MC 0%")
                sheet.write(row, 4, inst.amount)
                sheet.write(row, 5, fine_rate)
                sheet.write(row, 6, fine_qty, num_format)

                total_amount += inst.amount
                total_fine_qty += fine_qty

                row += 1

            # SUBTOTAL
            sheet.write(row, 3, "Sub total", total_border)
            sheet.write(row, 4, total_amount, total_border)
            sheet.write(row, 5,'', total_border)
            sheet.write(row, 6, total_fine_qty, total_border_num)

            row += 2

            # SALES / REDEMPTION SECTION
            redemption = self.env['scheme.redemption'].search([
                ('scheme_id', '=', scheme.id)
            ], limit=1)

            if redemption:
                order = redemption.sale_order_id

                row += 1

                # ---- SECTION HEADER ----
                sheet.write(row, 2, "Caret", header_border)
                sheet.write(row, 3, "Scheme Type", header_border)
                sheet.write(row, 4, "Amount", header_border)
                sheet.write(row, 5, "Rate", header_border_right)
                sheet.write(row, 6, "Qty", header_border_right)

                row += 1

                # ---- SALES ----
                sale_rate = 0.0
                if order.date_order:
                    sale_date = order.date_order.date()
                    next_day = sale_date + timedelta(days=1)

                    start_dt = datetime.combine(next_day, time.min)
                    end_dt = datetime.combine(next_day, time.max)

                    rate_rec = self.env['gold.rate.update.log'].search([
                        ('rate_datetime', '>=', start_dt),
                        ('rate_datetime', '<=', end_dt),
                    ], order='rate_datetime desc', limit=1)

                    if rate_rec:
                        sale_rate = rate_rec.board_rate or 0.0
                # sale_rate = order.order_line[:1].gold_rate if order.order_line else 0
                sale_qty = redemption.amount / sale_rate if sale_rate else 0

                sheet.write(row, 0, order.date_order.date(), date_format)
                sheet.write(row, 1, "Sales")
                sheet.write(row, 2, "22CT")
                sheet.write(row, 3, "MC 0%")
                sheet.write(row, 4, redemption.amount)
                sheet.write(row, 5, sale_rate)
                sheet.write(row, 6, sale_qty, num_format)

                row += 1

                # ---- PURCHASE FINE ----
                purchase_qty = sale_qty * 0.95
                sale_line = order.order_line.filtered(lambda l: not l.is_scheme_line)[:1]
                purchase_mc = 0.0

                if sale_line and sale_line.label_id:
                    purchase_mc = sale_line.label_id.purchase_making_charge_value or 0.0
                mc_text = f"MC {purchase_mc}%"

                sheet.write(row, 1, "Purchase Fine with MC")
                sheet.write(row, 3, mc_text)
                sheet.write(row, 6, purchase_qty, num_format)

                row += 1

                # ---- MARGIN ----
                margin = total_fine_qty - purchase_qty

                sheet.write(row, 3, "Margin", header_border_right)
                sheet.write(row, 4, "", header_border_right)
                sheet.write(row, 5, "", header_border_right)
                sheet.write(row, 6, margin, header_border_right)

            else:
                row += 1

                # ---- HEADER ----
                sheet.write(row, 3, "Caret", header_border)
                sheet.write(row, 4, "Market Price", header_border)
                sheet.write(row, 5, "", header_border)
                sheet.write(row, 6, "Qty", header_border_right)

                row += 1

                # ---- VALUES ----
                caret = "24CT"
                market_price = 100
               

                qty = redemption.amount / market_price if market_price else 0.0

                sheet.write(row, 3, caret)
                sheet.write(row, 4, market_price)
                sheet.write(row, 6, qty, num_format)

                row += 1

                # ---- MARGIN WITHOUT MC ----
                margin_wo_mc = total_fine_qty - qty  # or adjust if needed

                sheet.write(row, 3, "Margin without MC", header_border)
                sheet.write(row, 4, "", header_border)
                sheet.write(row, 5, "", header_border)
                sheet.write(row, 6, margin_wo_mc, total_border_num)
            row += 4