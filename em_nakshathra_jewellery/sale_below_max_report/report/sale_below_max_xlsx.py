from odoo import models
from datetime import datetime

class SaleBelowMaxXlsx(models.AbstractModel):
    _name = 'report.sale_below_max_report.sale_below_max_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, wizard):
        sheet = workbook.add_worksheet('Below MC Report')

        # Formats
        bold = workbook.add_format({'bold': True})
        number_format = workbook.add_format({'num_format': '0.000'})
        date_format = workbook.add_format({'num_format': 'dd-mm-yyyy'})

        row = 0

        #REPORT HEADER
        sheet.merge_range(row, 0, row, 12, 'Sale Below Minimum Report', bold)
        row += 2

        sheet.write(row, 0, 'From Date:', bold)
        sheet.write(row, 1, wizard.date_from.strftime('%d-%m-%Y') if wizard.date_from else '')

        sheet.write(row, 3, 'To Date:', bold)
        sheet.write(row, 4, wizard.date_to.strftime('%d-%m-%Y') if wizard.date_to else '')


        row += 2

        #COLUMN WIDTHS
        sheet.set_column(0, 0, 18)  # Order
        sheet.set_column(1, 1, 15)  # Date
        sheet.set_column(2, 2, 25)  # Customer
        sheet.set_column(3, 3, 20)  # Branch
        sheet.set_column(4, 4, 30)  # Product
        sheet.set_column(5, 5, 15)  # Purity
        sheet.set_column(6, 6, 20)  # Label
        sheet.set_column(7, 12, 15)  # Numbers

        #TABLE HEADER
        headers = ['Order', 'Date', 'Customer', 'Branch', 'Product', 'Purity', 'Label', 'Gross Wgt', 'Actual MC Amt', 'Metal Amt', 'MC % Actual', 'MC % Min', 'Difference']

        for col, header in enumerate(headers):
            sheet.write(row, col, header, bold)

        row += 1

        domain = [
            ('state', 'in', ['sale', 'done']),
            ('date_order', '>=', wizard.date_from),
            ('date_order', '<=', wizard.date_to),
        ]
        if wizard.branch_ids:
            domain.append(('branch_id', 'in', wizard.branch_ids.ids))
       
        orders = self.env['sale.order'].search(domain)

        #DATA
        for order in orders:
            for line in order.order_line:
                if line.sale_making_charge_min and \
                   line.mc_percent_actual < line.sale_making_charge_min:

                    # Convert datetime → date
                    order_date = order.date_order.date() if order.date_order else False

                    sheet.write(row, 0, order.name)

                    if order_date:
                        sheet.write_datetime(row, 1,
                            datetime.combine(order_date, datetime.min.time()),
                            date_format)
                    else:
                        sheet.write(row, 1, '')

                    sheet.write(row, 2, order.partner_id.name)
                    sheet.write(row, 3, order.branch_id.name if order.branch_id else '')
                    sheet.write(row, 4, line.product_id.display_name)
                    sheet.write(row, 5, line.purity_id.name if line.purity_id else '')
                    sheet.write(row, 6, line.label_id.name if line.label_id else '')
                    sheet.write(row, 7, line.product_uom_qty, number_format)
                    sheet.write(row, 8, line.mc_amount_actual, number_format)
                    sheet.write(row, 9, line.metal_amount, number_format)
                    sheet.write(row, 10, line.mc_percent_actual, number_format)
                    sheet.write(row, 11, line.sale_making_charge_min, number_format)
                    sheet.write(row, 12,
                                line.mc_percent_actual - line.sale_making_charge_min,
                                number_format)

                    row += 1