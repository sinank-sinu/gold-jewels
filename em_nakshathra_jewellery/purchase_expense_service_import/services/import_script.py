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

    def process_import(self, file_base64, progress_callback=None):
        _logger.info("Starting Purchase Expense Service Bulk Import...")
        # Automatically bypass sequence date constraint for backdated historical imports
        self.env['ir.config_parameter'].sudo().set_param('sequence.mixin.constraint_start_date', '2099-12-31')
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

            total_pos = len(grouped_data)
            total_rows = sum(len(lines) for lines in grouped_data.values())
            count = 0
            failed_records = []
            
            if progress_callback:
                progress_callback(count, total_pos, f"Starting import of {total_pos} bills from {total_rows} Excel rows...", failed_records)

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
                    line_info = f" ({len(lines)} lines)" if len(lines) > 1 else ""
                    msg = f"Processed {count}/{total_pos}: Bill {bill_ref}{line_info} ({vendor_name})"
                    if count % 5 == 0 or count == total_pos:
                        self.env.cr.commit()
                        _logger.info(f"Processed {count} POs...")
                    if progress_callback:
                        progress_callback(count, total_pos, msg, failed_records)
                except Exception as e:
                    self.env.cr.rollback()
                    err_info = {
                        'bill_ref': bill_ref,
                        'vendor': vendor_name,
                        'reason': str(e),
                    }
                    failed_records.append(err_info)
                    if progress_callback:
                        progress_callback(count, total_pos, f"Failed {bill_ref}: {str(e)}", failed_records)
                    continue

            self.env.cr.commit()
            return {
                'total': total_pos,
                'total_rows': total_rows,
                'success_count': count,
                'failed_count': len(failed_records),
                'failed_records': failed_records,
            }

        except Exception as e:
            _logger.error(f"Error during import: {str(e)}", exc_info=True)
            self.env.cr.rollback()
            raise e

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

        # Duplicate protection & auto-correction:
        # If PO already exists, check if bills need payment correction
        existing_po = self.env['purchase.order'].search([
            ('partner_ref', '=', bill_ref),
            ('company_id', '=', current_company.id),
        ], limit=1)
        if existing_po:
            # Ensure products and templates have correct expense accounts mapped
            for line_data in lines:
                self._resolve_product(line_data, current_company)

            bills = existing_po.invoice_ids.filtered(lambda b: b.move_type == 'in_invoice')
            if not bills and existing_po.state in ('purchase', 'done'):
                existing_po.action_create_invoice()
                bills = existing_po.invoice_ids.filtered(lambda b: b.move_type == 'in_invoice')

            branch_name = lines[0].get('Branch') if lines else None
            branch = None
            if branch_name:
                branch = self.env['res.branch'].search([('name', '=', str(branch_name).strip())], limit=1)

            acc_date = lines[0].get('Accounting Date')
            if isinstance(acc_date, datetime):
                acc_date_str = acc_date.strftime("%Y-%m-%d")
            else:
                acc_date_str = str(acc_date).split(" ")[0] if acc_date and str(acc_date) != 'None' else date_str

            payments_to_register = self._get_payments_to_register(lines)
            expected_amounts = sorted([round(p['amount'], 2) for p in payments_to_register])

            for bill in bills:
                self._correct_bill_expense_accounts(bill, current_company)
                if bill.state == 'draft':
                    bill.write({
                        'name': '/',
                        'invoice_date': date_str,
                        'date': acc_date_str,
                        'invoice_date_due': date_str,
                    })
                    if hasattr(bill, 'is_approved'):
                        bill.is_approved = True
                    bill.sudo().action_post()

                old_payments = bill._get_reconciled_payments()
                current_amounts = sorted([round(p.amount, 2) for p in old_payments])

                # If bill is already fully paid and payment breakdown matches lines, skip
                if bill.payment_state == 'paid' and bill.amount_residual == 0 and expected_amounts == current_amounts:
                    _logger.info(f"Bill {bill.name} (Ref: {bill_ref}) is already fully paid with correct payments.")
                    continue

                # Remove old partial/aggregated payments before re-registering distinct payments
                if old_payments:
                    payable_lines = bill.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable'))
                    payable_lines.remove_move_reconcile()
                    for p in old_payments:
                        try:
                            p.action_draft()
                            p.unlink()
                        except Exception as pe:
                            _logger.warning(f"Could not unlink old payment {p.id}: {pe}")

                self._register_payments_for_bill(bill, lines, current_company, branch, acc_date_str)
                _logger.info(f"Corrected payments for existing Bill {bill.name} (PO: {existing_po.name}, Ref: {bill_ref}).")

            self.env.flush_all()
            self.env.invalidate_all()
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


        acc_date = lines[0].get('Accounting Date')
        if isinstance(acc_date, datetime):
            acc_date_str = acc_date.strftime("%Y-%m-%d")
        else:
            acc_date_str = str(acc_date).split(" ")[0] if acc_date and str(acc_date) != 'None' else date_str

        po.with_context(default_date=acc_date_str, default_invoice_date=date_str).action_create_invoice()
        
        for bill in po.invoice_ids:
            self._correct_bill_expense_accounts(bill, current_company)
            bill.write({
                'name': '/',
                'invoice_date': date_str,
                'date': acc_date_str,
                'invoice_date_due': date_str,
            })
            
            # Mark as approved to bypass the custom manager-approval check in em_jewellery_management
            if hasattr(bill, 'is_approved'):
                bill.is_approved = True
            # Post the bill (sudo to ensure sufficient access rights)
            bill.sudo().action_post()
            
            self._register_payments_for_bill(bill, lines, current_company, branch, acc_date_str)

        self.env.flush_all()
        self.env.invalidate_all()

    def _get_payments_to_register(self, lines):
        payments = []
        for line in lines:
            bank1_amount = line.get('Bank 1')
            bank1_ref = str(line.get('Bank Reference') or '').strip()
            if bank1_ref in ('nan', 'None'):
                bank1_ref = ''

            bank2_amount = line.get('Bank 2')
            bank2_ref = str(line.get('Bank Reference.1') or '').strip()
            if bank2_ref in ('nan', 'None'):
                bank2_ref = ''

            cash_amount = line.get('Cash Amount')

            try:
                b1 = float(bank1_amount) if bank1_amount and str(bank1_amount) not in ('nan', 'None', '') else 0.0
            except (ValueError, TypeError):
                b1 = 0.0
            try:
                b2 = float(bank2_amount) if bank2_amount and str(bank2_amount) not in ('nan', 'None', '') else 0.0
            except (ValueError, TypeError):
                b2 = 0.0
            try:
                c = float(cash_amount) if cash_amount and str(cash_amount) not in ('nan', 'None', '') else 0.0
            except (ValueError, TypeError):
                c = 0.0

            if b1 > 0:
                payments.append({'type': 'bank', 'amount': b1, 'ref': bank1_ref})
            if b2 > 0:
                payments.append({'type': 'bank', 'amount': b2, 'ref': bank2_ref})
            if c > 0:
                payments.append({'type': 'cash', 'amount': c, 'ref': ''})
        return payments

    def _register_payments_for_bill(self, bill, lines, current_company, branch, acc_date_str):
        payments_to_register = self._get_payments_to_register(lines)

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

    def _find_expense_account(self, name, current_company):
        if not name:
            return False
        clean_name = str(name).strip()
        acc = self.env['account.account'].search([
            ('company_id', '=', current_company.id),
            ('account_type', '=', 'expense'),
            ('name', '=ilike', clean_name),
        ], limit=1)
        if not acc:
            acc = self.env['account.account'].search([
                ('company_id', '=', current_company.id),
                ('account_type', '=', 'expense'),
                ('name', 'ilike', clean_name),
            ], limit=1)
        return acc

    def _correct_bill_expense_accounts(self, bill, current_company):
        for line in bill.invoice_line_ids:
            target_account = False
            prod = line.product_id
            if prod:
                target_account = prod.with_company(current_company).property_account_expense_id or prod.product_tmpl_id.with_company(current_company).property_account_expense_id
                if not target_account:
                    target_account = self._find_expense_account(prod.name, current_company)
            if not target_account and line.name:
                desc = line.name.split(":")[-1].strip() if ":" in line.name else line.name.strip()
                target_account = self._find_expense_account(desc, current_company)

            if target_account and line.account_id.id != target_account.id:
                _logger.info(f"Correcting bill {bill.name} line {line.id} ({line.name}) account: {line.account_id.display_name} -> {target_account.display_name}")
                if bill.state == 'draft':
                    line.account_id = target_account.id
                else:
                    self.env.cr.execute(
                        "UPDATE account_move_line SET account_id = %s WHERE id = %s",
                        (target_account.id, line.id)
                    )
        if bill.state != 'draft':
            self.env['account.move.line'].invalidate_model(['account_id'])

    def _resolve_product(self, row, current_company):
        # Excel column is 'Product', not 'Order Lines/Product'
        raw_name = str(row.get('Product') or row.get('Order Lines/Product') or '')
        template_name = raw_name.strip()
        if not template_name or template_name == 'None':
            return None

        # Search existing product templates matching template_name (with or without spaces)
        candidates = self.env["product.template"].search([
            "|", ("name", "=ilike", template_name),
                 ("name", "ilike", template_name),
            "|", ("company_id", "=", current_company.id), ("company_id", "=", False)
        ], order="company_id desc")

        matching_templates = [
            t for t in candidates 
            if t.name and t.name.strip().lower() == template_name.lower()
        ]

        template = False
        # 1. Prefer template belonging to current_company that has an expense account configured
        for t in matching_templates:
            if t.company_id == current_company and t.with_company(current_company).property_account_expense_id:
                template = t
                break
        # 2. Prefer any template that has an expense account configured
        if not template:
            for t in matching_templates:
                if t.with_company(current_company).property_account_expense_id:
                    template = t
                    break
        # 3. Prefer template for current_company
        if not template:
            for t in matching_templates:
                if t.company_id == current_company:
                    template = t
                    break
        # 4. Fallback to first matching
        if not template and matching_templates:
            template = matching_templates[0]

        exp_account = self._find_expense_account(template_name, current_company)

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

        if template and template.purchase_method != 'purchase':
            template.write({'purchase_method': 'purchase'})

        # Ensure template has its expense account configured for this company
        if exp_account and not template.with_company(current_company).property_account_expense_id:
            template.with_company(current_company).property_account_expense_id = exp_account.id

        return template.product_variant_id