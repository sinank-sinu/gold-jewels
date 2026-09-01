# -*- coding: utf-8 -*-
import base64
import logging
import uuid
import time
from io import BytesIO
import openpyxl
from datetime import datetime, date

from odoo import http, fields, _
from odoo.http import request

_logger = logging.getLogger(__name__)

# Global in-memory storage for chunked import tasks
IMPORT_TASKS = {}

class SchemeSuspenseImportController(http.Controller):

    def _parse_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        
        val_str = str(value).strip()
        for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%Y/%m/%d', '%m-%d-%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(val_str, fmt).date()
            except ValueError:
                continue
        return False

    def _safe_float(self, value):
        if value in (None, False, ''):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        val = str(value).strip()
        if val:
            val = val.strip().replace(',', '')
            try:
                return float(val)
            except ValueError:
                return 0.0
        return 0.0

    def _find_journal(self, env, journal_name):
        if not journal_name:
            return False
        journal_name = str(journal_name).strip()
        
        mapping = {
            'Federal Bank  CA-10640200024918-Scheme': 'Federal Bank  CA-10640200024918-Scheme',
            'Cash-HO main': 'Cash-HO main',
            'Cash - HO': 'Cash-HO main',
        }
        mapped_name = mapping.get(journal_name, journal_name)
        
        journal = env['account.journal'].search([
            ('name', '=', mapped_name),
            ('company_id', '=', env.company.id)
        ], limit=1)
        if journal:
            return journal
            
        journal = env['account.journal'].search([
            ('name', '=', mapped_name)
        ], limit=1)
        if journal:
            return journal
            
        journal = env['account.journal'].search([
            ('name', '=ilike', mapped_name)
        ], limit=1)
        if journal:
            return journal
            
        journal = env['account.journal'].search([
            ('code', '=ilike', mapped_name)
        ], limit=1)
        return journal

    def _check_and_set_partner_properties(self, env, partner, company_id):
        comp_partner = partner.with_company(company_id)
        if not comp_partner.property_account_receivable_id:
            receivable_account = env['account.account'].search([
                ('account_type', '=', 'asset_receivable'),
                ('company_id', '=', company_id)
            ], limit=1)
            if not receivable_account:
                receivable_account = env['account.account'].search([
                    ('account_type', '=', 'asset_receivable')
                ], limit=1)
            if receivable_account:
                comp_partner.write({'property_account_receivable_id': receivable_account.id})
                
        if not comp_partner.property_account_payable_id:
            payable_account = env['account.account'].search([
                ('account_type', '=', 'liability_payable'),
                ('company_id', '=', company_id)
            ], limit=1)
            if not payable_account:
                payable_account = env['account.account'].search([
                    ('account_type', '=', 'liability_payable')
                ], limit=1)
            if payable_account:
                comp_partner.write({'property_account_payable_id': payable_account.id})

    @http.route('/import/customer/payments', type='http', auth='user', methods=['GET'], csrf=False)
    def import_customer_payments_page(self, **kwargs):
        return self._render_upload_form()

    @http.route('/import/customer/payments/start', type='json', auth='user', methods=['POST'], csrf=False)
    def start_import_task(self, **kwargs):
        params = kwargs or getattr(request, 'params', {}) or {}
        file_b64 = params.get('file_data')
        filename = params.get('filename', 'upload.xlsx')

        if not file_b64:
            return {'status': 'error', 'message': 'No file was uploaded. Please select an Excel file.'}

        try:
            file_bytes = base64.b64decode(file_b64)
            workbook = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
            sheet = workbook.active
        except Exception as e:
            return {'status': 'error', 'message': f'Failed to read Excel file: {str(e)}'}

        # Verify Headers (case-insensitive & whitespace tolerant)
        h_map = {
            str(sheet.cell(row=1, column=i).value).strip(): i 
            for i in range(1, sheet.max_column + 1) 
            if sheet.cell(row=1, column=i).value
        }

        def find_header_key(candidates):
            for k in h_map.keys():
                if k.strip().lower() in candidates:
                    return k
            return False

        customer_key = find_header_key(['customer', 'customer name', 'partner'])
        date_key = find_header_key(['payment date', 'date', 'payment_date'])
        amount_key = find_header_key(['amount', 'total amount'])
        journal_key = find_header_key(['scheme line/journal', 'journal', 'scheme journal'])
        txn_key = find_header_key(['scheme line/transaction id', 'transaction id', 'txn id', 'transaction_id', 'ref', 'reference'])

        missing_columns = []
        if not customer_key:
            missing_columns.append("Customer")
        if not date_key:
            missing_columns.append("Payment date / Date")
        if not amount_key:
            missing_columns.append("Amount")
        if not journal_key:
            missing_columns.append("Scheme Line/Journal")
        if not txn_key:
            missing_columns.append("Scheme Line/Transaction ID")

        if missing_columns:
            return {
                'status': 'mismatch',
                'missing_columns': missing_columns,
                'actual_headers': list(h_map.keys())
            }

        rows_data = []
        for row_idx in range(2, sheet.max_row + 1):
            row_values = [sheet.cell(row=row_idx, column=c).value for c in range(1, sheet.max_column + 1)]
            if not any(row_values):
                continue
            
            rows_data.append({
                'row_idx': row_idx,
                'customer': str(sheet.cell(row=row_idx, column=h_map[customer_key]).value or '').strip(),
                'date': sheet.cell(row=row_idx, column=h_map[date_key]).value,
                'amount': sheet.cell(row=row_idx, column=h_map[amount_key]).value,
                'journal': str(sheet.cell(row=row_idx, column=h_map[journal_key]).value or '').strip(),
                'transaction_id': str(sheet.cell(row=row_idx, column=h_map[txn_key]).value or '').strip() if txn_key and h_map.get(txn_key) else '',
            })

        env = request.env

        # Pre-fetch existing transaction IDs from DB into a python set for fast duplication check
        existing_txns = set()
        payments_with_ref = env['account.payment'].search_read(
            [('bank_reference', '!=', False)], ['bank_reference']
        )
        for p in payments_with_ref:
            if p.get('bank_reference'):
                existing_txns.add(str(p['bank_reference']).strip())

        payments_with_ref_field = env['account.payment'].search_read(
            [('ref', '!=', False)], ['ref']
        )
        for p in payments_with_ref_field:
            if p.get('ref'):
                existing_txns.add(str(p['ref']).strip())

        # Pre-lookup suspense partner
        suspense_partner = env['res.partner'].search([('name', '=ilike', 'Suspense')], limit=1)
        if not suspense_partner:
            suspense_partner = env['res.partner'].search([('name', '=ilike', 'Suspence')], limit=1)
        if not suspense_partner:
            suspense_partner = env['res.partner'].create({
                'name': 'Suspense',
                'customer_rank': 1,
            })

        task_id = str(uuid.uuid4())
        IMPORT_TASKS[task_id] = {
            'created_at': time.time(),
            'rows_data': rows_data,
            'total_rows': len(rows_data),
            'processed_index': 0,
            'stats': {
                'parsed': 0,
                'payments_created': 0,
                'payments_skipped': 0,
                'errors_count': 0
            },
            'logs': [],
            'existing_txns': existing_txns,
            'suspense_partner_id': suspense_partner.id,
            'journal_cache': {},
            'partner_cache': {},
            'checked_partner_props': set(),
        }

        return {
            'status': 'ok',
            'task_id': task_id,
            'total_rows': len(rows_data),
            'filename': filename
        }

    @http.route('/import/customer/payments/process_chunk', type='json', auth='user', methods=['POST'], csrf=False)
    def process_chunk(self, **kwargs):
        params = kwargs or getattr(request, 'params', {}) or {}
        task_id = params.get('task_id')
        batch_size = params.get('batch_size', 50)

        task = IMPORT_TASKS.get(task_id)
        if not task:
            return {'status': 'error', 'message': 'Import task expired or not found. Please upload again.'}

        env = request.env
        rows_data = task['rows_data']
        total_rows = task['total_rows']
        start_idx = task['processed_index']
        end_idx = min(start_idx + batch_size, total_rows)

        chunk_rows = rows_data[start_idx:end_idx]
        stats = task['stats']
        existing_txns = task['existing_txns']
        journal_cache = task['journal_cache']
        partner_cache = task['partner_cache']
        checked_partner_props = task['checked_partner_props']
        suspense_partner = env['res.partner'].browse(task['suspense_partner_id'])

        def get_cached_journal(j_name):
            if j_name not in journal_cache:
                j = self._find_journal(env, j_name)
                journal_cache[j_name] = j.id if j else False
            return env['account.journal'].browse(journal_cache[j_name]) if journal_cache[j_name] else False

        def get_cached_partner(p_name):
            if p_name not in partner_cache:
                if not p_name or p_name.lower() in ('suspense', 'suspence'):
                    partner_cache[p_name] = (suspense_partner.id, False)
                else:
                    p = env['res.partner'].search([('name', '=', p_name)], limit=1)
                    if not p:
                        p = env['res.partner'].search([('name', '=ilike', p_name)], limit=1)
                    if not p:
                        partner_cache[p_name] = (suspense_partner.id, True)
                    else:
                        partner_cache[p_name] = (p.id, False)
            pid, is_missing = partner_cache[p_name]
            return env['res.partner'].browse(pid), is_missing

        def ensure_partner_props(partner, comp_id):
            prop_key = (partner.id, comp_id)
            if prop_key not in checked_partner_props:
                self._check_and_set_partner_properties(env, partner, comp_id)
                checked_partner_props.add(prop_key)

        new_logs = []

        for item in chunk_rows:
            row_idx = item['row_idx']
            customer_name = item['customer']
            payment_date_raw = item['date']
            amount_raw = item['amount']
            journal_name = item['journal']
            transaction_id = item['transaction_id']

            stats['parsed'] += 1

            try:
                with env.cr.savepoint():
                    payment_date = self._parse_date(payment_date_raw)
                    amount = self._safe_float(amount_raw)

                    if not journal_name:
                        log_line = f"[WARNING] Row {row_idx}: Missing journal name. Skipping."
                        new_logs.append(log_line)
                        task['logs'].append(log_line)
                        stats['errors_count'] += 1
                        continue

                    if amount <= 0:
                        log_line = f"[WARNING] Row {row_idx}: Invalid amount: {amount_raw}. Skipping."
                        new_logs.append(log_line)
                        task['logs'].append(log_line)
                        stats['errors_count'] += 1
                        continue

                    if not payment_date:
                        log_line = f"[WARNING] Row {row_idx}: Invalid payment date: {payment_date_raw}. Skipping."
                        new_logs.append(log_line)
                        task['logs'].append(log_line)
                        stats['errors_count'] += 1
                        continue

                    journal = get_cached_journal(journal_name)
                    if not journal:
                        log_line = f"[ERROR] Row {row_idx}: Journal '{journal_name}' not found! Skipping."
                        new_logs.append(log_line)
                        task['logs'].append(log_line)
                        stats['errors_count'] += 1
                        continue

                    company_id = journal.company_id.id
                    partner, is_missing = get_cached_partner(customer_name)
                    if is_missing and customer_name:
                        log_line = f"[INFO] Row {row_idx}: Customer '{customer_name}' not found in Odoo! Routing to Suspense partner."
                        new_logs.append(log_line)
                        task['logs'].append(log_line)

                    ensure_partner_props(partner, company_id)

                    # 1. Check if already imported using Transaction ID
                    if transaction_id and transaction_id in existing_txns:
                        stats['payments_skipped'] += 1
                        log_line = f"[INFO] Row {row_idx}: Transaction ID '{transaction_id}' already imported. Skipping."
                        new_logs.append(log_line)
                        task['logs'].append(log_line)
                        continue

                    # 2. Secondary domain duplicate check if transaction ID is missing
                    if not transaction_id:
                        dup_pay_domain = [
                            ('partner_id', '=', partner.id),
                            ('journal_id', '=', journal.id),
                            ('amount', '=', amount),
                            ('date', '=', payment_date),
                        ]
                        existing_payment = env['account.payment'].search(dup_pay_domain, limit=1)
                        if existing_payment:
                            stats['payments_skipped'] += 1
                            log_line = f"[INFO] Row {row_idx}: Payment for '{customer_name}' on {payment_date} of amount {amount} already exists. Skipping."
                            new_logs.append(log_line)
                            task['logs'].append(log_line)
                            continue

                    # Create and post payment
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

                    payment_ctx = {
                        'tracking_disable': True,
                        'mail_create_nolog': True,
                        'mail_notrack': True,
                        'mail_create_nosubscribe': True,
                    }
                    payment = env['account.payment'].with_company(company_id).with_context(**payment_ctx).create(payment_vals)
                    payment.with_context(**payment_ctx).action_post()

                    if transaction_id:
                        existing_txns.add(transaction_id)

                    stats['payments_created'] += 1

            except Exception as row_err:
                log_line = f"[ERROR] Row {row_idx} failed: {str(row_err)}"
                new_logs.append(log_line)
                task['logs'].append(log_line)
                stats['errors_count'] += 1

        task['processed_index'] = end_idx
        env.cr.commit()

        completed = (end_idx >= total_rows)
        progress_pct = 100 if total_rows == 0 else int((end_idx / total_rows) * 100)

        if completed:
            _logger.info(f"Import task {task_id} completed: {stats}")

        return {
            'status': 'ok',
            'task_id': task_id,
            'processed_count': end_idx,
            'total_rows': total_rows,
            'progress_pct': progress_pct,
            'stats': stats,
            'logs': new_logs,
            'completed': completed
        }

    def _render_upload_form(self):
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Import Customer Payments</title>
            <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
            <style>
                * { box-sizing: border-box; margin: 0; padding: 0; }
                body {
                    font-family: 'Inter', sans-serif;
                    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
                    color: #f8fafc;
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 2rem;
                }
                .card {
                    width: 100%;
                    max-width: 750px;
                    background: rgba(30, 41, 59, 0.45);
                    backdrop-filter: blur(20px);
                    -webkit-backdrop-filter: blur(20px);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 24px;
                    padding: 3rem;
                    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
                }
                h1 {
                    font-family: 'Outfit', sans-serif;
                    font-weight: 700;
                    font-size: 2.25rem;
                    text-align: center;
                    margin-bottom: 0.5rem;
                    background: linear-gradient(to right, #a5b4fc, #c084fc);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                }
                .subtitle {
                    text-align: center;
                    color: #94a3b8;
                    font-size: 0.95rem;
                    margin-bottom: 2.5rem;
                }
                .dropzone {
                    position: relative;
                    border: 2px dashed rgba(255, 255, 255, 0.15);
                    border-radius: 16px;
                    padding: 3.5rem 2rem;
                    text-align: center;
                    background: rgba(255, 255, 255, 0.01);
                    transition: all 0.3s ease;
                    cursor: pointer;
                    margin-bottom: 2rem;
                }
                .dropzone:hover {
                    border-color: #818cf8;
                    background: rgba(99, 102, 241, 0.04);
                }
                .dropzone-icon {
                    font-size: 3.5rem;
                    margin-bottom: 1.25rem;
                    color: #818cf8;
                }
                .dropzone-text {
                    font-size: 1.05rem;
                    color: #cbd5e1;
                    margin-bottom: 0.5rem;
                    font-weight: 500;
                }
                .dropzone-subtext {
                    font-size: 0.85rem;
                    color: #64748b;
                }
                .file-input {
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    opacity: 0;
                    cursor: pointer;
                }
                .file-name-display {
                    margin-top: 1rem;
                    font-size: 0.95rem;
                    color: #34d399;
                    font-weight: 500;
                    display: none;
                }
                .btn-submit {
                    display: block;
                    width: 100%;
                    padding: 1.1rem;
                    background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
                    color: white;
                    border: none;
                    border-radius: 12px;
                    font-size: 1.05rem;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.3s ease;
                    box-shadow: 0 10px 20px rgba(99, 102, 241, 0.15);
                    text-align: center;
                }
                .btn-submit:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 12px 25px rgba(99, 102, 241, 0.25);
                }
                .error-box {
                    background: rgba(239, 68, 68, 0.15);
                    border: 1px solid rgba(239, 68, 68, 0.3);
                    color: #f87171;
                    padding: 1rem;
                    border-radius: 12px;
                    margin-bottom: 1.5rem;
                    font-size: 0.95rem;
                    display: none;
                }

                /* Progress Card Styles */
                .badge {
                    display: inline-block;
                    padding: 0.35rem 1rem;
                    border-radius: 20px;
                    font-size: 0.8rem;
                    font-weight: 700;
                    letter-spacing: 0.05em;
                    margin-top: 0.5rem;
                }
                .badge-process {
                    background: rgba(99, 102, 241, 0.15);
                    color: #818cf8;
                    border: 1px solid rgba(99, 102, 241, 0.3);
                }
                .badge-complete {
                    background: rgba(16, 185, 129, 0.15);
                    color: #10b981;
                    border: 1px solid rgba(16, 185, 129, 0.3);
                }
                .progress-container {
                    margin-bottom: 2rem;
                    text-align: center;
                }
                .progress-bar-bg {
                    width: 100%;
                    height: 16px;
                    background: rgba(255, 255, 255, 0.08);
                    border-radius: 10px;
                    overflow: hidden;
                    margin-bottom: 1rem;
                    box-shadow: inset 0 2px 4px rgba(0,0,0,0.3);
                }
                .progress-bar-fill {
                    height: 100%;
                    width: 0%;
                    background: linear-gradient(90deg, #6366f1 0%, #34d399 100%);
                    border-radius: 10px;
                    transition: width 0.3s ease;
                }
                .progress-stats-text {
                    font-family: 'Outfit', sans-serif;
                    font-size: 1.75rem;
                    font-weight: 700;
                    color: #f8fafc;
                    margin-bottom: 0.25rem;
                }
                .progress-subtext {
                    font-size: 0.9rem;
                    color: #94a3b8;
                }
                .stats-grid {
                    display: grid;
                    grid-template-columns: repeat(4, 1fr);
                    gap: 1rem;
                    margin-bottom: 2rem;
                }
                .stat-box {
                    background: rgba(0,0,0,0.2);
                    border: 1px solid rgba(255,255,255,0.05);
                    border-radius: 14px;
                    padding: 1.25rem;
                    text-align: center;
                }
                .stat-val {
                    font-family: 'Outfit', sans-serif;
                    font-size: 1.75rem;
                    font-weight: 700;
                    margin-bottom: 0.25rem;
                }
                .stat-box:nth-child(1) .stat-val { color: #60a5fa; }
                .stat-box:nth-child(2) .stat-val { color: #34d399; }
                .stat-box:nth-child(3) .stat-val { color: #fbbf24; }
                .stat-box:nth-child(4) .stat-val { color: #f87171; }
                .stat-lbl {
                    font-size: 0.75rem;
                    color: #94a3b8;
                    text-transform: uppercase;
                    font-weight: 600;
                    letter-spacing: 0.05em;
                }
                .terminal-win {
                    background: rgba(15, 23, 42, 0.85);
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 14px;
                    overflow: hidden;
                    margin-bottom: 2rem;
                }
                .terminal-bar {
                    background: rgba(30, 41, 59, 0.9);
                    padding: 0.75rem 1rem;
                    display: flex;
                    align-items: center;
                    border-bottom: 1px solid rgba(255,255,255,0.05);
                }
                .dot { width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
                .dot-red { background: #ef4444; }
                .dot-yel { background: #f59e0b; }
                .dot-grn { background: #10b981; }
                .terminal-title {
                    font-size: 0.8rem;
                    color: #94a3b8;
                    font-family: monospace;
                    margin-left: auto;
                }
                .terminal-content {
                    padding: 1.25rem;
                    font-family: monospace;
                    font-size: 0.85rem;
                    max-height: 220px;
                    overflow-y: auto;
                    line-height: 1.6;
                }
                .btn-container {
                    display: flex;
                    gap: 1rem;
                }
                .btn {
                    flex: 1;
                    padding: 1rem;
                    text-align: center;
                    border-radius: 12px;
                    font-weight: 600;
                    text-decoration: none;
                    transition: all 0.3s;
                    cursor: pointer;
                    font-size: 1rem;
                    border: none;
                }
                .btn-primary {
                    background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
                    color: white;
                    box-shadow: 0 5px 15px rgba(99, 102, 241, 0.15);
                }
                .btn-primary:hover {
                    transform: translateY(-1px);
                    box-shadow: 0 8px 20px rgba(99, 102, 241, 0.25);
                }
                .btn-secondary {
                    background: #334155;
                    color: #cbd5e1;
                }
                .btn-secondary:hover {
                    background: #475569;
                    color: white;
                }
            </style>
            <script>
                function handleFileChange(input) {
                    const display = document.getElementById('file-name-display');
                    const uploadText = document.getElementById('upload-prompt');
                    if (input.files && input.files.length > 0) {
                        display.innerText = '✓ Selected: ' + input.files[0].name;
                        display.style.display = 'block';
                        uploadText.style.opacity = '0.3';
                    } else {
                        display.style.display = 'none';
                        uploadText.style.opacity = '1';
                    }
                }

                let currentTaskId = null;
                let isImporting = false;

                async function submitImportForm(event) {
                    event.preventDefault();
                    if (isImporting) return;

                    const fileInput = document.getElementById('excel-file');
                    const errBox = document.getElementById('error-box');
                    errBox.style.display = 'none';

                    if (!fileInput.files || fileInput.files.length === 0) {
                        errBox.innerText = 'Please choose an Excel file to import.';
                        errBox.style.display = 'block';
                        return;
                    }

                    const file = fileInput.files[0];
                    if (!file.name.endsWith('.xlsx')) {
                        errBox.innerText = 'Unsupported file extension. Only Excel (.xlsx) files are supported.';
                        errBox.style.display = 'block';
                        return;
                    }

                    isImporting = true;
                    const reader = new FileReader();
                    reader.onload = async function(e) {
                        const base64Data = e.target.result.split(',')[1];
                        try {
                            const resp = await fetch('/import/customer/payments/start', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    jsonrpc: "2.0",
                                    params: {
                                        file_data: base64Data,
                                        filename: file.name
                                    }
                                })
                            });
                            const json = await resp.json();
                            const res = json.result || {};

                            if (res.status === 'mismatch') {
                                errBox.innerText = 'Column matching failed! Missing columns: ' + res.missing_columns.join(', ');
                                errBox.style.display = 'block';
                                isImporting = false;
                                return;
                            }

                            if (res.status !== 'ok') {
                                errBox.innerText = res.message || 'Failed to initialize import.';
                                errBox.style.display = 'block';
                                isImporting = false;
                                return;
                            }

                            currentTaskId = res.task_id;
                            showProgressUI(res.total_rows);
                            processImportChunks(res.task_id);

                        } catch (err) {
                            errBox.innerText = 'Server error during initialization: ' + err.message;
                            errBox.style.display = 'block';
                            isImporting = false;
                        }
                    };
                    reader.readAsDataURL(file);
                }

                function showProgressUI(totalRows) {
                    document.getElementById('upload-card').style.display = 'none';
                    document.getElementById('progress-card').style.display = 'block';
                    document.getElementById('progress-subtext').innerText = 'Processed 0 / ' + totalRows + ' rows';
                }

                async function processImportChunks(taskId) {
                    let completed = false;
                    const terminal = document.getElementById('terminal-content');
                    terminal.innerHTML = '<div style="color: #60a5fa;">[START] Beginning batch import execution...</div>';

                    while (!completed) {
                        try {
                            const resp = await fetch('/import/customer/payments/process_chunk', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    jsonrpc: "2.0",
                                    params: {
                                        task_id: taskId,
                                        batch_size: 50
                                    }
                                })
                            });
                            const json = await resp.json();
                            const res = json.result || {};

                            if (res.status !== 'ok') {
                                appendLog('[ERROR] ' + (res.message || 'Processing failed.'), '#f87171');
                                break;
                            }

                            // Update 1-100% Progress UI
                            const pct = res.progress_pct || 0;
                            document.getElementById('progress-fill').style.width = pct + '%';
                            document.getElementById('progress-pct-text').innerText = pct + '%';
                            document.getElementById('progress-subtext').innerText = 'Processed ' + res.processed_count + ' / ' + res.total_rows + ' rows';

                            // Update Stat Boxes
                            if (res.stats) {
                                document.getElementById('stat-parsed').innerText = res.stats.parsed || 0;
                                document.getElementById('stat-imported').innerText = res.stats.payments_created || 0;
                                document.getElementById('stat-skipped').innerText = res.stats.payments_skipped || 0;
                                document.getElementById('stat-errors').innerText = res.stats.errors_count || 0;
                            }

                            // Append real-time logs
                            if (res.logs && res.logs.length > 0) {
                                res.logs.forEach(line => {
                                    let color = '#cbd5e1';
                                    if (line.includes('[ERROR]')) color = '#f87171';
                                    else if (line.includes('[WARNING]')) color = '#fbbf24';
                                    else if (line.includes('[INFO]')) color = '#34d399';
                                    appendLog(line, color);
                                });
                            }

                            completed = res.completed;

                        } catch (err) {
                            appendLog('[ERROR] Chunk processing exception: ' + err.message, '#f87171');
                            break;
                        }
                    }

                    // Complete state UI updates
                    isImporting = false;
                    document.getElementById('progress-fill').style.width = '100%';
                    document.getElementById('progress-pct-text').innerText = '100%';
                    document.getElementById('main-title').innerText = 'Import Completed';
                    
                    const badge = document.getElementById('status-badge');
                    badge.className = 'badge badge-complete';
                    badge.innerText = 'LIVE IMPORT SAVED';

                    document.getElementById('action-btns').style.display = 'flex';
                }

                function appendLog(text, color) {
                    const terminal = document.getElementById('terminal-content');
                    const div = document.createElement('div');
                    div.style.color = color;
                    div.style.marginBottom = '0.25rem';
                    div.innerText = text;
                    terminal.appendChild(div);
                    terminal.scrollTop = terminal.scrollHeight;
                }
            </script>
        </head>
        <body>
            <!-- Upload Form Card -->
            <div id="upload-card" class="card">
                <h1>Import Customer Payments</h1>
                <p class="subtitle">Upload Excel file to register Customer Payments directly</p>
                <div id="error-box" class="error-box"></div>
                <form onsubmit="submitImportForm(event)">
                    <div class="dropzone">
                        <div id="upload-prompt">
                            <div class="dropzone-icon">⎋</div>
                            <div class="dropzone-text">Choose file or drag it here</div>
                            <div class="dropzone-subtext">Supports Microsoft Excel (.xlsx) files</div>
                        </div>
                        <input type="file" id="excel-file" class="file-input" accept=".xlsx" onchange="handleFileChange(this)" required/>
                        <div id="file-name-display" class="file-name-display"></div>
                    </div>
                    <button type="submit" class="btn-submit">Start Import</button>
                </form>
            </div>

            <!-- Progress Loading & Results Card -->
            <div id="progress-card" class="card" style="display: none;">
                <div style="text-align: center; margin-bottom: 2rem;">
                    <h1 id="main-title">Importing Customer Payments...</h1>
                    <span id="status-badge" class="badge badge-process">LIVE IMPORT IN PROGRESS</span>
                </div>

                <div class="progress-container">
                    <div id="progress-pct-text" class="progress-stats-text">0%</div>
                    <div class="progress-bar-bg">
                        <div id="progress-fill" class="progress-bar-fill"></div>
                    </div>
                    <div id="progress-subtext" class="progress-subtext">Preparing data...</div>
                </div>

                <div class="stats-grid">
                    <div class="stat-box">
                        <div id="stat-parsed" class="stat-val">0</div>
                        <div class="stat-lbl">Parsed</div>
                    </div>
                    <div class="stat-box">
                        <div id="stat-imported" class="stat-val">0</div>
                        <div class="stat-lbl">Imported</div>
                    </div>
                    <div class="stat-box">
                        <div id="stat-skipped" class="stat-val">0</div>
                        <div class="stat-lbl">Skipped</div>
                    </div>
                    <div class="stat-box">
                        <div id="stat-errors" class="stat-val">0</div>
                        <div class="stat-lbl">Errors</div>
                    </div>
                </div>

                <div class="terminal-win">
                    <div class="terminal-bar">
                        <div class="dot dot-red"></div>
                        <div class="dot dot-yel"></div>
                        <div class="dot dot-grn"></div>
                        <div class="terminal-title">import_live_logs.txt</div>
                    </div>
                    <div id="terminal-content" class="terminal-content">
                        <!-- Real-time logs streamed here -->
                    </div>
                </div>

                <div id="action-btns" class="btn-container" style="display: none;">
                    <a href="/import/customer/payments" class="btn btn-primary">Import Another File</a>
                    <a href="/web" class="btn btn-secondary">Return to Odoo</a>
                </div>
            </div>
        </body>
        </html>
        """
        return request.make_response(html, headers=[('Content-Type', 'text/html')])
