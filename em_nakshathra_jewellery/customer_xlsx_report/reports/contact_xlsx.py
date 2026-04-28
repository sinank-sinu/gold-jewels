from odoo import models


class ContactXlsxReport(models.AbstractModel):
    _name = 'report.customer_xlsx_report.contact_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, partners):

        sheet = workbook.add_worksheet('Contacts')
        # Set column widths
        sheet.set_column(0, 0, 25)   # Customer Name
        sheet.set_column(1, 1, 20)  # Profession
        sheet.set_column(2, 2, 15)  # Location
        sheet.set_column(3, 3, 8)  # Age
        sheet.set_column(4, 4, 15)  # Phone
        sheet.set_column(5, 5, 30)  # Email
        sheet.set_column(6, 6, 20)  # Branch
        
        bold = workbook.add_format({'bold': True})

        headers = [
           'Customer Name', 'Profession', 'Location',
             'Age', 'Phone', 'Email', 'Branch'
        ]

        # Header row
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)

        row = 1
        partners = self.env['res.partner'].search([('customer_rank', '>', 0)])

        for p in partners:
            sheet.write(row, 0, p.name or '')
            sheet.write(row, 1, p.function or '')
            sheet.write(row, 2, p.city or '')
            sheet.write(row, 3, p.age or 0)
            sheet.write(row, 4, p.phone or '')
            sheet.write(row, 5, p.email or '')
            sheet.write(row, 6, p.branch_id.name if p.branch_id else '')

            row += 1