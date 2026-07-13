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
        header_format = workbook.add_format({'bold': True, 'bg_color': '#4F81BD', 'font_color': 'white', 'border': 1})
        cell_format = workbook.add_format({'border': 1})
        date_format = workbook.add_format({'border': 1, 'num_format': 'dd/mm/yyyy'})
        
        # Set column widths
        sheet.set_column('A:A', 15)
        sheet.set_column('B:B', 20)
        sheet.set_column('C:C', 25)
        sheet.set_column('D:D', 15)
        sheet.set_column('E:E', 15)
        sheet.set_column('F:F', 15)
        sheet.set_column('G:G', 20)
        sheet.set_column('H:H', 15)
        sheet.set_column('I:I', 15)
        sheet.set_column('J:J', 15)
        sheet.set_column('K:K', 20)
        sheet.set_column('L:L', 15)
        sheet.set_column('M:M', 15)
        sheet.set_column('N:N', 15)
        sheet.set_column('O:O', 15)
        sheet.set_column('P:P', 15)
        sheet.set_column('Q:Q', 15)
        sheet.set_column('R:R', 15)
        sheet.set_column('S:S', 15)
        sheet.set_column('T:T', 15)
        sheet.set_column('U:U', 15)
        sheet.set_column('V:V', 15)
        sheet.set_column('W:W', 15)
        sheet.set_column('X:X', 15)
        sheet.set_column('Y:Y', 15)
        sheet.set_column('Z:Z', 15)
        sheet.set_column('AA:AA', 15)
        sheet.set_column('AB:AB', 15)
        sheet.set_column('AC:AC', 15)
        sheet.set_column('AD:AD', 15)
        sheet.set_column('AE:AE', 15)
        sheet.set_column('AF:AF', 15)
        sheet.set_column('AG:AG', 15)
        sheet.set_column('AH:AH', 15)
        sheet.set_column('AI:AI', 15)
        sheet.set_column('AJ:AJ', 15)
        sheet.set_column('AK:AK', 15)
        sheet.set_column('AL:AL', 15)
        sheet.set_column('AM:AM', 15)
        sheet.set_column('AN:AN', 15)
        sheet.set_column('AO:AO', 20)
        
        # Write headers
        headers = [
            'PO Number',
            'Date',
            'Vendor',
            'Vendor Reference',
            'Branch',
            'State',
            'Total Amount',
            'Currency',
            'Product',
            'Gross Weight',
            'Received',
            'Unit Price',
            'Subtotal',
            'Tax',
            'UoM',
            'Purity',
            
            'Rate(g)',
            'Metal Amount',
            'MC Type',
            'Rate Value',
            'MC%',
            'Amount MC',
            'MC Fine Weight',
            'MC Amount',
            'Total Fine',
            'Packaging Qty',
            'Packaging',
            'Bank',
            'Cash',
            'Card',
            'Upi',
            
            'Diamond Weight',
            'Stone Weight',
            'Other Weight',
            'Diamond Amount',
            'Stone Amount',
            'Other Amount',
            'Taxable Value (Sub Total)',
            'CGST',
            'SGST',
            'Round Off',
            'Bill Amount',
            'Scheme'
        ]
        
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
                sheet.write(row, 6, order.amount_total or 0, cell_format)
                sheet.write(row, 7, order.currency_id.name or '', cell_format)
                sheet.write(row, 8, line.product_id.name or '', cell_format)
                sheet.write(row, 9, line.product_qty or 0, cell_format)
                sheet.write(row, 10, line.qty_received or 0, cell_format)
                sheet.write(row, 11, line.price_unit or 0, cell_format)
                sheet.write(row, 12, line.price_subtotal or 0, cell_format)
                sheet.write(row, 13, line.price_tax or 0, cell_format)
                sheet.write(row, 14, line.product_uom.name or '', cell_format)
                sheet.write(row, 15, line.purity_id.name if line.purity_id else '', cell_format)
                sheet.write(row, 16, line.gross_weight or 0, cell_format)
                sheet.write(row, 17, line.gold_rate or 0, cell_format)
                sheet.write(row, 18, line.metal_amount or 0, cell_format)
                mc_type = ''
                if hasattr(line, 'purchase_making_charge_type') and line.purchase_making_charge_type:
                    selection_dict = dict(line._fields['purchase_making_charge_type'].selection) if 'purchase_making_charge_type' in line._fields else {}
                    mc_type = selection_dict.get(line.purchase_making_charge_type, line.purchase_making_charge_type)
                sheet.write(row, 19, mc_type, cell_format)
                sheet.write(row, 20, line.rate_value or 0, cell_format)
                sheet.write(row, 21, line.mc_percent or 0, cell_format)
                sheet.write(row, 22, line.mc_amount or 0, cell_format)
                sheet.write(row, 23, line.mc_fine or 0, cell_format)
                sheet.write(row, 24, line.purchase_making_charge_value or 0 if hasattr(line, 'purchase_making_charge_value') else 0, cell_format)
                sheet.write(row, 25, line.total_fine or 0, cell_format)
                sheet.write(row, 26, line.product_packaging_qty or 0 if hasattr(line, 'product_packaging_qty') else 0, cell_format)
                sheet.write(row, 27, line.product_packaging_id.name if hasattr(line, 'product_packaging_id') and line.product_packaging_id else '', cell_format)
                
                sheet.write(row, 28, bank_amt if first_line else '', cell_format)
                sheet.write(row, 29, cash_amt if first_line else '', cell_format)
                sheet.write(row, 30, card_amt if first_line else '', cell_format)
                sheet.write(row, 31, upi_amt if first_line else '', cell_format)
                
                # New columns
                gross_weight = line.gross_weight or 0
                diamond_weight = line.purchase_diamond_weight_gm or 0 if hasattr(line, 'purchase_diamond_weight_gm') else 0
                stone_weight = line.purchase_stone_weight or 0 if hasattr(line, 'purchase_stone_weight') else 0
                other_weight = gross_weight - (line.net_weight or 0 if hasattr(line, 'net_weight') else 0) - diamond_weight - stone_weight
                diamond_amount = diamond_weight * (line.purchase_diamond_rate or 0 if hasattr(line, 'purchase_diamond_rate') else 0)
                stone_amount = stone_weight * (line.purchase_stone_rate or 0 if hasattr(line, 'purchase_stone_rate') else 0)
                other_amount = other_weight * (line.gold_rate or 0)
                taxable_value = line.price_subtotal or 0
                cgst = line.price_tax / 2 if line.price_tax else 0
                sgst = line.price_tax / 2 if line.price_tax else 0
                round_off = order.amount_total - (order.amount_untaxed + order.amount_tax) if hasattr(order, 'amount_total') else 0
                bill_amount = order.amount_total or 0
                
                sheet.write(row, 32, gross_weight, cell_format)
                sheet.write(row, 33, diamond_weight, cell_format)
                sheet.write(row, 34, stone_weight, cell_format)
                sheet.write(row, 35, other_weight, cell_format)
                sheet.write(row, 36, diamond_amount, cell_format)
                sheet.write(row, 37, stone_amount, cell_format)
                sheet.write(row, 38, other_amount, cell_format)
                sheet.write(row, 39, taxable_value, cell_format)
                sheet.write(row, 40, cgst, cell_format)
                sheet.write(row, 41, sgst, cell_format)
                sheet.write(row, 42, round_off, cell_format)
                sheet.write(row, 43, bill_amount if first_line else '', cell_format)
                sheet.write(row, 44, order.active_scheme_id.name if first_line and hasattr(order, 'active_scheme_id') and order.active_scheme_id else '', cell_format)
                
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
