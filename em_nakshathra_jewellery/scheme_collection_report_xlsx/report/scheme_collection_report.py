from odoo import models, fields

class SchemeCollectionReportXlsx(models.AbstractModel):
    _name = 'report.scheme_collection_report_xlsx.scheme_collection_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, docs):
        sheet = workbook.add_worksheet('Scheme Collection Report')

        # Formats
        header_format = workbook.add_format({
            'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#4472C4', 'font_color': 'white'
        })
        text_format = workbook.add_format({'border': 1})
        number_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
        date_format = workbook.add_format({'border': 1, 'num_format': 'yyyy-mm-dd', 'align': 'center'})
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})

        # Title
        sheet.merge_range('A1:G1', 'Scheme Collection Report', title_format)

        # Filters
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        
        start_date = fields.Date.to_date(start_date_str) if start_date_str else False
        end_date = fields.Date.to_date(end_date_str) if end_date_str else False

        date_range = f"Date Range: {start_date_str or 'All'} to {end_date_str or 'All'}"
        sheet.merge_range('A2:G2', date_range, text_format)

        # Headers
        headers = [
            'Date', 'Customer', 'Date of Joining', 'Phone Number',
            'Which Installment Paid', 'Monthly Amount', 'Pending EMI'
        ]

        for col, header in enumerate(headers):
            sheet.write(2, col, header, header_format)

        # Column Widths
        column_widths = {'A': 15, 'B': 25, 'C': 15, 'D': 15, 'E': 25, 'F': 18, 'G': 15}
        for col_letter, width in column_widths.items():
            sheet.set_column(f'{col_letter}:{col_letter}', width)

        # Pre-fetch valid enrollments that have at least one payment in the given period
        inst_domain = [('state', '=', 'paid')]
        if start_date:
            inst_domain.append(('date', '>=', start_date))
        if end_date:
            inst_domain.append(('date', '<=', end_date))
            
        installments_in_period = self.env['jewellery.scheme.installment'].search(inst_domain)
        enrollment_ids_with_payment = installments_in_period.mapped('enrollment_id').ids
        
        if not enrollment_ids_with_payment:
            return

        # Fetch Data
        domain = [('state', '=', 'running'), ('id', 'in', enrollment_ids_with_payment)]
        if data.get('branch_ids'):
            domain.append(('branch_id', 'in', data.get('branch_ids')))

        enrollments = self.env['jewellery.scheme.enrollment'].search(domain)
        if not enrollments:
            return

        # Fetch all paid installments for these enrollments to compute indices efficiently
        all_paid_insts = self.env['jewellery.scheme.installment'].search([
            ('enrollment_id', 'in', enrollments.ids),
            ('state', '=', 'paid')
        ], order='date asc, id asc')
        
        # Group by enrollment
        from collections import defaultdict
        insts_by_enrollment = defaultdict(list)
        for inst in all_paid_insts:
            insts_by_enrollment[inst.enrollment_id.id].append(inst)

        current_row = 3
        today = fields.Date.today()

        for rec in enrollments:
            paid_insts = []
            enrollment_insts = insts_by_enrollment.get(rec.id, [])
            
            for idx, inst in enumerate(enrollment_insts, start=1):
                in_range = True
                if start_date and inst.date < start_date:
                    in_range = False
                if end_date and inst.date > end_date:
                    in_range = False
                
                if in_range:
                    paid_insts.append((str(idx), inst))
            
            # Skip if no installments paid between the dates
            if not paid_insts:
                continue

            pending_emi = rec.duration - rec.paid_count

            for idx_str, inst in paid_insts:
                sheet.write(current_row, 0, inst.date, date_format)
                sheet.write(current_row, 1, rec.partner_id.name or '', text_format)
                sheet.write(current_row, 2, rec.date_of_joining or '', date_format)
                sheet.write(current_row, 3, rec.phone or '', text_format)
                sheet.write(current_row, 4, idx_str, text_format)
                sheet.write(current_row, 5, rec.installment_amount, number_format)
                sheet.write(current_row, 6, pending_emi, text_format)
                current_row += 1
