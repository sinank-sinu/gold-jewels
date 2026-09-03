import openpyxl
import logging
import os
import threading
import shutil
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

def _find_journal(env, journal_name):
    if not journal_name:
        journal_name = 'Vyttila'
    raw_name = str(journal_name).strip()
    # 1. Exact match with raw name
    journal = env['account.journal'].search([('name', '=', raw_name)], limit=1)
    if journal:
        return journal
    # 2. Swap Vyttila <-> Vytila
    alt_name = raw_name.replace('Vyttila', 'Vytila') if 'Vyttila' in raw_name else raw_name.replace('Vytila', 'Vyttila')
    journal = env['account.journal'].search([('name', '=', alt_name)], limit=1)
    if journal:
        return journal
    # 3. Case-insensitive search fallback
    journal = env['account.journal'].search([('name', 'ilike', raw_name)], limit=1)
    if journal:
        return journal
    journal = env['account.journal'].search([('name', 'ilike', alt_name)], limit=1)
    if journal:
        return journal
    return env['account.journal'].search([
        '|', '|',
        ('name', 'ilike', '50200117325578'),
        ('name', 'ilike', 'Vyttila'),
        ('name', 'ilike', 'Vytila')
    ], limit=1)



def run_import_in_background(db_name, uid, file_path):
    """ Runs the heavy import in a background thread to prevent Odoo web timeouts. """
    _logger.info("Starting background import thread for %s", file_path)
    
    registry = odoo.registry(db_name)
    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
        
        try:
                workbook = openpyxl.load_workbook(file_path, data_only=True)
                sheet = workbook.active

                h_map = {str(sheet.cell(row=1, column=i).value).strip().lower(): i
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
                        idx = h_map.get(str(col_name).strip().lower())
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
                                        journal = _find_journal(env, journal_name)

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
                                journal_name = get_v('Scheme Line/Journal')
                                journal = _find_journal(env, journal_name)
                                upd_vals = {}
                                if journal and (not existing_installment.journal_id or existing_installment.journal_id.id != journal.id):
                                    upd_vals['journal_id'] = journal.id
                                    
                                if not existing_installment.move_id and journal and line_amount_f:
                                    if journal.id not in _account_cache:
                                        ob_acc = env['account.account'].search([
                                            ('company_id', '=', journal.company_id.id),
                                            ('name', 'ilike', 'Outstanding Rec')
                                        ], limit=1)
                                        if not ob_acc:
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
                                            ('name', 'ilike', 'Debtor')
                                        ], limit=1)
                                        if not dr_acc:
                                            dr_acc = env['account.account'].search([
                                                ('company_id', '=', journal.company_id.id),
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
                                        upd_vals['move_id'] = new_move.id

                                if upd_vals:
                                    existing_installment.write(upd_vals)
                                    count_lines += 1
                                continue


                            journal_name = get_v('Scheme Line/Journal')
                            journal = _find_journal(env, journal_name)
                                
                            excel_move_name = get_v('Scheme Line/Move')
                            excel_move_id = False
                            if excel_move_name:
                                excel_move_id = env['account.move'].search([('name', '=', str(excel_move_name).strip())], limit=1)
                                
                            generated_move_id = False

                            if not excel_move_id and journal and line_amount_f:
                                if journal.id not in _account_cache:
                                    ob_acc = env['account.account'].search([
                                        ('company_id', '=', journal.company_id.id),
                                        ('name', 'ilike', 'Outstanding Rec')
                                    ], limit=1)
                                    if not ob_acc:
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
                                        ('name', 'ilike', 'Debtor')
                                    ], limit=1)
                                    if not dr_acc:
                                        dr_acc = env['account.account'].search([
                                            ('company_id', '=', journal.company_id.id),
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

    @http.route('/import/schemes/upload', type='http', auth='user', methods=['GET', 'POST'], csrf=False)
    def upload_scheme_file(self, **kwargs):
        if request.httprequest.method == 'POST':
            try:
                file = request.httprequest.files.get('file') or kwargs.get('file')
                if not file or not getattr(file, 'filename', None):
                    return "<h1>Error</h1><p>No file uploaded. Please select a valid .xlsx file.</p>"
                
                upload_dir = '/home/akhil/odoo/uploaded_imports'
                os.makedirs(upload_dir, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                file_name = getattr(file, 'filename', 'uploaded_file.xlsx')
                file_path = os.path.join(upload_dir, f"{timestamp}_{file_name}")
                
                with open(file_path, 'wb') as f:
                    if hasattr(file, 'stream'):
                        file.stream.seek(0)
                        shutil.copyfileobj(file.stream, f)
                    elif hasattr(file, 'read'):
                        f.write(file.read())
                    else:
                        f.write(file)
                
                db_name = request.env.cr.dbname if (request.env and request.env.cr) else request.db
                uid = request.env.uid if request.env else odoo.SUPERUSER_ID

                thread = threading.Thread(target=run_import_in_background, args=(db_name, uid, file_path))
                thread.start()

                return request.redirect('/import/schemes/now?uploaded=1')
            except Exception as e:
                _logger.error("Upload error: %s", str(e), exc_info=True)
                return f"<h1>Upload Error</h1><p>{str(e)}</p>"

        # GET Request - File Upload Page
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Scheme Receipt Bulk Import</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                :root {
                    --primary: #4f46e5;
                    --primary-hover: #4338ca;
                    --bg: #f8fafc;
                    --card-bg: #ffffff;
                    --text: #1e293b;
                    --subtext: #64748b;
                    --border: #e2e8f0;
                }
                body {
                    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
                    background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0;
                    padding: 20px;
                }
                .upload-card {
                    background: var(--card-bg);
                    width: 100%;
                    max-width: 580px;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
                    text-align: center;
                }
                .icon-circle {
                    width: 70px;
                    height: 70px;
                    background: #e0e7ff;
                    color: var(--primary);
                    border-radius: 50%;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 32px;
                    margin-bottom: 20px;
                }
                h1 { font-size: 24px; font-weight: 700; color: var(--text); margin: 0 0 10px 0; }
                p.desc { font-size: 14px; color: var(--subtext); margin-bottom: 30px; line-height: 1.5; }
                
                .drop-zone {
                    border: 2px dashed #a5b4fc;
                    border-radius: 14px;
                    padding: 35px 20px;
                    background: #f8fafc;
                    cursor: pointer;
                    transition: all 0.2s ease-in-out;
                    margin-bottom: 25px;
                }
                .drop-zone:hover, .drop-zone.dragover {
                    border-color: var(--primary);
                    background: #eef2ff;
                }
                .drop-zone-text { font-size: 15px; color: var(--text); font-weight: 600; margin-bottom: 6px; }
                .drop-zone-sub { font-size: 12px; color: var(--subtext); }
                input[type="file"] { display: none; }
                
                .file-info {
                    display: none;
                    margin-top: 15px;
                    padding: 10px 15px;
                    background: #e0e7ff;
                    border-radius: 8px;
                    color: var(--primary);
                    font-weight: 600;
                    font-size: 14px;
                }

                .btn-submit {
                    width: 100%;
                    padding: 14px;
                    background: var(--primary);
                    color: white;
                    border: none;
                    border-radius: 10px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: background 0.2s;
                    box-shadow: 0 4px 6px -1px rgba(79, 70, 229, 0.3);
                }
                .btn-submit:hover { background: var(--primary-hover); }

                .action-links {
                    margin-top: 25px;
                    padding-top: 20px;
                    border-top: 1px solid var(--border);
                    display: flex;
                    justify-content: space-around;
                }
                .action-links a {
                    color: var(--primary);
                    text-decoration: none;
                    font-size: 13px;
                    font-weight: 600;
                }
                .action-links a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <div class="upload-card">
                <div class="icon-circle">📊</div>
                <h1>Import Scheme Receipts</h1>
                <p class="desc">Select or drop any Scheme Receipts Excel file (.xlsx). The background engine will match tickets, partners, journals, and post account entries automatically.</p>

                <form id="uploadForm" action="/import/schemes/upload" method="POST" enctype="multipart/form-data">
                    <div class="drop-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
                        <div class="drop-zone-text">📁 Click or Drag & Drop Excel File</div>
                        <div class="drop-zone-sub">Supports .xlsx format (e.g. Vyttila Journal, HO Scheme Opening, etc.)</div>
                        <div class="file-info" id="fileInfo"></div>
                    </div>
                    <input type="file" name="file" id="fileInput" accept=".xlsx" onchange="showFileName(this)">
                    
                    <button type="submit" class="btn-submit" id="btnSubmit">Start Background Import</button>
                </form>

                <div class="action-links">
                    <a href="/import/schemes/now">📈 Monitor Live Progress</a>
                </div>

            </div>

            <script>
                const dropZone = document.getElementById('dropZone');
                const fileInput = document.getElementById('fileInput');

                dropZone.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    dropZone.classList.add('dragover');
                });
                dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
                dropZone.addEventListener('drop', (e) => {
                    e.preventDefault();
                    dropZone.classList.remove('dragover');
                    if (e.dataTransfer.files.length) {
                        fileInput.files = e.dataTransfer.files;
                        showFileName(fileInput);
                    }
                });

                function showFileName(input) {
                    const info = document.getElementById('fileInfo');
                    if (input.files && input.files[0]) {
                        info.style.display = 'block';
                        info.innerText = 'Selected File: ' + input.files[0].name + ' (' + (input.files[0].size / 1024).toFixed(1) + ' KB)';
                    }
                }
            </script>
        </body>
        </html>
        """
        return request.make_response(html_content, headers=[('Content-Type', 'text/html')])

    @http.route('/import/schemes/vyttila', type='http', auth='user')
    def trigger_vyttila_import(self, **kwargs):
        file_path = '/home/akhil/Downloads/NAKSHATHRA PROJECT/xlsx/scheme imports/vytilla journel import.xlsx'
        if not os.path.exists(file_path):
            file_name = 'vytilla journel import.xlsx'
            file_path = get_module_resource('custom_scheme_recipt_import', 'data', file_name)

        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"

        db_name = request.env.cr.dbname
        uid = request.env.uid

        thread = threading.Thread(target=run_import_in_background, args=(db_name, uid, file_path))
        thread.start()

        return request.redirect('/import/schemes/now?vyttila=1')

    @http.route('/import/schemes/now', type='http', auth='user')
    def trigger_scheme_import(self, **kwargs):
        file_name = 'Scheme Opening HO.xlsx'
        file_path = get_module_resource('custom_scheme_recipt_import', 'data', file_name)

        if kwargs.get('uploaded'):
            pass # Thread is already running from POST upload
        elif file_path and os.path.exists(file_path):
            db_name = request.env.cr.dbname
            uid = request.env.uid
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

    @http.route('/import/schemes/undo', type='http', auth='user')
    def undo_scheme_import(self, **kwargs):
        file_name = 'Scheme Opening HO.xlsx'
        file_path = get_module_resource('custom_scheme_recipt_import', 'data', file_name)

        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"
        
        try:
            import openpyxl
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            sheet = workbook.active
            h_map = {str(sheet.cell(row=1, column=i).value).strip(): i for i in range(1, sheet.max_column + 1) if sheet.cell(row=1, column=i).value}
            
            tickets = set()
            for row_idx in range(2, sheet.max_row + 1):
                idx = h_map.get('Ticket Number')
                val = sheet.cell(row=row_idx, column=idx).value if idx else False
                if val:
                    tickets.add(str(val).strip().upper())
                    
            if not tickets:
                return "<h1>No tickets found in the excel file to undo.</h1>"

            env = request.env
            enrollments = env['jewellery.scheme.enrollment'].sudo().search([('ticket_number', 'in', list(tickets))])
            installments = env['jewellery.scheme.installment'].sudo().search([('enrollment_id', 'in', enrollments.ids)])
            
            # Unpost and delete moves
            moves_to_delete = env['account.move'].sudo()
            for inst in installments:
                if inst.move_id and (inst.move_id.ref or "").startswith("Scheme Payment:"):
                    moves_to_delete |= inst.move_id
                    
            additional_moves = env['account.move'].sudo().search([('ref', 'in', [f"Scheme Payment: {t}" for t in tickets])])
            moves_to_delete |= additional_moves
            
            for move in moves_to_delete:
                if move.state == 'posted':
                    move.button_draft()
            
            moves_count = len(moves_to_delete)
            inst_count = len(installments)
            enr_count = len(enrollments)
            
            moves_to_delete.unlink()
            installments.unlink()
            enrollments.unlink()
            
            return f"<h1>Undo Complete</h1><p>Successfully deleted {enr_count} enrollments, {inst_count} installments, and {moves_count} journal entries matching the tickets in the Excel file.</p>"
        except Exception as e:
            return f"<h1>Error during Undo</h1><p>{str(e)}</p>"

    @http.route('/import/schemes/fix_vyttila_journals', type='http', auth='user')
    def fix_vyttila_journals(self, **kwargs):
        """ Fixes existing scheme installment records in DB that are missing journal_id for Vyttila entries. """
        try:
            env = request.env
            # 1. Find Vyttila journal
            journal = env['account.journal'].sudo().search([
                '|', '|',
                ('name', 'ilike', '50200117325578'),
                ('name', 'ilike', 'Vyttila'),
                ('name', 'ilike', 'Vytila')
            ], limit=1)
            
            if not journal:
                return "<h1>Error</h1><p>Vyttila journal not found in database.</p>"
                
            # 2. Update existing installments for Vyttila tickets precisely
            file_path = '/home/akhil/Downloads/NAKSHATHRA PROJECT/xlsx/scheme imports/vytilla journel import.xlsx'
            if os.path.exists(file_path):
                import openpyxl
                wb = openpyxl.load_workbook(file_path, data_only=True)
                sheet = wb.active
                h_map = {str(sheet.cell(row=1, column=i).value).strip(): i for i in range(1, sheet.max_column + 1) if sheet.cell(row=1, column=i).value}
                t_col = h_map.get('Ticket Number')
                tx_col = h_map.get('Scheme Line/Transaction Id')
                
                tickets = set()
                tx_ids = set()
                for r in range(2, sheet.max_row + 1):
                    t_val = sheet.cell(row=r, column=t_col).value if t_col else None
                    tx_val = sheet.cell(row=r, column=tx_col).value if tx_col else None
                    if t_val:
                        tickets.add(str(t_val).strip().upper())
                    if tx_val:
                        tx_ids.add(str(tx_val).strip())
                        
                domain = [
                    ('move_id', '=', False),
                    '|',
                    ('journal_id', '=', False),
                    ('transaction_id', 'in', list(tx_ids))
                ]
                installments = env['jewellery.scheme.installment'].sudo().search(domain)
                installments = installments.filtered(lambda i: i.enrollment_id and i.enrollment_id.ticket_number and i.enrollment_id.ticket_number.upper() in tickets)
                fixed_count = len(installments)
                
                # Account resolution for move creation
                ob_acc = env['account.account'].sudo().search([
                    ('company_id', '=', journal.company_id.id),
                    ('name', 'ilike', 'Outstanding Rec')
                ], limit=1)
                if not ob_acc:
                    ob_acc = journal.default_account_id
                if not ob_acc:
                    ob_acc = env['account.account'].sudo().search([
                        ('company_id', '=', journal.company_id.id),
                        '|',
                        ('name', 'ilike', 'opening balance'),
                        ('account_type', '=', 'current_assets'),
                    ], limit=1)
                    
                dr_acc = env['account.account'].sudo().search([
                    ('company_id', '=', journal.company_id.id),
                    ('name', 'ilike', 'Debtor')
                ], limit=1)
                if not dr_acc:
                    dr_acc = env['account.account'].sudo().search([
                        ('company_id', '=', journal.company_id.id),
                        ('account_type', '=', 'asset_receivable'),
                    ], limit=1)

                moves_created = 0
                for inst in installments:
                    inst_vals = {'journal_id': journal.id}
                    if not inst.move_id and ob_acc and dr_acc and inst.amount > 0:
                        ticket_num = inst.enrollment_id.ticket_number or ''
                        partner_id = inst.enrollment_id.partner_id.id if inst.enrollment_id else False
                        move_vals = {
                            'journal_id': journal.id,
                            'date': inst.date or fields.Date.today(),
                            'ref': f"Scheme Payment: {ticket_num}",
                            'move_type': 'entry',
                            'company_id': journal.company_id.id,
                        }
                        if hasattr(journal, 'branch_id') and journal.branch_id:
                            move_vals['branch_id'] = journal.branch_id.id
                            
                        move_vals['line_ids'] = [
                            (0, 0, {
                                'name': f'Scheme Liability (Opening) - {ticket_num}',
                                'account_id': ob_acc.id,
                                'debit': inst.amount,
                                'credit': 0.0,
                                'partner_id': partner_id,
                            }),
                            (0, 0, {
                                'name': f'Scheme Payment - {ticket_num}',
                                'account_id': dr_acc.id,
                                'debit': 0.0,
                                'credit': inst.amount,
                                'partner_id': partner_id,
                            }),
                        ]
                        try:
                            new_move = env['account.move'].sudo().create(move_vals)
                            new_move.sudo().action_post()
                            inst_vals['move_id'] = new_move.id
                            moves_created += 1
                        except Exception as move_err:
                            _logger.warning("Failed to create move for installment %s: %s", inst.id, move_err)

                    inst.sudo().write(inst_vals)

                return f"<h1>Fix Complete</h1><p>Successfully updated ONLY {fixed_count} unassigned imported installment records with Journal <b>'{journal.name}'</b> (ID: {journal.id}) and generated {moves_created} Customer Moves (account.move entries).</p>"
            else:
                # Fallback DB-wide fix for missing journal_id
                installments = env['jewellery.scheme.installment'].sudo().search([('journal_id', '=', False)])
                fixed_count = len(installments)
                installments.sudo().write({'journal_id': journal.id})
                return f"<h1>Fix Complete (Fallback)</h1><p>Successfully updated {fixed_count} installment records with Journal <b>'{journal.name}'</b>.</p>"
        except Exception as e:
            return f"<h1>Error fixing DB records</h1><p>{str(e)}</p>"

    @http.route('/import/schemes/revert_fix', type='http', auth='user')
    def revert_fix_vyttila_journals(self, **kwargs):
        try:
            env = request.env
            file_path = '/home/akhil/Downloads/NAKSHATHRA PROJECT/xlsx/scheme imports/vytilla journel import.xlsx'
            if not os.path.exists(file_path):
                return "<h1>Error</h1><p>Excel file not found.</p>"

            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet = wb.active
            h_map = {str(sheet.cell(row=1, column=i).value).strip(): i for i in range(1, sheet.max_column + 1) if sheet.cell(row=1, column=i).value}
            t_col = h_map.get('Ticket Number')
            tickets = set()
            for r in range(2, sheet.max_row + 1):
                val = sheet.cell(row=r, column=t_col).value if t_col else None
                if val:
                    tickets.add(str(val).strip().upper())

            enrollments = env['jewellery.scheme.enrollment'].sudo().search([('ticket_number', 'in', list(tickets))])
            installments = env['jewellery.scheme.installment'].sudo().search([('enrollment_id', 'in', enrollments.ids)])

            moves_to_revert = env['account.move'].sudo().search([('ref', 'in', [f"Scheme Payment: {t}" for t in tickets])])
            
            reverted_insts = 0
            for inst in installments:
                if inst.move_id and inst.move_id in moves_to_revert:
                    inst.sudo().write({'move_id': False, 'journal_id': False})
                    reverted_insts += 1
                elif inst.journal_id and inst.journal_id.name and ('50200117325578' in inst.journal_id.name or 'Vyttila' in inst.journal_id.name or 'Vytila' in inst.journal_id.name):
                    if inst.transaction_id:
                        inst.sudo().write({'journal_id': False})
                        reverted_insts += 1

            for m in moves_to_revert:
                if m.state == 'posted':
                    m.button_draft()

            moves_count = len(moves_to_revert)
            moves_to_revert.unlink()

            return f"<h1>Revert Complete</h1><p>Successfully unposted and deleted {moves_count} journal entries and reset {reverted_insts} installments back to their original state.</p>"
        except Exception as e:
            return f"<h1>Error during Revert</h1><p>{str(e)}</p>"

