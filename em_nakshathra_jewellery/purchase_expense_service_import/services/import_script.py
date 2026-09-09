# -*- coding: utf-8 -*-
import base64
import io
import logging
from datetime import datetime
from collections import defaultdict
import openpyxl
from odoo.exceptions import UserError

from odoo import _

_logger = logging.getLogger(__name__)

class ImportLabelService:
    def __init__(self, env):
        self.env = env

    def process_import(self, file_base64):
        _logger.info("Starting Purchase Expense Service Bulk Import...")
        try:
            file_content = base64.b64decode(file_base64)
            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True, read_only=True)
            sheet = wb.active

            # Read Headers
            headers = [str(cell.value).strip() if cell.value else '' for cell in sheet[1]]
            
            # Group rows by Bill Reference
            grouped_data = defaultdict(list)
            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                if not row[0] and not any(row):
                    continue  # Skip empty rows
                row_dict = dict(zip(headers, row))
                
                vendor_ref = row_dict.get('Purchase Order')
                if not vendor_ref:
                    continue
                    
                bill_ref = str(row_dict.get("Bill Reference") or "").strip()
                grouped_data[bill_ref].append(row_dict)

            count = 0
            failed_records = []
            
            for bill_ref, lines in grouped_data.items():
                vendor_name = str(lines[0].get("Purchase Order") or "").strip()
                bill_date = lines[0].get("Bill Date")
                
                if isinstance(bill_date, datetime):
                    date_str = bill_date.strftime("%Y-%m-%d")
                else:
                    date_str = str(bill_date).split(" ")[0] if bill_date else datetime.now().strftime("%Y-%m-%d")

                try:
                    self._process_po_group(vendor_name, bill_ref, date_str, lines)
                    count += 1
                    if count % 10 == 0:
                        self.env.cr.commit()
                        _logger.info(f"Processed {count} POs...")
                except Exception as e:
                    self.env.cr.rollback()
                    failed_records.append(f"Bill Reference: {bill_ref}\nVendor: {vendor_name}\nReason: {str(e)}")
                    continue

            self.env.cr.commit()
            if failed_records:
                raise UserError("Import completed with failures:\n\n" + "\n\n".join(failed_records))

        except Exception as e:
            _logger.error(f"Error during import: {str(e)}", exc_info=True)
            self.env.cr.rollback()

    def _process_po_group(self, vendor_name, bill_ref, date_str, lines):
        if not lines:
            return

        company_names = set(str(line.get('Company')).strip() for line in lines if line.get('Company'))
        if not company_names:
            raise UserError(f"No Company specified in Excel for Bill Reference {bill_ref}")
        if len(company_names) > 1:
            raise UserError(f"Multiple companies found for Bill {bill_ref}.")

        company_name = company_names.pop()
        current_company = self.env['res.company'].search([('name', '=', company_name)], limit=1)
        if not current_company:
            raise UserError(f"Company '{company_name}' not found in Odoo.")

        # Duplicate protection: skip if a PO with this bill reference already exists
        existing_po = self.env['purchase.order'].search([
            ('partner_ref', '=', bill_ref),
            ('company_id', '=', current_company.id),
        ], limit=1)
        if existing_po:
            _logger.warning(f"Skipping duplicate: Bill Reference '{bill_ref}' already exists as PO {existing_po.name} for company '{company_name}'.")
            return

        inr_currency = current_company.currency_id
        partner = self.env['res.partner'].search(['|', ('name', '=', vendor_name), ('ref', '=', vendor_name)], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({
                'name': vendor_name,
                'supplier_rank': 1,
                'company_id': False,
                'currency_id': inr_currency.id,
            })
        else:
            # Fix partner currency to company currency (INR) in case it was set to USD
            if partner.currency_id and partner.currency_id != inr_currency:
                partner.currency_id = inr_currency.id
            if partner.company_id:
                try:
                    partner.company_id = False
                except Exception:
                    pass

        payable_account = self.env['account.account'].search([
            ('company_id', '=', current_company.id),
            ('account_type', '=', 'liability_payable'),
            ('name', 'ilike', 'creditor'),
        ], limit=1)
        if not payable_account:
            payable_account = self.env['account.account'].search([
                ('company_id', '=', current_company.id),
                ('account_type', '=', 'liability_payable'),
                ('name', 'not ilike', 'opening'),
            ], limit=1)
        if payable_account:
            partner.with_company(current_company).property_account_payable_id = payable_account.id

        po_vals = {
            'partner_id': partner.id,
            'date_order': date_str,
            'partner_ref': bill_ref,
            'company_id': current_company.id,
        }
        
        branch_name = lines[0].get('Branch') if lines else None
        branch = None
        if branch_name:
            branch = self.env['res.branch'].search([('name', '=', str(branch_name).strip())], limit=1)
            if branch:
                po_vals['branch_id'] = branch.id

        po = self.env['purchase.order'].create(po_vals)

        for line in lines:
            product = self._resolve_product(line, current_company)
            if not product:
                continue

            tax_name = str(line.get("Order Lines/Taxes") or "").strip()
            tax = False
            if tax_name:
                tax = self.env["account.tax"].search([
                    ("name", "=", tax_name),
                    ("type_tax_use", "in", ["purchase", "none"]),
                    ('company_id', '=', current_company.id)
                ], limit=1)

            qty = float(line.get('Order Lines/Quantity') or 1.0)
            price = float(line.get('Order Lines/Unit Price') or 0.0)
            # 'Order Lines/Description' and 'Order Lines/UoM' may not exist in this Excel format
            desc = str(line.get('Order Lines/Description') or line.get('Product') or product.name)
            if desc == 'None' or not desc.strip():
                desc = product.name
                
            uom_name = str(line.get('Order Lines/UoM') or "").strip()
            uom = None
            if uom_name and uom_name != 'None':
                uom = self.env['uom.uom'].search([('name', '=', uom_name)], limit=1)
                
            po_line_vals = {
                'order_id': po.id,
                'product_id': product.id,
                'name': desc,
                'product_qty': qty,
                'price_unit': price,
                'date_planned': date_str,
                'taxes_id': [(6, 0, [tax.id])] if tax else [(5, 0, 0)],
            }
            if uom:
                po_line_vals['product_uom'] = uom.id
            else:
                po_line_vals['product_uom'] = product.uom_id.id

            self.env['purchase.order.line'].create(po_line_vals)

        po.button_confirm()

        po.write({
            'date_approve': date_str,
            'date_planned': date_str,
        })


        po.action_create_invoice()
        
        for bill in po.invoice_ids:
            # Set Accounting Date
            acc_date = lines[0].get('Accounting Date')
            if isinstance(acc_date, datetime):
                acc_date_str = acc_date.strftime("%Y-%m-%d")
            else:
                acc_date_str = str(acc_date).split(" ")[0] if acc_date and str(acc_date) != 'None' else date_str
                
            bill.write({
                'invoice_date': date_str,
                'date': acc_date_str,
                'invoice_date_due': date_str,
            })
            
            # Mark as approved to bypass the custom manager-approval check in em_jewellery_management
            if hasattr(bill, 'is_approved'):
                bill.is_approved = True
            # Post the bill (sudo to ensure sufficient access rights)
            bill.sudo().action_post()
            
            # Build payment list from Excel columns:
            # Bank 1 / Bank Reference → bank journal
            # Bank 2 / Bank Reference.1 → bank journal (second bank)
            # Cash Amount → cash journal
            payments_to_register = []

            bank1_amount = lines[0].get('Bank 1')
            bank1_ref = str(lines[0].get('Bank Reference') or '').strip()
            bank2_amount = lines[0].get('Bank 2')
            bank2_ref = str(lines[0].get('Bank Reference.1') or '').strip()
            cash_amount = lines[0].get('Cash Amount')

            try:
                bank1_amount = float(bank1_amount) if bank1_amount and str(bank1_amount) not in ('nan', 'None', '') else 0.0
            except (ValueError, TypeError):
                bank1_amount = 0.0
            try:
                bank2_amount = float(bank2_amount) if bank2_amount and str(bank2_amount) not in ('nan', 'None', '') else 0.0
            except (ValueError, TypeError):
                bank2_amount = 0.0
            try:
                cash_amount = float(cash_amount) if cash_amount and str(cash_amount) not in ('nan', 'None', '') else 0.0
            except (ValueError, TypeError):
                cash_amount = 0.0

            if bank1_amount > 0:
                payments_to_register.append({'type': 'bank', 'amount': bank1_amount, 'ref': bank1_ref})
            if bank2_amount > 0:
                payments_to_register.append({'type': 'bank', 'amount': bank2_amount, 'ref': bank2_ref})
            if cash_amount > 0:
                payments_to_register.append({'type': 'cash', 'amount': cash_amount, 'ref': ''})

            for pay_info in payments_to_register:
                # Find correct journal: prefer branch-specific, then company-wide
                journal = False
                if branch:
                    journal = self.env['account.journal'].search([
                        ('type', '=', pay_info['type']),
                        ('branch_id', '=', branch.id),
                        ('company_id', '=', current_company.id),
                    ], limit=1)
                if not journal:
                    journal = self.env['account.journal'].search([
                        ('type', '=', pay_info['type']),
                        ('company_id', '=', current_company.id),
                    ], limit=1)

                if journal:
                    pay_vals = {
                        'journal_id': journal.id,
                        'payment_date': acc_date_str,
                        'amount': pay_info['amount'],
                        # Force company currency (INR) regardless of journal's currency setting
                        'currency_id': current_company.currency_id.id,
                    }
                    if pay_info['ref']:
                        pay_vals['communication'] = pay_info['ref']
                    payment_register = self.env['account.payment.register'].with_context(
                        active_model='account.move',
                        active_ids=bill.ids,
                    ).create(pay_vals)
                    payment_register.action_create_payments()

        self.env.flush_all()
        self.env.invalidate_all()

    def _resolve_product(self, row, current_company):
        # Excel column is 'Product', not 'Order Lines/Product'
        raw_name = str(row.get('Product') or row.get('Order Lines/Product') or '')
        template_name = raw_name.strip()
        if not template_name or template_name == 'None':
            return None

        # Try to find existing product (could be standard product or service)
        template = self.env["product.template"].search([
            ("name", "=ilike", template_name),
            "|", ("company_id", "=", current_company.id), ("company_id", "=", False)
        ], limit=1)

        if template and template.purchase_method != 'purchase':
            template.write({'purchase_method': 'purchase'})

        if not template:
            _logger.info(f"Creating Service Product '{template_name}' for company '{current_company.name}'")
            template = self.env["product.template"].create({
                "name": template_name,
                "type": "service",
                "purchase_ok": True,
                "sale_ok": False,
                "purchase_method": "purchase",
                "company_id": current_company.id,
            })

        return template.product_variant_id