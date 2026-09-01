# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import base64
from io import BytesIO
import logging
from datetime import datetime, date
import openpyxl

_logger = logging.getLogger(__name__)

class SchemeSuspenseImportWizard(models.TransientModel):
    _name = "scheme.suspense.import.wizard"
    _description = "Customer Suspense Payments Import Wizard"

    file = fields.Binary(string="Excel File", required=True)
    filename = fields.Char(string="Filename")
    
    dry_run = fields.Boolean(
        string="Dry Run", 
        default=True, 
        help="If checked, no database changes will be saved. Recommended to run first to verify data."
    )
    
    result_message = fields.Text(string="Import Result Summary", readonly=True)

    def _parse_date(self, val):
        if isinstance(val, (date, datetime)):
            return val.date() if isinstance(val, datetime) else val
        if isinstance(val, str):
            val = val.strip()
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y'):
                try:
                    return datetime.strptime(val, fmt).date()
                except ValueError:
                    continue
        return False

    def _safe_float(self, val):
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            val = val.strip().replace(',', '')
            try:
                return float(val)
            except ValueError:
                return 0.0
        return 0.0

    def _check_and_set_partner_properties(self, partner, company_id):
        comp_partner = partner.with_company(company_id)
        if not comp_partner.property_account_receivable_id:
            receivable_account = self.env['account.account'].search([
                ('account_type', '=', 'asset_receivable'),
                ('company_id', '=', company_id)
            ], limit=1)
            if receivable_account:
                comp_partner.write({'property_account_receivable_id': receivable_account.id})
                
        if not comp_partner.property_account_payable_id:
            payable_account = self.env['account.account'].search([
                ('account_type', '=', 'liability_payable'),
                ('company_id', '=', company_id)
            ], limit=1)
            if payable_account:
                comp_partner.write({'property_account_payable_id': payable_account.id})

    def _find_journal(self, journal_name):
        if not journal_name:
            return False
        journal_name = str(journal_name).strip()
        
        # Mapping journal name variants to actual names
        mapping = {
            'Federal Bank  CA-10640200024918-Scheme': 'Federal Bank  CA-10640200024918-Scheme',
            'Cash-HO main': 'Cash-HO main',
            'Cash - HO': 'Cash-HO main',
        }
        mapped_name = mapping.get(journal_name, journal_name)
        
        # 1. Search in current company first
        journal = self.env['account.journal'].search([
            ('name', '=', mapped_name),
            ('company_id', '=', self.env.company.id)
        ], limit=1)
        if journal:
            return journal
            
        # 2. Search in any company
        journal = self.env['account.journal'].search([
            ('name', '=', mapped_name)
        ], limit=1)
        if journal:
            return journal
            
        # 3. Search case-insensitive
        journal = self.env['account.journal'].search([
            ('name', '=ilike', mapped_name)
        ], limit=1)
        if journal:
            return journal
            
        # 4. Search by code
        journal = self.env['account.journal'].search([
            ('code', '=ilike', mapped_name)
        ], limit=1)
        return journal

    def action_import(self):
        self.ensure_one()
        
        if not self.file:
            raise ValidationError(_("Please upload an Excel file."))
            
        try:
            workbook = openpyxl.load_workbook(
                filename=BytesIO(base64.b64decode(self.file)),
                data_only=True
            )
        except Exception as e:
            raise ValidationError(_("Invalid Excel file: %s") % str(e))
            
        sheet = workbook.active
        
        # Map headers
        h_map = {
            str(sheet.cell(row=1, column=i).value).strip(): i 
            for i in range(1, sheet.max_column + 1) 
            if sheet.cell(row=1, column=i).value
        }
        
        # Resolve spreadsheet headers
        customer_key = next((k for k in h_map.keys() if k.strip() == 'Customer'), False)
        date_key = next((k for k in h_map.keys() if k.strip() in ('Payment date', 'Date')), False)
        amount_key = next((k for k in h_map.keys() if k.strip() == 'Amount'), False)
        journal_key = next((k for k in h_map.keys() if k.strip() == 'Scheme Line/Journal'), False)
        txn_key = next((k for k in h_map.keys() if k.strip() == 'Scheme Line/Transaction ID'), False)
        
        if not amount_key:
            raise ValidationError(_("Missing required column: 'Amount'"))
        if not journal_key:
            raise ValidationError(_("Missing required column: 'Scheme Line/Journal'"))

        stats = {
            'parsed': 0,
            'payments_created': 0,
            'payments_skipped': 0,
            'errors_count': 0
        }
        
        logs = []
        
        # Pre-lookup/create Suspense partner (trying both spellings Suspense and Suspence)
        suspense_partner = self.env['res.partner'].search([('name', '=ilike', 'Suspense')], limit=1)
        if not suspense_partner:
            suspense_partner = self.env['res.partner'].search([('name', '=ilike', 'Suspence')], limit=1)
        if not suspense_partner:
            suspense_partner = self.env['res.partner'].create({
                'name': 'Suspense',
                'customer_rank': 1,
            })
            logs.append("Created new 'Suspense' partner in Odoo.")

        for row_idx in range(2, sheet.max_row + 1):
            def get_v(col_name):
                idx = h_map.get(col_name)
                return sheet.cell(row=row_idx, column=idx).value if idx else None

            # Skip empty rows
            row_values = [sheet.cell(row=row_idx, column=c).value for c in range(1, sheet.max_column + 1)]
            if not any(row_values):
                continue
                
            stats['parsed'] += 1
            
            try:
                with self.env.cr.savepoint():
                    customer_raw = get_v(customer_key) if customer_key else None
                    customer_name = str(customer_raw).strip() if customer_raw else ''
                    
                    payment_date_raw = get_v(date_key) if date_key else None
                    payment_date = self._parse_date(payment_date_raw)
                    
                    amount = self._safe_float(get_v(amount_key))
                    
                    journal_name = get_v(journal_key)
                    journal_name = str(journal_name).strip() if journal_name else ''
                    
                    transaction_id = get_v(txn_key) if txn_key else None
                    transaction_id = str(transaction_id).strip() if transaction_id else ''

                    if not journal_name:
                        logs.append(f"Row {row_idx}: Missing journal name. Skipping.")
                        stats['errors_count'] += 1
                        continue
                        
                    if amount <= 0:
                        logs.append(f"Row {row_idx}: Invalid amount: {amount}. Skipping.")
                        stats['errors_count'] += 1
                        continue
                        
                    if not payment_date:
                        logs.append(f"Row {row_idx}: Invalid payment date: {payment_date_raw}. Skipping.")
                        stats['errors_count'] += 1
                        continue

                    # Find Journal
                    journal = self._find_journal(journal_name)
                    if not journal:
                        logs.append(f"Row {row_idx}: Journal '{journal_name}' not found! Skipping.")
                        stats['errors_count'] += 1
                        continue

                    company_id = journal.company_id.id
                    
                    # Resolve Partner (keep is_suspense_payment toggle off)
                    partner = False
                    
                    if not customer_name or customer_name.lower() in ('suspense', 'suspence'):
                        partner = suspense_partner
                    else:
                        # Search partner by name
                        partner = self.env['res.partner'].search([('name', '=', customer_name)], limit=1)
                        if not partner:
                            # Search partner case-insensitive
                            partner = self.env['res.partner'].search([('name', '=ilike', customer_name)], limit=1)
                            
                        if not partner:
                            logs.append(f"Row {row_idx}: Customer '{customer_name}' not found in Odoo! Routing to Suspense partner.")
                            partner = suspense_partner

                    # Set receivable/payable properties if missing to prevent chart of accounts crashes
                    self._check_and_set_partner_properties(partner, company_id)

                    # Duplicate check for Payment
                    dup_pay_domain = [
                        ('partner_id', '=', partner.id),
                        ('journal_id', '=', journal.id),
                        ('amount', '=', amount),
                        ('date', '=', payment_date),
                    ]
                    if transaction_id:
                        dup_pay_domain.append(('bank_reference', '=', transaction_id))
                    
                    existing_payment = self.env['account.payment'].search(dup_pay_domain, limit=1)
                    if not existing_payment and transaction_id:
                        existing_payment = self.env['account.payment'].search([
                            ('journal_id', '=', journal.id),
                            ('bank_reference', '=', transaction_id)
                        ], limit=1)
                        if not existing_payment:
                            existing_payment = self.env['account.payment'].search([
                                ('journal_id', '=', journal.id),
                                ('ref', '=', transaction_id)
                            ], limit=1)
                        
                    if existing_payment:
                        stats['payments_skipped'] += 1
                    else:
                        # Create the Payment record
                        pml = journal.inbound_payment_method_line_ids[:1]
                        payment_vals = {
                            'payment_type': 'inbound',
                            'partner_type': 'customer',
                            'partner_id': partner.id,
                            'journal_id': journal.id,
                            'amount': amount,
                            'date': payment_date,
                            'ref': transaction_id or f"Imported Payment - {customer_name}",
                            'bank_reference': transaction_id,
                            'is_suspense_payment': False,
                            'company_id': company_id,
                        }
                        if pml:
                            payment_vals['payment_method_line_id'] = pml.id
                            
                        payment = self.env['account.payment'].with_company(company_id).create(payment_vals)
                        payment.action_post()
                        stats['payments_created'] += 1

            except Exception as row_err:
                logs.append(f"Row {row_idx} failed with error: {str(row_err)}")
                stats['errors_count'] += 1

        # Summary Message compilation
        summary = []
        if self.dry_run:
            summary.append("=== DRY RUN SUMMARY ===")
            summary.append("No changes have been saved to the database.\n")
        else:
            summary.append("=== IMPORT SUMMARY ===")
            summary.append("All parsed records have been successfully saved.\n")
            
        summary.append(f"Rows Parsed: {stats['parsed']}")
        summary.append(f"Payments Created & Posted: {stats['payments_created']}")
        summary.append(f"Payments Skipped (Duplicates): {stats['payments_skipped']}")
        summary.append(f"Errors Encountered: {stats['errors_count']}\n")
        
        if logs:
            summary.append("=== Detailed Logs / Errors ===")
            summary.extend(logs[:50]) # Limit to first 50 logs/errors to avoid rendering huge string
            if len(logs) > 50:
                summary.append(f"... and {len(logs) - 50} more log lines.")
                
        summary_message = "\n".join(summary)
        
        if self.dry_run:
            self.env.cr.rollback()
            self.env.clear()
            self.env.registry.clear_caches()
            _logger.info("Dry run completed. Rolled back all changes.")
        else:
            self.env.clear()
            self.env.registry.clear_caches()
            _logger.info("Import completed. Committing changes.")
            
        # Re-open the wizard view to show the result summary message
        return {
            'name': _('Import Result'),
            'type': 'ir.actions.act_window',
            'res_model': 'scheme.suspense.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_result_message': summary_message,
                'default_file': False,
            }
        }
