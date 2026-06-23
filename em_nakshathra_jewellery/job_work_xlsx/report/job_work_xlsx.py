from odoo import models


class JobWorkXlsx(models.AbstractModel):
    _name = 'report.job_work_xlsx.job_work_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, docs):
        sheet = workbook.add_worksheet('Job Work Report')

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
            'num_format': '0.000'
        })
        bold_format = workbook.add_format({
            'bold': True,
            'border': 1,
            'num_format': '0.000',
            'bg_color': '#D9E1F2'
        })
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'align': 'center'
        })

        # =========================
        # Title
        # =========================
        sheet.merge_range('A1:J1', 'Job Work Report', title_format)

        # =========================
        # Filter Information
        # =========================
        if data.get('start_date') or data.get('end_date') or data.get('branch_names'):
            date_range = f"Date Range: {data.get('start_date') or 'All'} to {data.get('end_date') or 'All'} | Branches: {data.get('branch_names', 'All')}"
            sheet.merge_range('A2:K2', date_range, text_format)

        # =========================
        # Headers
        # =========================
        headers = [
            '#', 'Date', 'Branch', 'Voucher Name', 'Type', 'Job Type',
            'Job Worker', 'Gross Weight', 'Fine Issue', 'Fine Receipt', 'Balance'
        ]

        start_row = 3 if (data.get('start_date') or data.get('end_date') or data.get('branch_names')) else 2
        for col, header in enumerate(headers):
            sheet.write(start_row, col, header, header_format)

        # =========================
        # Column Width
        # =========================
        sheet.set_column('A:A', 5)
        sheet.set_column('B:B', 12)
        sheet.set_column('C:C', 18)
        sheet.set_column('D:D', 20)
        sheet.set_column('E:E', 12)
        sheet.set_column('F:F', 15)
        sheet.set_column('G:G', 25)
        sheet.set_column('H:K', 15)

        # =========================
        # Data Rows
        # =========================
        row = start_row + 1
        row_no = 1

        total_gross_weight = 0.0
        total_fine_issue = 0.0
        total_fine_receipt = 0.0
        running_balance = 0.0

        for rec in docs:
            running_balance = running_balance - (rec.stock_in or 0.0) + (rec.stock_out or 0.0)
            sheet.write(row, 0, row_no, text_format)
            sheet.write(row, 1, str(rec.date or ''), text_format)
            sheet.write(row, 2, rec.branch_id.name if rec.branch_id else '', text_format)
            sheet.write(row, 3, rec.voucher_name or '', text_format)
            sheet.write(row, 4, rec.type or '', text_format)
            sheet.write(row, 5, rec.job_type or '', text_format)
            sheet.write(row, 6, rec.partner_id.name if rec.partner_id else '', text_format)
            sheet.write(row, 7, rec.gross_weight, number_format)
            sheet.write(row, 8, rec.stock_in, number_format)
            sheet.write(row, 9, rec.stock_out, number_format)
            sheet.write(row, 10, running_balance, number_format)

            # =========================
            # Totals
            # =========================
            total_gross_weight += rec.gross_weight or 0.0
            total_fine_issue += rec.stock_in or 0.0
            total_fine_receipt += rec.stock_out or 0.0

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
        sheet.write(row, 5, '', bold_format)
        sheet.write(row, 6, 'Total', bold_format)
        sheet.write(row, 7, total_gross_weight, bold_format)
        sheet.write(row, 8, total_fine_issue, bold_format)
        sheet.write(row, 9, total_fine_receipt, bold_format)
        sheet.write(row, 10, '', bold_format)
