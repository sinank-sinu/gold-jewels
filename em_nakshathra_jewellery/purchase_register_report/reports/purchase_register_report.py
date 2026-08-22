# -*- coding: utf-8 -*-

from odoo import models, _
from odoo.exceptions import UserError


class PurchaseRegisterXlsx(models.AbstractModel):
    _name = 'report.purchase_register_report.purchase_register_xlsx'
    _inherit = 'report.report_xlsx.abstract'
    _description = 'Purchase Register XLSX Report'

    def generate_xlsx_report(self, workbook, data, objects):
        sheet = workbook.add_worksheet('Purchase Register')
        
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
            'PO Number',                  # 0
            'Date',                       # 1
            'Vendor',                     # 2
            'Vendor Reference',           # 3
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
            'Received',                   # 15
            'Rate(g)',                    # 16
            'Metal Amount',               # 17
            'MC Type',                    # 18
            'Rate Value',                 # 19
            'MC%',                        # 20
            'Amount MC',                  # 21
            'MC Fine Weight',             # 22
            'MC Amount',                  # 23
            'Total Fine',                 # 24
            'Packaging Qty',              # 25
            'Packaging',                  # 26
            'Diamond Amount',             # 27
            'Stone Amount',               # 28
            'Other Amount',               # 29
            'Unit Price',                 # 30
            'Subtotal',                   # 31
            'Taxable Value (Sub Total)',  # 32
            'CGST',                       # 33
            'SGST',                       # 34
            'Tax',                        # 35
            'Round Off',                  # 36
            'Bill Amount',                # 37
            'Total Amount',               # 38
            'Bank',                       # 39
            'Cash',                       # 40
            'Card',                       # 41
            'UPI'                         # 42
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
            
            # Get payments from invoices linked to this purchase order
            invoice_ids = order.invoice_ids.filtered(lambda m: m.move_type in ('in_invoice', 'in_refund'))
            
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
                sheet.write(row, 3, order.partner_ref or '', cell_format)
                sheet.write(row, 4, order.branch_id.name if order.branch_id else '', cell_format)
                sheet.write(row, 5, dict(order._fields['state'].selection).get(order.state, ''), cell_format)
                sheet.write(row, 6, order.currency_id.name or '', cell_format)
                sheet.write(row, 7, line.product_id.name or '', cell_format)
                sheet.write(row, 8, line.product_uom.name or '', cell_format)
                sheet.write(row, 9, line.purity_id.name if line.purity_id else '', cell_format)
                
                # New columns/values computation
                gross_weight = line.product_qty or 0
                diamond_weight = line.diamond_weight_gm or 0 if hasattr(line, 'diamond_weight_gm') else 0
                stone_weight = line.stone_weight or 0 if hasattr(line, 'stone_weight') else 0
                net_weight = line.net_weight or 0 if hasattr(line, 'net_weight') else 0
                other_weight = max(0, gross_weight - net_weight - diamond_weight - stone_weight)
                diamond_amount = line.diamond_rate or 0 if hasattr(line, 'diamond_rate') else 0
                stone_amount = line.stone_rate or 0 if hasattr(line, 'stone_rate') else 0
                other_amount = other_weight * (line.gold_rate or 0)
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
                sheet.write(row, 15, line.qty_received or 0, cell_format)
                
                # Metal & Charges
                sheet.write(row, 16, line.gold_rate or 0, cell_format)
                sheet.write(row, 17, line.metal_amount or 0, cell_format)
                mc_type = ''
                if hasattr(line, 'purchase_making_charge_type') and line.purchase_making_charge_type:
                    selection_dict = dict(line._fields['purchase_making_charge_type'].selection) if 'purchase_making_charge_type' in line._fields else {}
                    mc_type = selection_dict.get(line.purchase_making_charge_type, line.purchase_making_charge_type)
                sheet.write(row, 18, mc_type, cell_format)
                sheet.write(row, 19, line.rate_value or 0, cell_format)
                sheet.write(row, 20, line.mc_percent or 0, cell_format)
                sheet.write(row, 21, line.mc_amount or 0, cell_format)
                sheet.write(row, 22, line.mc_fine or 0, cell_format)
                sheet.write(row, 23, line.purchase_making_charge_value or 0 if hasattr(line, 'purchase_making_charge_value') else 0, cell_format)
                sheet.write(row, 24, line.total_fine or 0, cell_format)
                sheet.write(row, 25, line.product_packaging_qty or 0 if hasattr(line, 'product_packaging_qty') else 0, cell_format)
                sheet.write(row, 26, line.product_packaging_id.name if hasattr(line, 'product_packaging_id') and line.product_packaging_id else '', cell_format)
                sheet.write(row, 27, diamond_amount, cell_format)
                sheet.write(row, 28, stone_amount, cell_format)
                sheet.write(row, 29, other_amount, cell_format)
                sheet.write(row, 30, line.price_unit or 0, cell_format)
                
                # Billing & Taxes
                sheet.write(row, 31, line.price_subtotal or 0, cell_format)
                sheet.write(row, 32, taxable_value, cell_format)
                sheet.write(row, 33, cgst, cell_format)
                sheet.write(row, 34, sgst, cell_format)
                sheet.write(row, 35, line.price_tax or 0, cell_format)
                sheet.write(row, 36, round_off, cell_format)
                sheet.write(row, 37, bill_amount if first_line else 0, cell_format)
                sheet.write(row, 38, order.amount_total or 0, cell_format)
                
                # Payments & Settlements
                sheet.write(row, 39, bank_amt if first_line else 0, cell_format)
                sheet.write(row, 40, cash_amt if first_line else 0, cell_format)
                sheet.write(row, 41, card_amt if first_line else 0, cell_format)
                sheet.write(row, 42, upi_amt if first_line else 0, cell_format)
                
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
