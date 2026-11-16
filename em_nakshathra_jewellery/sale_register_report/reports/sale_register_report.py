# -*- coding: utf-8 -*-

from odoo import models, _
from odoo.exceptions import UserError


class SaleRegisterXlsx(models.AbstractModel):
    _name = 'report.sale_register_report.sale_register_xlsx'
    _inherit = 'report.report_xlsx.abstract'
    _description = 'Sale Register XLSX Report'

    def generate_xlsx_report(self, workbook, data, objects):
        # Only confirmed orders (locked orders also stay in 'sale'): exclude Quotation, Quotation Sent and Cancelled
        if not objects and data and data.get('so_ids'):
            objects = self.env['sale.order'].browse(data['so_ids'])
        objects = objects.filtered(lambda o: o.state == 'sale')

        sheet = workbook.add_worksheet('Sale Register')
        
        # Define formats
        bold_format = workbook.add_format({'bold': True})
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#1F4E78',  # Professional dark blue
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True
        })
        cell_format = workbook.add_format({'border': 1})
        date_format = workbook.add_format({
            'border': 1,
            'num_format': 'dd/mm/yyyy',
            'align': 'center',
            'valign': 'vcenter'
        })
        
        # Write headers
        headers = [
            'SO Number',                  # 0
            'Date',                       # 1
            'Customer',                   # 2
            'Salesperson',                # 3
            'Branch',                     # 4
            'State',                      # 5
            'Currency',                   # 6
            'Product',                    # 7
            'UoM',                        # 8
            'Purity',                     # 9
            'Gross Weight',               # 10
            'Net Weight',                 # 11
            'Diamond Weight',             # 12
            'Stone Weight',               # 13
            'Other Weight',               # 14
            'Delivered',                  # 15
            'Fine Weight (g)',            # 16
            'Gold Rate(g)',               # 17
            'Metal Amount',               # 18
            'MC%',                        # 19
            'MC Amount',                  # 20
            'Diamond Amount',             # 21
            'Stone Amount',               # 22
            'Other Amount',               # 23
            'Unit Price',                 # 24
            'Subtotal',                   # 25
            'Taxable Value (Sub Total)',  # 26
            'CGST',                       # 27
            'SGST',                       # 28
            'Tax',                        # 29
            'Round Off',                  # 30
            'Bill Amount',                # 31
            'Total Amount',               # 32
            'Bank',                       # 33
            'Cash',                       # 34
            'Card',                       # 35
            'UPI',                        # 36
            'Old Gold Amount',            # 37
            'Sale Return Price',          # 38
            'Scheme'                      # 39
        ]
        
        # Set row height and column widths
        sheet.set_row(0, 26)  # Professional spacious header row
        for col, header in enumerate(headers):
            sheet.set_column(col, col, max(len(header) + 4, 12))
        
        for col, header in enumerate(headers):
            sheet.write(0, col, header, header_format)
        
        # Write data
        row = 1
        for order in objects:
            # Get payment methods from invoice payments
            bank_amt = 0
            cash_amt = 0
            card_amt = 0
            upi_amt = 0
            
            # Get payments from invoices linked to this sale order
            invoice_ids = order.invoice_ids.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund'))
            
            if invoice_ids:
                processed_payments = self.env['account.payment']
                for inv in invoice_ids:
                    # 1. Reconciled payments (exact applied amount)
                    if hasattr(inv, '_get_reconciled_invoices_partials'):
                        partials, _ = inv._get_reconciled_invoices_partials()
                        for partial, amount, counterpart_line in partials:
                            payment = counterpart_line.move_id.payment_id
                            if payment and payment.state == 'posted':
                                journal_name = (payment.journal_id.name or '').lower()
                                journal_code = (payment.journal_id.code or '').lower()
                                
                                if 'card' in journal_name or 'card' in journal_code:
                                    card_amt += amount
                                elif 'upi' in journal_name or 'upi' in journal_code:
                                    upi_amt += amount
                                elif 'cash' in journal_name or 'cash' in journal_code:
                                    cash_amt += amount
                                elif 'bank' in journal_name or 'bank' in journal_code:
                                    bank_amt += amount
                                processed_payments |= payment
                    
                    # 2. Custom payment_to_id
                    if hasattr(inv, 'payment_to_id') and inv.payment_to_id:
                        payment = inv.payment_to_id
                        if payment.state == 'posted' and payment not in processed_payments:
                            journal_name = (payment.journal_id.name or '').lower()
                            journal_code = (payment.journal_id.code or '').lower()
                            if 'card' in journal_name or 'card' in journal_code:
                                card_amt += payment.amount
                            elif 'upi' in journal_name or 'upi' in journal_code:
                                upi_amt += payment.amount
                            elif 'cash' in journal_name or 'cash' in journal_code:
                                cash_amt += payment.amount
                            elif 'bank' in journal_name or 'bank' in journal_code:
                                bank_amt += payment.amount
                            processed_payments |= payment

                    # 3. Custom payment_ids
                    if hasattr(inv, 'payment_ids') and inv.payment_ids:
                        for payment in inv.payment_ids:
                            if payment.state == 'posted' and payment not in processed_payments:
                                journal_name = (payment.journal_id.name or '').lower()
                                journal_code = (payment.journal_id.code or '').lower()
                                if 'card' in journal_name or 'card' in journal_code:
                                    card_amt += payment.amount
                                elif 'upi' in journal_name or 'upi' in journal_code:
                                    upi_amt += payment.amount
                                elif 'cash' in journal_name or 'cash' in journal_code:
                                    cash_amt += payment.amount
                                elif 'bank' in journal_name or 'bank' in journal_code:
                                    bank_amt += payment.amount
                                processed_payments |= payment

            first_line = True
            for line in order.order_line:
                sheet.write(row, 0, order.name or '', cell_format)
                sheet.write(row, 1, order.date_order.date() if order.date_order else '', date_format)
                sheet.write(row, 2, order.partner_id.name or '', cell_format)
                sheet.write(row, 3, order.user_id.name if order.user_id else '', cell_format)
                sheet.write(row, 4, order.branch_id.name if hasattr(order, 'branch_id') and order.branch_id else '', cell_format)
                sheet.write(row, 5, dict(order._fields['state'].selection).get(order.state, ''), cell_format)
                sheet.write(row, 6, order.currency_id.name or '', cell_format)
                sheet.write(row, 7, line.product_id.name or '', cell_format)
                sheet.write(row, 8, line.product_uom.name or '', cell_format)
                sheet.write(row, 9, line.purity_id.name if hasattr(line, 'purity_id') and line.purity_id else '', cell_format)
                
                # New columns/values computation
                gross_weight = line.product_uom_qty or 0 if hasattr(line, 'product_uom_qty') else 0
                diamond_weight = line.sale_diamond_weight_gm or 0 if hasattr(line, 'sale_diamond_weight_gm') else 0
                stone_weight = line.sale_stone_weight or 0 if hasattr(line, 'sale_stone_weight') else 0
                net_weight = line.net_weight or 0 if hasattr(line, 'net_weight') else 0
                other_weight = max(0, gross_weight - net_weight - diamond_weight - stone_weight) if hasattr(line, 'net_weight') else 0
                diamond_amount = line.sale_diamond_rate or 0 if hasattr(line, 'sale_diamond_rate') else 0
                stone_amount = line.sale_stone_rate or 0 if hasattr(line, 'sale_stone_rate') else 0
                other_amount = line.other_weight_amount or 0 if hasattr(line, 'other_weight_amount') else (other_weight * (line.gold_rate or 0) if hasattr(line, 'gold_rate') else 0)
                taxable_value = line.price_subtotal or 0
                cgst = line.price_tax / 2 if line.price_tax else 0
                sgst = line.price_tax / 2 if line.price_tax else 0
                round_off = (order.amount_total or 0) - ((order.amount_untaxed or 0) + (order.amount_tax or 0)) if hasattr(order, 'amount_total') else 0
                bill_amount = order.amount_total or 0
                
                # Weights
                sheet.write(row, 10, gross_weight, cell_format)
                sheet.write(row, 11, net_weight, cell_format)
                sheet.write(row, 12, diamond_weight, cell_format)
                sheet.write(row, 13, stone_weight, cell_format)
                sheet.write(row, 14, other_weight, cell_format)
                sheet.write(row, 15, line.qty_delivered or 0, cell_format)
                sheet.write(row, 16, line.fine_weight or 0 if hasattr(line, 'fine_weight') else 0, cell_format)
                
                # Rates & Valuations
                sheet.write(row, 17, line.gold_rate or 0 if hasattr(line, 'gold_rate') else 0, cell_format)
                sheet.write(row, 18, line.metal_amount or 0 if hasattr(line, 'metal_amount') else 0, cell_format)
                sheet.write(row, 19, line.mc_percent_actual or 0 if hasattr(line, 'mc_percent_actual') else 0, cell_format)
                sheet.write(row, 20, line.mc_amount_actual or 0 if hasattr(line, 'mc_amount_actual') else 0, cell_format)
                sheet.write(row, 21, diamond_amount, cell_format)
                sheet.write(row, 22, stone_amount, cell_format)
                sheet.write(row, 23, other_amount, cell_format)
                sheet.write(row, 24, line.price_unit or 0, cell_format)
                
                # Billing & Taxes
                sheet.write(row, 25, line.price_subtotal or 0, cell_format)
                sheet.write(row, 26, taxable_value, cell_format)
                sheet.write(row, 27, cgst, cell_format)
                sheet.write(row, 28, sgst, cell_format)
                sheet.write(row, 29, line.price_tax or 0, cell_format)
                sheet.write(row, 30, round_off, cell_format)
                sheet.write(row, 31, bill_amount if first_line else 0, cell_format)
                sheet.write(row, 32, order.amount_total or 0, cell_format)
                
                # Payments & Settlements
                sheet.write(row, 33, bank_amt if first_line else 0, cell_format)
                sheet.write(row, 34, cash_amt if first_line else 0, cell_format)
                sheet.write(row, 35, card_amt if first_line else 0, cell_format)
                sheet.write(row, 36, upi_amt if first_line else 0, cell_format)
                sheet.write(row, 37, (order.old_gold_bill_amount or 0) if first_line and hasattr(order, 'old_gold_bill_amount') else 0, cell_format)
                sheet.write(row, 38, line.sale_return_price or 0 if hasattr(line, 'sale_return_price') else 0, cell_format)
                scheme_amount = 0
                if first_line:
                    redemption_amt = 0
                    redemptions = self.env['scheme.redemption'].search([('sale_order_id', '=', order.id)])
                    if redemptions:
                        redemption_amt = sum(redemptions.mapped('amount'))
                    
                    line_amt = 0
                    if hasattr(order, 'scheme_line_id') and order.scheme_line_id:
                        line_amt = abs(order.scheme_line_id.price_unit)
                    
                    is_scheme_line_amt = sum(abs(l.price_unit) for l in order.order_line if getattr(l, 'is_scheme_line', False))
                    
                    scheme_amount = max(redemption_amt, line_amt, is_scheme_line_amt)
                sheet.write(row, 39, scheme_amount, cell_format)
                
                first_line = False
                row += 1
        
        # Write summary
        row += 2
        sheet.write(row, 0, 'Summary', bold_format)
        row += 1
        sheet.write(row, 0, 'Total Orders:', bold_format)
        sheet.write(row, 1, len(objects), cell_format)
        row += 1
        sheet.write(row, 0, 'Total Amount:', bold_format)
        sheet.write(row, 1, sum(order.amount_total for order in objects), cell_format)
