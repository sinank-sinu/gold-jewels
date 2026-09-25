from odoo import models
# Added missing timedelta and time imports for the gold rate datetime logic
from datetime import datetime, timedelta, time

class SchemeRedeemMarginXlsx(models.AbstractModel):
    _name = 'report.em_jewellery_customisation.scheme_redeem_margin_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, schemes):
        # ----------------------------------------------------
        # FORMATS DEFINITION
        # ----------------------------------------------------
        title_format = workbook.add_format({
            'bold': True, 
            'font_size': 14, 
            'align': 'center', 
            'valign': 'vcenter'
        })
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#D3D3D3',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        cell_left = workbook.add_format({'border': 1, 'align': 'left'})
        cell_center = workbook.add_format({'border': 1, 'align': 'center'})
        cell_right_num = workbook.add_format({
            'border': 1, 
            'align': 'right', 
            'num_format': '#,##0.00'
        })
        total_format = workbook.add_format({
            'bold': True, 
            'border': 1, 
            'bg_color': '#EAEAEA', 
            'align': 'right',
            'num_format': '#,##0.00'
        })
        total_label_format = workbook.add_format({
            'bold': True, 
            'border': 1, 
            'bg_color': '#EAEAEA', 
            'align': 'right'
        })

        # ----------------------------------------------------
        # CONDITION: HANDLE INDIVIDUAL VS COMBINED LAYOUT
        # ----------------------------------------------------
        if len(schemes) == 1:
            # Route straight to your individual report layout
            self._generate_individual_report(workbook, schemes[0], title_format, header_format, cell_left, cell_right_num)
            return

        # --- GENERATE COMBINED REPORT TABULAR LAYOUT ---
        sheet = workbook.add_worksheet('Combined Schemes Summary')
        
        # Set Column Widths for a clean fit
        sheet.set_column('A:A', 25)  # Customer Name
        sheet.set_column('B:B', 18)  # Ticket Number
        sheet.set_column('C:C', 20)  # Name
        sheet.set_column('D:D', 20)  # Nominee
        sheet.set_column('E:E', 12)  # Duration
        sheet.set_column('F:F', 15)  # Branch
        sheet.set_column('G:I', 18)  # Installment, Total Paid, Balance

        # Title Block
        sheet.merge_range('A1:I2', 'COMBINED SCHEMES FINANCIAL REPORT', title_format)
        
        # Header Row
        headers = [
            'Customer Name', 'Ticket Number', 'Name', 'Nominee', 'Duration', 
            'Branch', 'Installment Amount', 'Total Paid', 'Balance Amount'
        ]
        
        row = 3
        for col_idx, text in enumerate(headers):
            sheet.write(row, col_idx, text, header_format)
        
        row += 1

        # Initialize manual summary counter variables (like your old gold report)
        python_total_installment = 0.0
        python_total_paid = 0.0
        python_total_balance = 0.0

        # Populate Rows dynamically 
        for scheme in schemes:
            sheet.write(row, 0, scheme.partner_id.name or '', cell_left)
            sheet.write(row, 1, scheme.ticket_number or scheme.name or '', cell_center)
            sheet.write(row, 2, scheme.name or '', cell_left)
            sheet.write(row, 3, scheme.nominee or '', cell_left)
            sheet.write(row, 4, scheme.duration or 0, cell_center)
            branch_name = str(scheme.branch_id.name or '') if scheme.branch_id else ''
            sheet.write(row, 5, branch_name, cell_center)
            # sheet.write(row, 5, scheme.name if hasattr(scheme, 'branch_id') and scheme.branch_id else '', cell_center)

            # Safely get numeric float values
            inst_amt = float(getattr(scheme, 'installment_amount', 0.0) or 0.0)
            tot_paid = float(getattr(scheme, 'total_paid', 0.0) or 0.0)
            bal_amt = float(getattr(scheme, 'balance_amount', 0.0) or 0.0)

            # Increment Python summary counters
            python_total_installment += inst_amt
            python_total_paid += tot_paid
            python_total_balance += bal_amt

            sheet.write(row, 6, inst_amt, cell_right_num)
            sheet.write(row, 7, tot_paid, cell_right_num)
            sheet.write(row, 8, bal_amt, cell_right_num)
            row += 1

        # ----------------------------------------------------
        # SUMMARY FOOTER ROW (VALUES WRITTEN DIRECTLY VIA PYTHON)
        # ----------------------------------------------------
        sheet.merge_range(f'A{row+1}:E{row+1}', '', total_label_format)
        sheet.write(row, 5, 'Total', total_label_format)
        
        # Writes absolute raw values calculated in Python memory 
        sheet.write(row, 6, python_total_installment, total_format)
        sheet.write(row, 7, python_total_paid, total_format)
        sheet.write(row, 8, python_total_balance, total_format)


    def _generate_individual_report(self, workbook, scheme, title_format, header_format, cell_left, cell_right_num):
        """ Processes a detailed, individual breakdown statement sheet layout """
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
                rate_rec = self.env['fine.rate.master'].search([('date', '=', next_day)], limit=1)
                if not rate_rec:
                    rate_rec = self.env['fine.rate.master'].search([('date', '<=', next_day)], order='date desc', limit=1)
                if rate_rec:
                    fine_rate = rate_rec.fine_rate or 0.0
            
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
            order_date = order.date_order.date() if order and order.date_order else (redemption.date or False)
            if order_date:
                sale_date = order_date
                next_day = sale_date + timedelta(days=1)
                start_dt = datetime.combine(next_day, time.min)
                end_dt = datetime.combine(next_day, time.max)

                rate_rec = self.env['gold.rate.update.log'].search([
                    ('rate_datetime', '>=', start_dt),
                    ('rate_datetime', '<=', end_dt),
                ], order='rate_datetime desc', limit=1)

                if rate_rec:
                    sale_rate = rate_rec.board_rate or 0.0
            
            sale_qty = redemption.amount / sale_rate if sale_rate else 0

            sheet.write(row, 0, order_date or '', date_format)
            sheet.write(row, 1, "Sales")
            sheet.write(row, 2, "22CT")
            sheet.write(row, 3, "MC 0%")
            sheet.write(row, 4, redemption.amount)
            sheet.write(row, 5, sale_rate)
            sheet.write(row, 6, sale_qty, num_format)

            row += 1

            # ---- PURCHASE FINE ----
            purchase_qty = sale_qty * 0.95
            sale_line = order.order_line.filtered(lambda l: not l.is_scheme_line)[:1] if order else False
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
            caret = "22CT"
            market_price = 100
           
            qty = redemption.amount / market_price if market_price else 0.0

            sheet.write(row, 3, caret)
            sheet.write(row, 4, market_price)
            sheet.write(row, 6, qty, num_format)

            row += 1

            # ---- MARGIN WITHOUT MC ----
            margin_wo_mc = total_fine_qty - qty

            sheet.write(row, 3, "Margin without MC", header_border)
            sheet.write(row, 4, "", header_border)
            sheet.write(row, 5, "", header_border)
            sheet.write(row, 6, margin_wo_mc, total_border_num)
