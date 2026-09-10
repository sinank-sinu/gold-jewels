import openpyxl
import logging
import os
import tempfile
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


def process_import_chunk(db_name, uid, file_path, start_row, chunk_size=500):
    registry = odoo.registry(db_name)
    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, uid, {})
        
        try:
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            sheet = workbook.active
            
            h_map = {str(sheet.cell(row=1, column=i).value).strip(): i
                     for i in range(1, sheet.max_column + 1)
                     if sheet.cell(row=1, column=i).value}
                     
            max_row = sheet.max_row
            end_row = min(start_row + chunk_size, max_row + 1)
            
            _account_cache = {}
            scheme_tracker = {}
            last_valid_ticket = False
            
            for row_idx in range(start_row, end_row):
                def get_v(col_name, _row=row_idx):
                    idx = h_map.get(col_name)
                    return sheet.cell(row=_row, column=idx).value if idx else False
                    
                try:
                    with env.cr.savepoint():
                        current_ticket_raw = get_v('Ticket Number')
                        if current_ticket_raw:
                            last_valid_ticket = str(current_ticket_raw).strip()
                        if not last_valid_ticket:
                            continue

                        line_date = parse_date(get_v('Scheme Line/Date') or get_v('Date') or get_v('Payment date') or get_v('Payment Date'))
                        line_amount_f = safe_float(get_v('Scheme Line/Amount') or get_v('Amount') or get_v('Installment Amount'))

                        # 1. Enrollment Logic
                        scheme_id = scheme_tracker.get(last_valid_ticket)
                        if not scheme_id:
                            existing = env['jewellery.scheme.enrollment'].search([('ticket_number', '=', last_valid_ticket)], limit=1)
                            if existing:
                                scheme_id = existing.id
                            else:
                                partner_name = str(get_v('Partner') or get_v('Customer')).strip() if (get_v('Partner') or get_v('Customer')) else False
                                if partner_name:
                                    partner = _find_or_create_partner(env, partner_name, get_v('Phone'))
                                    active_raw = get_v('Active')
                                    is_active = str(active_raw).lower() in ['true', '1', 'yes'] if active_raw else False
                                    scheme_id = env['jewellery.scheme.enrollment'].create({
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
                                        'date_of_joining': line_date or fields.Date.today(),
                                        'branch_id': False,
                                    }).id
                            if scheme_id:
                                scheme_tracker[last_valid_ticket] = scheme_id

                        # 2. Installment + Journal Entry Logic
                        if not scheme_id or not (line_date or line_amount_f):
                            continue

                        journal_name = get_v('Scheme Line/Journal')
                        journal = env['account.journal'].search([('name', '=', str(journal_name).strip())], limit=1) if journal_name else False
                        
                        excel_move_name = get_v('Scheme Line/Move')
                        excel_move_id = env['account.move'].search([('name', '=', str(excel_move_name).strip())], limit=1) if excel_move_name else False
                        generated_move_id = False

                        if not excel_move_id and journal and line_amount_f:
                            if journal.id not in _account_cache:
                                ob = env['account.account'].search([('company_id', '=', journal.company_id.id), '|', ('name', 'ilike', 'opening balance'), ('account_type', '=', 'current_assets')], limit=1)
                                dr = env['account.account'].search([('company_id', '=', journal.company_id.id), '|', ('name', 'ilike', 'debtor'), ('account_type', '=', 'asset_receivable')], limit=1)
                                _account_cache[journal.id] = (ob, dr)
                            ob_acc, dr_acc = _account_cache[journal.id]
                            if ob_acc and dr_acc:
                                scheme_record = env['jewellery.scheme.enrollment'].browse(scheme_id)
                                new_move = env['account.move'].create({
                                    'journal_id': journal.id,
                                    'date': line_date or fields.Date.today(),
                                    'ref': f"Scheme Payment: {last_valid_ticket}",
                                    'move_type': 'entry',
                                    'line_ids': [
                                        (0, 0, {'name': f'Scheme Liability (Opening) - {last_valid_ticket}', 'account_id': ob_acc.id, 'debit': line_amount_f, 'credit': 0.0, 'partner_id': scheme_record.partner_id.id}),
                                        (0, 0, {'name': f'Scheme Payment - {last_valid_ticket}', 'account_id': dr_acc.id, 'debit': 0.0, 'credit': line_amount_f, 'partner_id': scheme_record.partner_id.id}),
                                    ],
                                })
                                new_move.action_post()
                                generated_move_id = new_move.id
                                
                        env['jewellery.scheme.installment'].create({
                            'enrollment_id': scheme_id, 'date': line_date or fields.Date.today(), 'amount': line_amount_f,
                            'journal_id': journal.id if journal else False,
                            'state': str(get_v('Scheme Line/State')).lower() if get_v('Scheme Line/State') else 'paid',
                            'move_id': excel_move_id.id if excel_move_id else generated_move_id,
                            'transaction_id': get_v('Scheme Line/Transaction ID'),
                        })
                        _logger.info("Row %s: Imported Installment - Ticket: %s | Amount: %s | Move: %s", row_idx, last_valid_ticket, line_amount_f, generated_move_id or excel_move_id.id or 'None')
                except Exception as row_err:
                    _logger.error("Row %s skipped - %s", row_idx, str(row_err))
                    
            _logger.info("Successfully committed chunk from row %s to %s.", start_row, end_row - 1)
            env.cr.commit()
            return end_row, max_row
            
        except Exception as e:
            env.cr.rollback()
            _logger.error("Import Failure: %s", str(e))
            return -1, -1

