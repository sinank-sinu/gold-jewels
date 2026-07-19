from odoo import models
from datetime import timedelta

class SchemeMarginListXlsx(models.AbstractModel):
    _name = 'report.em_jewellery_customisation.scheme_margin_list_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, schemes):
        sheet = workbook.add_worksheet('Scheme Margin')
        
        # Formats
        bold = workbook.add_format({'bold': True})
        bold_underline = workbook.add_format({'bold': True, 'underline': True, 'font_size': 12})
        header_border = workbook.add_format({'bold': True, 'top': 1, 'bottom': 1})
        header_border_right = workbook.add_format({'bold': True, 'top': 1, 'bottom': 1, 'align': 'right'})
        total_border = workbook.add_format({'bold': True, 'top': 1, 'bottom': 1})
        total_border_num = workbook.add_format({'bold': True, 'top': 1, 'bottom': 1, 'num_format': '0.000', 'align': 'right'})
        num_format = workbook.add_format({'num_format': '0.000', 'align': 'right'})
        date_format = workbook.add_format({'num_format': 'dd-mm-yyyy'})

        # Column widths
        sheet.set_column(0, 0, 25) # Customer
        sheet.set_column(1, 1, 15) # Date
        sheet.set_column(2, 2, 20) # Voucher Type
        sheet.set_column(3, 3, 20) # Voucher No / Caret
        sheet.set_column(4, 4, 15) # Scheme Type
        sheet.set_column(5, 5, 15) # Amount
        sheet.set_column(6, 6, 25) # Fine Rate
        sheet.set_column(7, 7, 15) # Fine Qty

        if not schemes:
            return

        is_redeem_report = schemes[0].is_redeemed
        if is_redeem_report:
            sheet.set_column(8, 8, 25) # Sales Value
            sheet.set_column(9, 9, 15) # Sales Fine Qty
            sheet.set_column(10, 10, 15) # Gain / Loss

        row = 0
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        title = "Scheme redeem Margin Report" if is_redeem_report else "Scheme Non Redeem Margin Report"
        sheet.write(row, 0, title, bold_underline)
        row += 1

        if start_date and end_date:
            sheet.write(row, 0, "From", bold)
            sheet.write(row, 1, start_date, date_format)
            sheet.write(row, 3, "To", bold)
            sheet.write(row, 4, end_date, date_format)
        row += 2

        # HEADER
        headers = [
            'Customer Name', 'Date', 'Voucher Type', 'Voucher No',
            'Scheme Type', 'Amount', 'Fine Rate Next Day 1 PM', 'Fine Qty'
        ]
        
        if is_redeem_report:
            headers.extend(['Sales Value (untaxed amount)', 'Sales Fine Qty', 'Gain / Loss'])

        for col, h in enumerate(headers):
            if col >= 6:
                sheet.write(row, col, h, header_border_right)
            else:
                sheet.write(row, col, h, header_border)
        
        row += 1

        # RAW SQL FOR MAX PERFORMANCE
        query = """
            SELECT 
                e.id AS enrollment_id,
                p.name AS customer_name,
                i.date AS inst_date,
                m.name AS voucher_no,
                i.amount AS amount,
                f.fine_rate AS fine_rate
            FROM jewellery_scheme_installment i
            JOIN jewellery_scheme_enrollment e ON i.enrollment_id = e.id
            LEFT JOIN res_partner p ON e.partner_id = p.id
            LEFT JOIN account_move m ON i.move_id = m.id
            LEFT JOIN fine_rate_master f ON f.date = (i.date + INTERVAL '1 day')::date
            WHERE i.state = 'paid'
              AND e.id IN %s
        """
        params = [tuple(schemes.ids)]

        if start_date:
            query += " AND i.date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND i.date <= %s"
            params.append(end_date)

        query += " ORDER BY p.name, e.id, i.date"

        self.env.cr.execute(query, params)
        records = self.env.cr.dictfetchall()

        grand_total_amount = 0.0
        grand_total_fine_qty = 0.0

        # Pre-calculate redemption data per scheme
        redemption_data = {}
        enrollment_fine_qtys = {}
        if is_redeem_report:
            redemptions = self.env['scheme.redemption'].search([('scheme_id', 'in', schemes.ids)])
            for red in redemptions:
                order = red.sale_order_id
                if order:
                    sales_value = order.amount_untaxed
                    sales_fine_qty = 0.0
                    for l in order.order_line:
                        if getattr(l, 'is_scheme_line', False):
                            continue
                        if getattr(l, 'label_id', False):
                            sales_fine_qty += l.label_id.sale_fine_weight
                        else:
                            sales_fine_qty += getattr(l, 'fine_weight', 0.0)
                            
                    redemption_data[red.scheme_id.id] = {
                        'sale_date': order.date_order.date() if order.date_order else False,
                        'sale_name': order.name,
                        'redemption_amount': red.amount,
                        'sales_value': sales_value,
                        'sales_fine_qty': sales_fine_qty,
                    }

            # Calculate total fine qty per enrollment for gain/loss
            for rec in records:
                e_id = rec['enrollment_id']
                amt = rec['amount'] or 0.0
                fr = rec['fine_rate'] or 0.0
                fq = amt / fr if fr else 0.0
                enrollment_fine_qtys[e_id] = enrollment_fine_qtys.get(e_id, 0.0) + fq

            for e_id, r_data in redemption_data.items():
                r_data['gain_loss'] = enrollment_fine_qtys.get(e_id, 0.0) - r_data['sales_fine_qty']

        grand_total_sales_value = sum(d.get('sales_value', 0) for d in redemption_data.values())
        grand_total_sales_fine_qty = sum(d.get('sales_fine_qty', 0) for d in redemption_data.values())
        grand_total_gain_loss = sum(d.get('gain_loss', 0) for d in redemption_data.values())

        for index, rec in enumerate(records):
            amount = rec['amount'] or 0.0
            fine_rate = rec['fine_rate'] or 0.0
            fine_qty = amount / fine_rate if fine_rate else 0.0

            # Print Receipt Row
            sheet.write(row, 0, rec['customer_name'] or '')
            sheet.write(row, 1, rec['inst_date'], date_format)
            sheet.write(row, 2, "Receipt")
            sheet.write(row, 3, rec['voucher_no'] or '')
            sheet.write(row, 4, "MC 0%")
            sheet.write(row, 5, amount)
            sheet.write(row, 6, fine_rate, num_format)
            sheet.write(row, 7, fine_qty, num_format)
            
            if is_redeem_report:
                sheet.write(row, 8, '')
                sheet.write(row, 9, '')
                sheet.write(row, 10, '')

            grand_total_amount += amount
            grand_total_fine_qty += fine_qty
            row += 1

            if is_redeem_report:
                # Check if this is the last receipt for this customer
                is_last_row = (index == len(records) - 1) or (records[index+1]['enrollment_id'] != rec['enrollment_id'])
                
                if is_last_row:
                    r_data = redemption_data.get(rec['enrollment_id'])
                    if r_data:
                        # Print Redemption / Sales Row
                        sheet.write(row, 0, rec['customer_name'] or '')
                        if r_data['sale_date']:
                            sheet.write(row, 1, r_data['sale_date'], date_format)
                        else:
                            sheet.write(row, 1, '')
                        sheet.write(row, 2, "Sales")
                        sheet.write(row, 3, r_data['sale_name'] or '')
                        sheet.write(row, 4, "MC 0%")
                        sheet.write(row, 5, r_data['redemption_amount'])
                        sheet.write(row, 6, '')
                        sheet.write(row, 7, '')
                        
                        sheet.write(row, 8, r_data['sales_value'], num_format)
                        sheet.write(row, 9, r_data['sales_fine_qty'], num_format)
                        sheet.write(row, 10, r_data['gain_loss'], num_format)
                        row += 1

        # GRAND TOTAL
        sheet.write(row, 4, "Grand Total", total_border)
        sheet.write(row, 5, grand_total_amount, total_border)
        sheet.write(row, 6, '', total_border)
        sheet.write(row, 7, grand_total_fine_qty, total_border_num)
        
        if is_redeem_report:
            sheet.write(row, 8, grand_total_sales_value, total_border_num)
            sheet.write(row, 9, grand_total_sales_fine_qty, total_border_num)
            sheet.write(row, 10, grand_total_gain_loss, total_border_num)

