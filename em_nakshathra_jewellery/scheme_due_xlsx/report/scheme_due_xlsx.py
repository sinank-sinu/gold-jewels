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
        sheet.merge_range('A1:P1', 'Scheme Due Report', title_format)

        # =========================
        # Filter Information
        # =========================
        show_filter_row = bool(data.get('end_date') or data.get('branch_names'))
        if show_filter_row:
            date_range = f"Due As Of: {data.get('end_date') or 'All'} | Branches: {data.get('branch_names', 'All')}"
            sheet.merge_range('A2:P2', date_range, text_format)

        # =========================
        # Headers
        # =========================
        headers = [
            'Scheme Name', 'Customer Name', 'Salesman', 'Branch', 'Date of Joining', 
            'Mobile', 'Whatsapp', 'Email', 'Installment Amount', 'Tenure', 
            'Total Scheme Amount', 'No of installment paid', 'Total Paid', 
            'Due Amount', 'No of installment due', 'Next due date'
        ]

        start_row = 3 if show_filter_row else 2
        for col, header in enumerate(headers):
            sheet.write(start_row, col, header, header_format)

        # =========================
        # Column Width Adjustments
        # =========================
        column_widths = {
            'A': 25, 'B': 25, 'C': 15, 'D': 15, 'E': 15, 'F': 15, 'G': 15, 'H': 25,
            'I': 18, 'J': 10, 'K': 20, 'L': 25, 'M': 20, 'N': 20, 'O': 25, 'P': 15
        }
        for col_letter, width in column_widths.items():
            sheet.set_column(f'{col_letter}:{col_letter}', width)

        # =========================
        # Fetching Data and Rows
        # =========================
        as_of_date = fields.Date.to_date(data.get('end_date')) or fields.Date.context_today(self)
        
        # Build search domain based on filters passed via wizard's data dictionary
        domain = [('state', '=', 'running')]
        if data.get('end_date'):
            domain.extend(['|', ('date_of_joining', '=', False), ('date_of_joining', '<=', data.get('end_date'))])
        if data.get('branch_ids'):
            domain.append(('branch_id', 'in', data.get('branch_ids')))
        if data.get('partner_ids'):
            domain.append(('partner_id', 'in', data.get('partner_ids')))
        
        enrollments = docs if docs else self.env['jewellery.scheme.enrollment'].search(domain, order='date_of_joining asc, id asc')

        current_row = start_row + 1

        for rec in enrollments:
            if rec.state != 'running':
                continue

            joining_date = rec.date_of_joining or as_of_date
            inst_amount = rec.installment_amount or 0.0
            tenure = rec.duration or 0
            total_scheme_amount = inst_amount * tenure

            # 1. Paid values from enrollment metrics
            total_paid = rec.total_paid
            if inst_amount > 0:
                inst_paid = int(round(total_paid / inst_amount))
            else:
                inst_paid = rec.paid_count

            # 2. Balance / Due calculations (Remaining to complete scheme)
            inst_due = max(0, tenure - inst_paid)
            due_amount = max(0.0, total_scheme_amount - total_paid)

            # 3. Determine Next Due Date dynamically
            next_due_date = joining_date + relativedelta(months=inst_paid) if inst_paid < tenure else ''

            # Write Values into the row matching headers structure
            sheet.write(current_row, 0, rec.name or '', text_format)
            sheet.write(current_row, 1, rec.partner_id.name or '', text_format)
            sheet.write(current_row, 2, rec.user_id.name or rec.create_uid.name or '', text_format)
            sheet.write(current_row, 3, rec.branch_id.name or '', text_format)
            sheet.write(current_row, 4, joining_date, date_format)
            sheet.write(current_row, 5, rec.phone or rec.partner_id.phone or '', text_format)
            sheet.write(current_row, 6, rec.whatsapp_number or rec.partner_id.mobile or '', text_format)
            sheet.write(current_row, 7, rec.partner_id.email or '', text_format)
            sheet.write(current_row, 8, inst_amount, number_format)
            sheet.write(current_row, 9, tenure, text_format)
            sheet.write(current_row, 10, total_scheme_amount, number_format)
            sheet.write(current_row, 11, inst_paid, text_format)
            sheet.write(current_row, 12, total_paid, number_format)
            sheet.write(current_row, 13, due_amount, number_format)
            sheet.write(current_row, 14, inst_due, text_format)
            
            if next_due_date:
                sheet.write(current_row, 15, next_due_date, date_format)
            else:
                sheet.write(current_row, 15, 'Completed', text_format)

            current_row += 1