class SchemeImportController(http.Controller):

    def _render_upload_form(self):
        csrf_token = request.csrf_token()
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Scheme Opening Excel Import</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * {{ box-sizing: border-box; }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    background: #f0f2f5;
                    color: #333;
                    margin: 0;
                    padding: 40px 20px;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 80vh;
                }}
                .container {{
                    max-width: 580px;
                    width: 100%;
                    background: #ffffff;
                    padding: 40px 35px;
                    border-radius: 12px;
                    box-shadow: 0 6px 20px rgba(0,0,0,0.07);
                }}
                h1 {{
                    color: #1a202c;
                    font-size: 24px;
                    font-weight: 700;
                    margin-top: 0;
                    margin-bottom: 8px;
                }}
                .subtitle {{
                    color: #718096;
                    font-size: 14px;
                    margin-bottom: 25px;
                    line-height: 1.5;
                }}
                .drop-area {{
                    border: 2px dashed #cbd5e0;
                    border-radius: 8px;
                    padding: 30px 20px;
                    text-align: center;
                    background: #f7fafc;
                    transition: border-color 0.2s, background 0.2s;
                    margin-bottom: 22px;
                    cursor: pointer;
                }}
                .drop-area:hover {{
                    border-color: #3182ce;
                    background: #ebf8ff;
                }}
                .drop-area input[type="file"] {{
                    display: none;
                }}
                .file-label {{
                    display: block;
                    cursor: pointer;
                    font-size: 15px;
                    color: #4a5568;
                    font-weight: 500;
                }}
                .file-name {{
                    margin-top: 12px;
                    font-size: 14px;
                    color: #2b6cb0;
                    font-weight: 600;
                    word-break: break-all;
                }}
                .info-card {{
                    background: #edf2f7;
                    border-left: 4px solid #3182ce;
                    padding: 12px 16px;
                    border-radius: 4px;
                    font-size: 13px;
                    color: #2d3748;
                    margin-bottom: 25px;
                    line-height: 1.4;
                }}
                .btn-submit {{
                    background: #3182ce;
                    color: #ffffff;
                    border: none;
                    width: 100%;
                    padding: 13px 20px;
                    border-radius: 6px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: background 0.2s, transform 0.1s;
                }}
                .btn-submit:hover {{
                    background: #2b6cb0;
                }}
                .btn-submit:active {{
                    transform: scale(0.99);
                }}
                .btn-submit:disabled {{
                    background: #a0aec0;
                    cursor: not-allowed;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Scheme Opening Bulk Import</h1>
                <p class="subtitle">Upload an Excel (.xlsx) file to import Scheme Enrollments, Installments, and opening Journal Entries.</p>
                
                <div class="info-card">
                    <b>Note:</b> Supports large files with thousands of rows. The file will be processed in chunks of 500 rows with real-time automatic progress updates.
                </div>

                <form id="uploadForm" action="/import/schemes/opening" method="POST" enctype="multipart/form-data">
                    <input type="hidden" name="csrf_token" value="{csrf_token}"/>
                    
                    <div class="drop-area" onclick="document.getElementById('excelFileInput').click();">
                        <label class="file-label" for="excelFileInput">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#4a5568" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom:8px; display:block; margin-left:auto; margin-right:auto;">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                <polyline points="17 8 12 3 7 8"></polyline>
                                <line x1="12" y1="3" x2="12" y2="15"></line>
                            </svg>
                            <span>Click to choose an Excel file (.xlsx)</span>
                        </label>
                        <input type="file" id="excelFileInput" name="file" accept=".xlsx,.xls" required />
                        <div class="file-name" id="selectedFileName"></div>
                    </div>

                    <button type="submit" class="btn-submit" id="submitBtn">Upload & Start Import</button>
                </form>
            </div>

            <script>
                const fileInput = document.getElementById('excelFileInput');
                const fileNameDiv = document.getElementById('selectedFileName');
                const submitBtn = document.getElementById('submitBtn');
                const form = document.getElementById('uploadForm');

                fileInput.addEventListener('change', function() {{
                    if (this.files && this.files.length > 0) {{
                        fileNameDiv.innerText = 'Selected file: ' + this.files[0].name;
                    }} else {{
                        fileNameDiv.innerText = '';
                    }}
                }});

                form.addEventListener('submit', function() {{
                    submitBtn.disabled = true;
                    submitBtn.innerText = 'Uploading... Please wait';
                }});
            </script>
        </body>
        </html>
        """
        return request.make_response(html_content, headers=[('Content-Type', 'text/html')])

    @http.route(['/import/schemes/opening', '/import/schemes/opening/now', '/import/schemes/opening/form'], type='http', auth='user', methods=['GET', 'POST'], csrf=False)
    def trigger_scheme_import(self, **kwargs):
        upload_file = kwargs.get('file')
        tmp_file = kwargs.get('tmp_file')
        start_row_raw = kwargs.get('start_row')

        # If GET request and no upload/processing parameters, show the upload interface
        if request.httprequest.method == 'GET' and not start_row_raw and not tmp_file and not upload_file:
            return self._render_upload_form()

        # Handle uploaded file from form
        if upload_file and hasattr(upload_file, 'read'):
            fd, file_path = tempfile.mkstemp(suffix='.xlsx')
            with os.fdopen(fd, 'wb') as f:
                f.write(upload_file.read())
            tmp_file = file_path
            start_row = 2
        elif tmp_file and os.path.exists(tmp_file):
            abs_tmp = os.path.abspath(tmp_file)
            if not abs_tmp.startswith(os.path.abspath(tempfile.gettempdir())):
                return request.make_response("<h1>Error</h1><p>Invalid temporary file path.</p>", headers=[('Content-Type', 'text/html')])
            file_path = tmp_file
            start_row = int(start_row_raw or 2)
        else:
            # Fallback to module default file if exists
            file_name = 'SCHEME - ONE OPENING ENTRY 03-08-2026.xlsx'
            file_path = get_module_resource('custom_scheme_import', 'data', file_name)
            if not file_path or not os.path.exists(file_path):
                file_path = os.path.join(os.path.dirname(__file__), '..', 'data', file_name)
            start_row = int(start_row_raw or 2)

        if not file_path or not os.path.exists(file_path):
            error_html = """
            <html>
                <head>
                    <title>File Not Found</title>
                    <style>
                        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; margin-top: 60px; background: #f4f6f9; }
                        .card { max-width: 500px; margin: 0 auto; background: white; padding: 35px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }
                        h1 { color: #dc3545; font-size: 24px; margin-bottom: 12px; }
                        p { color: #555; font-size: 15px; line-height: 1.5; }
                        .btn { display: inline-block; margin-top: 20px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 14px; }
                        .btn:hover { background: #0056b3; }
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>File Not Found</h1>
                        <p>No file was uploaded and default file could not be found.</p>
                        <a href="/import/schemes/opening" class="btn">Go to Upload Page</a>
                    </div>
                </body>
            </html>
            """
            return request.make_response(error_html, headers=[('Content-Type', 'text/html')])

        db_name = request.env.cr.dbname
        uid = request.env.uid

        end_row, max_row = process_import_chunk(db_name, uid, file_path, start_row, chunk_size=500)
        
        if end_row == -1:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception as e:
                    _logger.warning("Could not remove temp file %s: %s", tmp_file, e)
            fail_html = """
            <html>
                <head>
                    <title>Import Failed</title>
                    <style>
                        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; margin-top: 60px; background: #f4f6f9; }
                        .card { max-width: 500px; margin: 0 auto; background: white; padding: 35px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }
                        h1 { color: #dc3545; font-size: 24px; margin-bottom: 12px; }
                        p { color: #555; font-size: 15px; line-height: 1.5; }
                        .btn { display: inline-block; margin-top: 20px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 14px; }
                        .btn:hover { background: #0056b3; }
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>Import Failed</h1>
                        <p>An error occurred during chunk processing. Check server terminal logs for details.</p>
                        <a href="/import/schemes/opening" class="btn">Back to Upload</a>
                    </div>
                </body>
            </html>
            """
            return request.make_response(fail_html, headers=[('Content-Type', 'text/html')])

        if end_row > max_row:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception as e:
                    _logger.warning("Could not remove temp file %s: %s", tmp_file, e)
            html = """
            <html>
                <head>
                    <title>Import Completed</title>
                    <style>
                        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; margin-top: 60px; background: #f4f6f9; }
                        .card { max-width: 550px; margin: 0 auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }
                        h1 { color: #28a745; margin-bottom: 15px; font-size: 26px; }
                        p { color: #555; font-size: 16px; line-height: 1.5; }
                        .btn { display: inline-block; margin-top: 25px; padding: 12px 24px; background: #007bff; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 15px; }
                        .btn:hover { background: #0056b3; }
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>Import Completed Successfully!</h1>
                        <p>All rows have been imported.</p>
                        <a href="/import/schemes/opening" class="btn">Upload Another File</a>
                    </div>
                </body>
            </html>
            """
        else:
            progress = min(100, int((end_row / max_row) * 100))
            tmp_query = f"&tmp_file={tmp_file}" if tmp_file else ""
            refresh_url = f"/import/schemes/opening?start_row={end_row}{tmp_query}"
            html = f"""
            <html>
                <head>
                    <title>Importing Scheme Data...</title>
                    <meta http-equiv="refresh" content="0; url={refresh_url}" />
                    <style>
                        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; margin-top: 60px; background: #f4f6f9; }}
                        .card {{ max-width: 600px; margin: 0 auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
                        h1 {{ color: #007bff; margin-bottom: 20px; font-size: 24px; }}
                        .progress-bar {{ width: 100%; height: 28px; background: #e9ecef; margin: 25px auto; border-radius: 14px; overflow: hidden; position: relative; }}
                        .progress-fill {{ width: {progress}%; height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.3s; align-items: center; justify-content: center; color: white; display: flex; font-weight: bold; font-size: 14px; }}
                        .msg {{ font-size: 16px; color: #495057; margin: 10px 0; }}
                        .warning {{ color: #dc3545; font-size: 14px; margin-top: 20px; font-weight: 500; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>Importing Data... Please Wait</h1>
                        <div class="progress-bar"><div class="progress-fill">{progress}%</div></div>
                        <p class="msg">Processed up to row {end_row - 1} of {max_row}</p>
                        <p class="warning">Do not close this tab! It will auto-refresh until completed.</p>
                    </div>
                </body>
            </html>
            """
        return request.make_response(html, headers=[('Content-Type', 'text/html')])
