from odoo import models, fields
from dateutil.relativedelta import relativedelta
import datetime

class SchemeDueXlsx(models.Model):
    _name = 'report.scheme_due_xlsx.scheme_due_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, docs):
        sheet = workbook.add_worksheet('Scheme Due Report')

        # =========================
        # Formats
        # =========================
        header_format = workbook.add_format({
            'bold': True,
            'border': 1,
            'align': 'center',
            'bg_color': '#4472C4',
            'font_color': 'white'
        })
        text_format = workbook.add_format({'border': 1})
        number_format = workbook.add_format({
            'border': 1,
            'num_format': '#,##0.00'
        })
        date_format = workbook.add_format({
            'border': 1,
            'num_format': 'yyyy-mm-dd',
            'align': 'center'
        })
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'align': 'center'
        })

        # =========================
        # Title
        # =========================
        sheet.merge_range('A1:R1', 'Scheme Due Report', title_format)

        # =========================
        # Filter Information
        # =========================
        show_filter_row = data.get('start_date') or data.get('end_date') or data.get('branch_names')
        if show_filter_row:
            date_range = f"Date Range: {data.get('start_date') or 'All'} to {data.get('end_date') or 'All'} | Branches: {data.get('branch_names', 'All')}"
            sheet.merge_range('A2:R2', date_range, text_format)

        # =========================
        # Headers
        # =========================
        headers = [
            'Scheme Name', 'Customer Name', 'Salesman', 'Branch', 'Date of Joining', 
            'Mobile', 'Whatsapp', 'Email', 'Installment Amount', 'Tenure', 
            'Total Scheme Amount', 'No of installment till date', 'Total Due Amount', 
            'No of installment paid', 'Total Paid', 'Due Amount', 'No of installment due', 'Next due date'
        ]

        start_row = 3 if show_filter_row else 2
        for col, header in enumerate(headers):
            sheet.write(start_row, col, header, header_format)

        # =========================
        # Column Width Adjustments
        # =========================
        column_widths = {
            'A': 25, 'B': 25, 'C': 15, 'D': 15, 'E': 15, 'F': 15, 'G': 15, 'H': 25,
            'I': 18, 'J': 10, 'K': 20, 'L': 25, 'M': 20, 'N': 25, 'O': 15, 'P': 15,
            'Q': 25, 'R': 15
        }
        for col_letter, width in column_widths.items():
            sheet.set_column(f'{col_letter}:{col_letter}', width)

        # =========================
        # Fetching Data and Rows
        # =========================
        today = fields.Date.context_today(self)
        
        # Build search domain based on filters passed via wizard's data dictionary
        domain = [('state', '=', 'running')]
        if data.get('branch_ids'):
            domain.append(('branch_id', 'in', data.get('branch_ids')))
        
        # Fallback to docs if data domain isn't filled by an explicit wizard
        enrollments = self.env['jewellery.scheme.enrollment'].search(domain) if data.get('branch_ids') else docs

        current_row = start_row + 1

        for rec in enrollments:
            joining_date = rec.date_of_joining or today
            inst_amount = rec.installment_amount or 0.0
            tenure = rec.duration or 0
            total_scheme_amount = inst_amount * tenure

            # 1. Compute Installments Till Date based on months passed since Joining Date
            if today >= joining_date:
                delta = relativedelta(today, joining_date)
                # Total months elapsed inclusive of starting month slot
                months_elapsed = (delta.years * 12) + delta.months + 1
                inst_till_date = min(months_elapsed, tenure)
            else:
                inst_till_date = 0

            total_due_amount_till_date = inst_till_date * inst_amount

            # 2. Paid values pulled from database metrics
            inst_paid = rec.paid_count
            total_paid = rec.total_paid

            # 3. Financial calculations for due figures
            inst_due = max(0, inst_till_date - inst_paid)
            due_amount = max(0.0, total_due_amount_till_date - total_paid)

            # 4. Determine Next Due Date dynamically
            # It points to the month index corresponding to the number of completed payments
            next_due_date = joining_date + relativedelta(months=inst_paid) if inst_paid < tenure else ''

            # Write Values into the row matching headers structure
            sheet.write(current_row, 0, rec.name or '', text_format)
            sheet.write(current_row, 1, rec.partner_id.name or '', text_format)
            sheet.write(current_row, 2, rec.create_uid.name or '', text_format) # Salesman mapping
            sheet.write(current_row, 3, rec.branch_id.name or '', text_format)
            sheet.write(current_row, 4, joining_date, date_format)
            sheet.write(current_row, 5, rec.phone or '', text_format)
            sheet.write(current_row, 6, rec.whatsapp_number or '', text_format)
            sheet.write(current_row, 7, rec.partner_id.email or '', text_format)
            sheet.write(current_row, 8, inst_amount, number_format)
            sheet.write(current_row, 9, tenure, text_format)
            sheet.write(current_row, 10, total_scheme_amount, number_format)
            sheet.write(current_row, 11, inst_till_date, text_format)
            sheet.write(current_row, 12, total_due_amount_till_date, number_format)
            sheet.write(current_row, 13, inst_paid, text_format)
            sheet.write(current_row, 14, total_paid, number_format)
            sheet.write(current_row, 15, due_amount, number_format)
            sheet.write(current_row, 16, inst_due, text_format)
            
            if next_due_date:
                sheet.write(current_row, 17, next_due_date, date_format)
            else:
                sheet.write(current_row, 17, 'Completed', text_format)

            current_row += 1

