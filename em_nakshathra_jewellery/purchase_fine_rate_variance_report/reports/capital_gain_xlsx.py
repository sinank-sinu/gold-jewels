from odoo import models
from datetime import datetime


class PurchaseCapitalGainXlsx(models.AbstractModel):
    _name = 'report.purchase_fine_rate_variance_report.capital_gain_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, purchase_orders):

        sheet = workbook.add_worksheet('Capital Gain Report')

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

        positive_gain_format = workbook.add_format({
            'border': 1,
            'num_format': '0.000',
            'bold': True,
            'font_color': 'green',
        })

        negative_loss_format = workbook.add_format({
            'border': 1,
            'num_format': '0.000',
            'bold': True,
            'font_color': 'red',
        })

        note_format = workbook.add_format({
            'font_size': 10,
            'align': 'left'
        })

        sheet.set_column('A:A', 20)  # Purchase Ref
        sheet.set_column('B:B', 25)  # Vendor
        sheet.set_column('C:C', 35)  # Product
        sheet.set_column('D:D', 15)  # Purity
        sheet.set_column('E:E', 12)  # Qty
        sheet.set_column('F:J', 18)  # Remaining financial columns

        row = 0

        sheet.merge_range(row, 0, row, 9, 'Capital Gain Report', title_format)

        row += 2

        sheet.write(row, 0, 'From Date', header_format)
        sheet.write(row, 1, str(data.get('date_from', '')), text_format)
        
        row += 1

        sheet.write(row, 0, 'To Date', header_format)
        sheet.write(row, 1, str(data.get('date_to', '')), text_format)

        row += 2

        # =====================================================
        # TABLE HEADERS
        # =====================================================

        headers = [
            'Purchase Ref', 'Vendor', 'Product', 'Purity', 'Qty', 
            'PO Fine Rate', 'Purchase Value', 'Paid day Fine rate', 
            'Value', 'Gain / Loss'
        ]
        
        for col_num, header_title in enumerate(headers):
            sheet.write(row, col_num, header_title, header_format)

        row += 1

        # =====================================================
        # DATA LINES
        # =====================================================

        for po in purchase_orders:
            # Filter: Find related bills that are in 'posted' state and fully 'paid'
            paid_invoices = po.invoice_ids.filtered(
                lambda inv: inv.state == 'posted' and inv.payment_state == 'paid'
            )
            
            # Skip this PO entirely if it doesn't have any paid vendor bills
            if not paid_invoices:
                continue
                
            # Determine target payment/bill date from the latest paid invoice
            # (Fallback to date_order if invoice date is somehow missing)
            latest_paid_invoice = paid_invoices[0]
            target_date = latest_paid_invoice.invoice_date or po.date_order or datetime.today()

            for line in po.order_line:
                
                qty = line.product_qty or 0.0
                po_rate = line.gold_rate or 0.0
                
                # 1. Purchase Value = Subtotal PO (Excluded Tax)
                # purchase_value = line.price_subtotal or 0.0
                purchase_value = qty * po_rate  
                
                # 2. Paid day fine rate 
                paid_day_rec = self.env['fine.rate.master'].search([
                    ('date', '=', target_date)
                ], order='date desc, id desc', limit=1)
                
                paid_day_fine_rate = paid_day_rec.fine_rate or 0.0
                
                # 3. Value = Qty * Paid day fine rate
                calculated_value = qty * paid_day_fine_rate
                
                # 4. Gain / Loss = Value - Purchase Value
                gain_loss = purchase_value - calculated_value

                # Select styling based on gain or loss outcome
                gain_loss_style = positive_gain_format if gain_loss >= 0 else negative_loss_format

                # Write values to row
                sheet.write(row, 0, po.name or '', text_format)
                sheet.write(row, 1, po.partner_id.name or '', text_format)
                sheet.write(row, 2, line.product_id.display_name or '', text_format)
                sheet.write(row, 3, line.purity_id.name if line.purity_id else '', text_format)
                sheet.write(row, 4, qty, number_format)
                sheet.write(row, 5, po_rate, number_format)
                sheet.write(row, 6, purchase_value, number_format)
                sheet.write(row, 7, paid_day_fine_rate, number_format)
                sheet.write(row, 8, calculated_value, number_format)
                sheet.write(row, 9, gain_loss, gain_loss_style)

                row += 1


