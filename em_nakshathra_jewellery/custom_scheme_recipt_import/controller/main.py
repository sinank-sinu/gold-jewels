import openpyxl
import logging
import os
import threading
import odoo
from datetime import datetime, date, timedelta
from odoo import http, fields
from odoo.http import request
from odoo.modules.module import get_module_resource

_logger = logging.getLogger(__name__)


def parse_date(value):
    if not value:
        return False
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = str(value).strip()
    
    # Try parsing Excel serial dates (e.g., 45312)
    try:
        serial = float(value)
        if 30000 < serial < 60000:
            return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    except ValueError:
        pass

    # Extended formats to handle timestamps and 2-digit years
    formats = (
        '%m/%d/%Y', '%m-%d-%Y', '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%Y/%m/%d',
        '%m/%d/%y', '%m-%d-%y', '%d/%m/%y', '%d-%m-%y', '%y-%m-%d', '%y/%m/%d',
        '%Y-%m-%d %H:%M:%S', '%m/%d/%Y %H:%M:%S', '%d/%m/%Y %H:%M:%S'
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
            
    _logger.warning("parse_date could not parse: '%s'", value)
    return False

def safe_float(value):
    try:
        return float(value) if value not in (None, False, '') else 0.0
    except (TypeError, ValueError):
        return 0.0

def _find_or_create_partner(env, name, phone):
    if not name:
        return False
    partner = env['res.partner'].search([('name', '=', name)], limit=1)
    if not partner:
        partner = env['res.partner'].create({
            'name': name,
            'phone': str(phone) if phone else False,
            'customer_rank': 1,
        })
    return partner

def run_import_in_background(db_name, uid, file_path):
    """ Runs the heavy import in a background thread to prevent Odoo web timeouts. """
    _logger.info("Starting background import thread for %s", file_path)
    
    registry = odoo.registry(db_name)
    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
        
        try:
                workbook = openpyxl.load_workbook(file_path, data_only=True)
                sheet = workbook.active

                h_map = {str(sheet.cell(row=1, column=i).value).strip(): i
                         for i in range(1, sheet.max_column + 1)
                         if sheet.cell(row=1, column=i).value}

                last_valid_ticket = False
                scheme_tracker = {}
                count_scheme = 0
                count_lines = 0
                _account_cache = {}
                
                # Initialize Progress Tracking
                env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', '0')
                env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_total', str(sheet.max_row))

                for row_idx in range(2, sheet.max_row + 1):
                    # Periodically update progress
                    if row_idx % 100 == 0:
                        env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', str(row_idx))
                        
                    # Periodically commit and clear cache to free memory!
                    if row_idx % 500 == 0:
                        env.cr.commit()
                        env.clear()
                        _logger.info("Committed up to row %s. Memory cleared.", row_idx)

                    def get_v(col_name, _row=row_idx):
                        idx = h_map.get(col_name)
                        return sheet.cell(row=_row, column=idx).value if idx else False

                    try:
                        with env.cr.savepoint():
                            current_ticket_raw = get_v('Ticket Number')
                            if current_ticket_raw:
                                last_valid_ticket = str(current_ticket_raw).strip().upper()

                            if not last_valid_ticket:
                                continue

                            # 1. Enrollment Logic
                            scheme_id = scheme_tracker.get(last_valid_ticket)
                            if not scheme_id:
                                existing_scheme = env['jewellery.scheme.enrollment'].search([
                                    ('ticket_number', '=', last_valid_ticket)
                                ], limit=1)

                                if existing_scheme:
                                    scheme_id = existing_scheme.id
                                else:
                                    partner_name = str(get_v('Partner') or get_v('Customer')).strip() if (get_v('Partner') or get_v('Customer')) else False
                                    if partner_name:
                                        partner = _find_or_create_partner(env, partner_name, get_v('Phone'))
                                        if not partner:
                                            raise ValueError(f"Could not find/create partner '{partner_name}'")

                                        active_raw = get_v('Active')
                                        is_active = str(active_raw).lower() in ['true', '1', 'yes'] if active_raw else False

                                        journal_name = get_v('Scheme Line/Journal')
                                        journal = False
                                        if journal_name:
                                            journal_name = str(journal_name).strip().replace('Vyttila', 'Vytila')
                                            journal = env['account.journal'].search([('name', '=', journal_name)], limit=1)

                                        scheme_vals = {
                                            'name': get_v('Name'),
                                            'ticket_number': last_valid_ticket,
                                            'partner_id': partner.id,
                                            'phone': get_v('Phone'),
                                            'whatsapp_number': get_v('Whatsapp Number'),
                                            'address': get_v('Address'),
                                            'duration': get_v('Duration'),
                                            'installment_amount': safe_float(get_v('Installment Amount')),
                                            'total_paid': safe_float(get_v('Total Paid')),
                                            'balance_amount': safe_float(get_v('Balance Amount')),
                                            'state': str(get_v('State')).lower() if get_v('State') else 'draft',
                                            'active': is_active,
                                            'nominee': get_v('Nominee'),
                                        }
                                        if journal and hasattr(journal, 'branch_id') and journal.branch_id:
                                            scheme_vals['branch_id'] = journal.branch_id.id
                                            
                                        scheme_id = env['jewellery.scheme.enrollment'].create(scheme_vals).id
                                        count_scheme += 1

                                if scheme_id:
                                    scheme_tracker[last_valid_ticket] = scheme_id

                            # 2. Installment + Journal Entry Logic
                            line_date_raw = get_v('Scheme Line/Date') or get_v('Date') or get_v('Payment date') or get_v('Payment Date')
                            line_amount   = get_v('Scheme Line/Amount') or get_v('Amount') or get_v('Installment Amount')
                            line_date     = parse_date(line_date_raw)
                            line_amount_f = safe_float(line_amount)

                            if not scheme_id or not (line_date or line_amount_f):
                                if row_idx < 5:
                                    _logger.warning("Row %s silently skipped! scheme_id: %s, date: %s, amount: %s", row_idx, scheme_id, line_date, line_amount_f)
                                continue

                            # Duplicate protection
                            t_id = get_v('Scheme Line/Transaction ID')
                            dup_domain = [
                                ('enrollment_id', '=', scheme_id),
                                ('date', '=', line_date),
                                ('amount', '=', line_amount_f)
                            ]
                            if t_id:
                                dup_domain.append(('transaction_id', '=', str(t_id)))
                            
                            existing_installment = env['jewellery.scheme.installment'].search(dup_domain, limit=1)
                            if existing_installment:
                                continue

                            journal_name = get_v('Scheme Line/Journal')
                            journal = False
                            if journal_name:
                                journal_name = str(journal_name).strip().replace('Vyttila', 'Vytila')
                                journal = env['account.journal'].search([('name', '=', journal_name)], limit=1)
                                
                            excel_move_name = get_v('Scheme Line/Move')
                            excel_move_id = False
                            if excel_move_name:
                                excel_move_id = env['account.move'].search([('name', '=', str(excel_move_name).strip())], limit=1)
                                
                            generated_move_id = False

                            if not excel_move_id and journal and line_amount_f:
                                if journal.id not in _account_cache:
                                    ob_acc = journal.default_account_id
                                    if not ob_acc:
                                        ob_acc = env['account.account'].search([
                                            ('company_id', '=', journal.company_id.id),
                                            '|',
                                            ('name', 'ilike', 'opening balance'),
                                            ('account_type', '=', 'current_assets'),
                                        ], limit=1)
                                    dr_acc = env['account.account'].search([
                                        ('company_id', '=', journal.company_id.id),
                                        '|',
                                        ('name', 'ilike', 'debtor'),
                                        ('account_type', '=', 'asset_receivable'),
                                    ], limit=1)
                                    _account_cache[journal.id] = (ob_acc, dr_acc)

                                opening_balance_account, debtors_account = _account_cache[journal.id]

                                if opening_balance_account and debtors_account:
                                    scheme_record = env['jewellery.scheme.enrollment'].browse(scheme_id)
                                    line_partner_id = scheme_record.partner_id.id if scheme_record else False

                                    move_vals = {
                                        'journal_id': journal.id,
                                        'date': line_date or fields.Date.today(),
                                        'ref': f"Scheme Payment: {last_valid_ticket}",
                                        'move_type': 'entry',
                                        'company_id': journal.company_id.id,
                                    }
                                    if hasattr(journal, 'branch_id') and journal.branch_id:
                                        move_vals['branch_id'] = journal.branch_id.id
                                        
                                    move_vals['line_ids'] = [
                                            (0, 0, {
                                                'name': f'Scheme Liability (Opening) - {last_valid_ticket}',
                                                'account_id': opening_balance_account.id,
                                                'debit': line_amount_f,
                                                'credit': 0.0,
                                                'partner_id': line_partner_id,
                                            }),
                                            (0, 0, {
                                                'name': f'Scheme Payment - {last_valid_ticket}',
                                                'account_id': debtors_account.id,
                                                'debit': 0.0,
                                                'credit': line_amount_f,
                                                'partner_id': line_partner_id,
                                            }),
                                        ]
                                    new_move = env['account.move'].create(move_vals)
                                    new_move.action_post()
                                    generated_move_id = new_move.id
                                    _logger.info("Row %s: Journal entry created (id=%s) ticket=%s amount=%.2f", row_idx, generated_move_id, last_valid_ticket, line_amount_f)

                            env['jewellery.scheme.installment'].create({
                                'enrollment_id':  scheme_id,
                                'date':           line_date or fields.Date.today(),
                                'amount':         line_amount_f,
                                'journal_id':     journal.id if journal else False,
                                'state':          str(get_v('Scheme Line/State')).lower() if get_v('Scheme Line/State') else 'paid',
                                'move_id':        excel_move_id.id if excel_move_id else generated_move_id,
                                'transaction_id': get_v('Scheme Line/Transaction ID'),
                            })
                            count_lines += 1

                    except Exception as row_err:
                        _logger.error("Row %s skipped - %s", row_idx, str(row_err))
                        continue

                env.cr.commit()
                env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', 'DONE')
                _logger.info("Background Import Complete. Enrollments: %s, Installments: %s", count_scheme, count_lines)

        except Exception as e:
            env.cr.rollback()
            env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', 'ERROR: ' + str(e))
            _logger.error("Background Import Failure: %s", str(e))


class SchemeImportController(http.Controller):

    @http.route('/import/schemes/now', type='http', auth='user')
    def trigger_scheme_import(self, **kwargs):
        file_name = 'scheme_payment 01.04.2026.xlsx'
        file_path = get_module_resource('custom_scheme_recipt_import', 'data', file_name)

        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"

        db_name = request.env.cr.dbname
        uid = request.env.uid

        # Launch background thread
        thread = threading.Thread(target=run_import_in_background, args=(db_name, uid, file_path))
        thread.start()

        html_content = """
            <html>
            <head>
                <style>
                    body { font-family: 'Inter', Arial, sans-serif; text-align: center; margin-top: 50px; background: #f0f2f5; color: #333; }
                    h1 { color: #2c3e50; font-weight: 600; }
                    .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
                    .msg { font-size: 16px; color: #666; margin-bottom: 20px; }
                    .progress-wrapper { width: 100%; background-color: #e9ecef; border-radius: 20px; overflow: hidden; margin: 30px 0; height: 30px; position: relative; }
                    .progress-bar { height: 100%; background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%); width: 0%; transition: width 0.5s ease-in-out; }
                    .progress-text { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #fff; font-weight: bold; font-size: 14px; text-shadow: 1px 1px 2px rgba(0,0,0,0.2); }
                    .status { font-size: 18px; font-weight: bold; color: #007bff; margin-top: 10px; }
                    .success-msg { display: none; color: #28a745; font-size: 20px; font-weight: bold; margin-top: 20px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Importing Scheme Receipts</h1>
                    <p class="msg">The 16,000+ rows are being processed in the background.</p>
                    
                    <div class="progress-wrapper">
                        <div class="progress-bar" id="progressBar"></div>
                        <div class="progress-text" id="progressText">0%</div>
                    </div>
                    
                    <div class="status" id="statusText">Initializing...</div>
                    <div class="success-msg" id="successMsg">🎉 Import Completed Successfully!</div>
                </div>

                <script>
                    function fetchProgress() {
                        fetch('/import/schemes/progress')
                            .then(response => response.json())
                            .then(data => {
                                if (data.progress === 'DONE') {
                                    document.getElementById('progressBar').style.width = '100%';
                                    document.getElementById('progressText').innerText = '100%';
                                    document.getElementById('statusText').innerText = 'Finished';
                                    document.getElementById('successMsg').style.display = 'block';
                                } else if (data.progress.startsWith('ERROR')) {
                                    document.getElementById('statusText').innerText = data.progress;
                                    document.getElementById('statusText').style.color = '#dc3545';
                                    document.getElementById('progressBar').style.background = '#dc3545';
                                } else {
                                    let current = parseInt(data.progress) || 0;
                                    let total = parseInt(data.total) || 1;
                                    let percent = Math.min(100, Math.round((current / total) * 100));
                                    
                                    document.getElementById('progressBar').style.width = percent + '%';
                                    document.getElementById('progressText').innerText = percent + '%';
                                    document.getElementById('statusText').innerText = 'Processing row ' + current + ' of ' + total;
                                    
                                    // Poll again in 2 seconds
                                    setTimeout(fetchProgress, 2000);
                                }
                            })
                            .catch(err => {
                                console.error('Error fetching progress:', err);
                                setTimeout(fetchProgress, 3000);
                            });
                    }
                    // Start polling
                    setTimeout(fetchProgress, 1000);
                </script>
            </body>
            </html>
        """
        return request.make_response(html_content, headers=[('Content-Type', 'text/html')])

    @http.route('/import/schemes/progress', type='http', auth='public')
    def check_import_progress(self, **kwargs):
        progress = request.env['ir.config_parameter'].sudo().get_param('scheme_receipt_import_progress', '0')
        total = request.env['ir.config_parameter'].sudo().get_param('scheme_receipt_import_total', '1')
        
        # Escape any potential quotes in error messages
        progress = progress.replace('"', '\\"')
        
        return request.make_response(f'{{"progress": "{progress}", "total": "{total}"}}', headers=[('Content-Type', 'application/json')])