# from odoo import models
# from datetime import datetime


# class PurchaseCapitalGainXlsx(models.AbstractModel):
#     _name = 'report.purchase_fine_rate_variance_report.capital_gain_xlsx'
#     _inherit = 'report.report_xlsx.abstract'

#     def generate_xlsx_report(self, workbook, data, purchase_orders):

#         sheet = workbook.add_worksheet('Capital Gain Report')


#         title_format = workbook.add_format({
#             'bold': True,
#             'align': 'center',
#             'font_size': 14,
#             'border': 1,
#         })

#         header_format = workbook.add_format({
#             'bold': True,
#             'border': 1,
#             'align': 'center',
#             'bg_color': '#D9D9D9',
#         })

#         text_format = workbook.add_format({
#             'border': 1,
#         })

#         number_format = workbook.add_format({
#             'border': 1,
#             'num_format': '0.000',
#         })

#         positive_gain_format = workbook.add_format({
#             'border': 1,
#             'num_format': '0.000',
#             'bold': True,
#             'font_color': 'green',
#         })

#         negative_loss_format = workbook.add_format({
#             'border': 1,
#             'num_format': '0.000',
#             'bold': True,
#             'font_color': 'red',
#         })

#         note_format = workbook.add_format({
#             'font_size': 10,
#             'align': 'left'
#         })



#         sheet.set_column('A:A', 20)  # Purchase Ref
#         sheet.set_column('B:B', 25)  # Vendor
#         sheet.set_column('C:C', 35)  # Product
#         sheet.set_column('D:D', 12)  # Qty
#         sheet.set_column('E:I', 18)  # Remaining financial columns

#         row = 0


#         sheet.merge_range(row, 0, row, 8, 'Capital Gain Report', title_format)

#         row += 2


#         sheet.write(row, 0, 'From Date', header_format)
#         sheet.write(row, 1, str(data.get('date_from', '')), text_format)
        
        
#         row += 1

#         sheet.write(row, 0, 'To Date', header_format)
#         sheet.write(row, 1, str(data.get('date_to', '')), text_format)

#         row += 2

#         # =====================================================
#         # TABLE HEADERS
#         # =====================================================

#         headers = [
#             'Purchase Ref', 'Vendor', 'Product', 'Qty', 
#             'PO Fine Rate', 'Purchase Value', 'Paid day Fine rate', 
#             'Value', 'Gain / Loss'
#         ]
        
#         for col_num, header_title in enumerate(headers):
#             sheet.write(row, col_num, header_title, header_format)

#         row += 1

#         # =====================================================
#         # DATA LINES
#         # =====================================================

#         for po in purchase_orders:
#             for line in po.order_line:
                
#                 qty = line.product_qty or 0.0
#                 po_rate = line.gold_rate or 0.0
                
#                 # 1. Purchase Value = Subtotal PO (Excluded Tax)
#                 purchase_value = line.price_subtotal or 0.0
                
#                 # 2. Paid day fine rate 
#                 # (Querying your master table using either PO date or invoice date context)
#                 target_date = po.date_order or datetime.today()
#                 paid_day_rec = self.env['fine.rate.master'].search([
#                     ('date', '<=', target_date)
#                 ], order='date desc, id desc', limit=1)
                
#                 paid_day_fine_rate = paid_day_rec.fine_rate or 0.0
                
#                 # 3. Value = Qty * Paid day fine rate
#                 calculated_value = qty * paid_day_fine_rate
                
#                 # 4. Gain / Loss = Value - Purchase Value
#                 gain_loss = calculated_value - purchase_value

#                 # Select styling based on gain or loss outcome
#                 gain_loss_style = positive_gain_format if gain_loss >= 0 else negative_loss_format

#                 # Write values to row
#                 sheet.write(row, 0, po.name or '', text_format)
#                 sheet.write(row, 1, po.partner_id.name or '', text_format)
#                 sheet.write(row, 2, line.product_id.display_name or '', text_format)
#                 sheet.write(row, 3, qty, number_format)
#                 sheet.write(row, 4, po_rate, number_format)
#                 sheet.write(row, 5, purchase_value, number_format)
#                 sheet.write(row, 6, paid_day_fine_rate, number_format)
#                 sheet.write(row, 7, calculated_value, number_format)
#                 sheet.write(row, 8, gain_loss, gain_loss_style)

#                 row += 1