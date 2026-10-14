import openpyxl
import logging
import os
import threading
import gc
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
        partner = env['res.partner'].with_context(
            tracking_disable=True,
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            mail_notrack=True,
        ).create({
            'name': name,
            'phone': str(phone) if phone else False,
            'customer_rank': 1,
        })
    return partner

def run_import_in_background(db_name, uid, file_path, is_temp=False):
    """ Runs the heavy import in a background thread to prevent Odoo web timeouts. """
    _logger.info("Starting background import thread for %s", file_path)
    
    registry = odoo.registry(db_name)
    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
        workbook = None
        
        try:
            workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            sheet = workbook.active

            rows_iter = sheet.iter_rows(values_only=True)
            header_row = next(rows_iter, None)

            if not header_row:
                _logger.warning("Empty Excel sheet found in %s", file_path)
                env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', 'DONE')
                return

            h_map = {
                str(col_name).strip(): idx
                for idx, col_name in enumerate(header_row)
                if col_name is not None and str(col_name).strip()
            }

            # Pre-filter all valid data rows up to consecutive empty rows
            # This completely avoids ghost rows (e.g. 1,048,576 formatted empty rows)
            data_rows = []
            consecutive_empty = 0
            for row in rows_iter:
                has_data = any(
                    c_idx < len(row) and row[c_idx] not in (None, False, '') and str(row[c_idx]).strip() != ''
                    for c_idx in h_map.values()
                )
                if not has_data:
                    consecutive_empty += 1
                    if consecutive_empty >= 25:
                        break
                    continue
                consecutive_empty = 0
                data_rows.append(row)

            # Close workbook immediately since all data is now loaded in memory
            try:
                workbook.close()
                workbook = None
            except Exception:
                pass

            total_data_rows = len(data_rows)
            if not total_data_rows:
                _logger.warning("No data rows found in %s", file_path)
                env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', 'DONE')
                env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_total', '0')
                return

            total_excel_lines = total_data_rows + 1  # Including header line
            last_valid_ticket = False
            scheme_tracker = {}
            count_scheme = 0
            count_lines = 0
            _account_cache = {}

            # Initialize Progress Tracking with exact line count
            env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', '1')
            env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_total', str(total_excel_lines))
            cr.commit()

            bulk_ctx = {
                'tracking_disable': True,
                'mail_create_nosubscribe': True,
                'mail_create_nolog': True,
                'mail_notrack': True,
                'mail_auto_subscribe_no_notify': True,
            }

            for row_idx, row in enumerate(data_rows, start=2):
                # Update progress periodically so frontend receives it
                update_step = 10 if total_excel_lines <= 500 else (50 if total_excel_lines <= 5000 else 100)
                if row_idx % update_step == 0 or row_idx == total_excel_lines:
                    env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', str(row_idx))
                    env.cr.commit()

                # Periodically commit and clear cache + run garbage collection!
                if row_idx % 250 == 0:
                    env.cr.commit()
                    env.clear()
                    gc.collect()
                    _logger.info("Committed up to line %s/%s. Memory cleared.", row_idx, total_excel_lines)

                # Pre-fetch all cell values for current row in a dict
                row_vals = {
                    col: row[c_idx] if c_idx < len(row) else None
                    for col, c_idx in h_map.items()
                }

                get_v = row_vals.get

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
                                        journal_name = str(journal_name).strip()
                                        journal = env['account.journal'].search([('name', '=', journal_name), ('company_id', '=', 5)], limit=1)
                                        if not journal:
                                            journal = env['account.journal'].search([('name', '=', journal_name)], limit=1)
                                        
                                        if not journal and 'Vyt' in journal_name:
                                            alt_name = journal_name.replace('Vyttila', 'Vytila') if 'Vyttila' in journal_name else journal_name.replace('Vytila', 'Vyttila')
                                            journal = env['account.journal'].search([('name', '=', alt_name), ('company_id', '=', 5)], limit=1)
                                            if not journal:
                                                journal = env['account.journal'].search([('name', '=', alt_name)], limit=1)

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
                                        
                                    scheme_id = env['jewellery.scheme.enrollment'].with_context(**bulk_ctx).create(scheme_vals).id
                                    count_scheme += 1

                            if scheme_id:
                                scheme_tracker[last_valid_ticket] = scheme_id

                        # 2. Installment + Journal Entry Logic
                        line_date_raw = get_v('Scheme Line/Date') or get_v('Date') or get_v('Payment date') or get_v('Payment Date')
                        line_amount   = get_v('Scheme Line/Amount') or get_v('Amount') or get_v('Amount ') or get_v('Installment Amount')
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
                            journal_name = str(journal_name).strip()
                            journal = env['account.journal'].search([('name', '=', journal_name), ('company_id', '=', 5)], limit=1)
                            if not journal:
                                journal = env['account.journal'].search([('name', '=', journal_name)], limit=1)
                            
                            if not journal and 'Vyt' in journal_name:
                                alt_name = journal_name.replace('Vyttila', 'Vytila') if 'Vyttila' in journal_name else journal_name.replace('Vytila', 'Vyttila')
                                journal = env['account.journal'].search([('name', '=', alt_name), ('company_id', '=', 5)], limit=1)
                                if not journal:
                                    journal = env['account.journal'].search([('name', '=', alt_name)], limit=1)
                            
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
                                new_move = env['account.move'].with_context(**bulk_ctx).create(move_vals)
                                new_move.with_context(**bulk_ctx).action_post()
                                generated_move_id = new_move.id
                                _logger.info("Row %s: Journal entry created (id=%s) ticket=%s amount=%.2f", row_idx, generated_move_id, last_valid_ticket, line_amount_f)

                        env['jewellery.scheme.installment'].with_context(**bulk_ctx).create({
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
            err_msg = str(e) or type(e).__name__
            if isinstance(e, MemoryError):
                err_msg = "Server ran out of memory (MemoryError). Memory limit reached."
            env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', 'ERROR: ' + err_msg)
            _logger.exception("Background Import Failure: %s", err_msg)
        finally:
            if workbook:
                try:
                    workbook.close()
                except Exception:
                    pass
            if is_temp and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    _logger.warning("Could not remove temp file %s: %s", file_path, e)


class SchemeImportController(http.Controller):

    @http.route('/import/schemes', type='http', auth='user')
    def upload_scheme_form(self, **kwargs):
        html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: 'Inter', Arial, sans-serif; text-align: center; margin-top: 50px; background: #f0f2f5; color: #333; }}
                    h1 {{ color: #2c3e50; font-weight: 600; }}
                    .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
                    .file-input {{ margin: 20px 0; }}
                    button {{ background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 16px; }}
                    button:hover {{ background: #0056b3; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Upload Scheme Excel File</h1>
                    <form action="/import/schemes/now" method="POST" enctype="multipart/form-data">
                        <input type="hidden" name="csrf_token" value="{request.csrf_token()}"/>
                        <div class="file-input">
                            <input type="file" name="file" accept=".xlsx" required="required"/>
                        </div>
                        <button type="submit">Upload and Import</button>
                    </form>
                </div>
            </body>
            </html>
        """
        return request.make_response(html_content, headers=[('Content-Type', 'text/html')])

    @http.route('/import/schemes/now', type='http', auth='user', methods=['GET', 'POST'], csrf=False)
    def trigger_scheme_import(self, **kwargs):
        upload_file = kwargs.get('file')
        is_temp = False

        if upload_file:
            import tempfile
            fd, file_path = tempfile.mkstemp(suffix='.xlsx')
            with os.fdopen(fd, 'wb') as f:
                f.write(upload_file.read())
            is_temp = True
        else:
            file_name = 'scheme cash(1).xlsx'
            file_path = get_module_resource('custom_scheme_recipt_import', 'data', file_name)

        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"

        db_name = request.env.cr.dbname
        uid = request.env.uid

        # Reset progress parameter immediately so frontend doesn't show stale error
        request.env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_progress', 'Starting...')
        request.env['ir.config_parameter'].sudo().set_param('scheme_receipt_import_total', '...')
        request.env.cr.commit()

        # Launch background thread
        thread = threading.Thread(target=run_import_in_background, args=(db_name, uid, file_path, is_temp))
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
                    <p class="msg">The rows are being processed in the background.</p>
                    
                    <div class="progress-wrapper">
                        <div class="progress-bar" id="progressBar"></div>
                        <div class="progress-text" id="progressText">0%</div>
                    </div>
                    
                    <div class="status" id="statusText">Starting import...</div>
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
                                } else if (data.progress === 'Starting...') {
                                    document.getElementById('statusText').innerText = 'Initializing and loading file...';
                                    setTimeout(fetchProgress, 2000);
                                } else {
                                    let current = parseInt(data.progress) || 0;
                                    let total = parseInt(data.total);
                                    if (isNaN(total) || total <= 0 || total > 500000) {
                                        document.getElementById('progressBar').style.width = '100%';
                                        document.getElementById('progressText').innerText = '';
                                        document.getElementById('statusText').innerText = 'Processing row ' + current + '...';
                                    } else {
                                        let percent = Math.min(100, Math.round((current / total) * 100));
                                        document.getElementById('progressBar').style.width = percent + '%';
                                        document.getElementById('progressText').innerText = percent + '%';
                                        document.getElementById('statusText').innerText = 'Processing row ' + current + ' of ' + total;
                                    }
                                    
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
        
        workbook = None
        try:
            import openpyxl
            workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            sheet = workbook.active
            rows_iter = sheet.iter_rows(values_only=True)
            header_row = next(rows_iter, None)
            if not header_row:
                return "<h1>No tickets found in the excel file to undo.</h1>"

            h_map = {str(col_name).strip(): idx for idx, col_name in enumerate(header_row) if col_name is not None and str(col_name).strip()}
            
            tickets = set()
            t_idx = h_map.get('Ticket Number')
            if t_idx is not None:
                consecutive_empty = 0
                for row in rows_iter:
                    val = row[t_idx] if t_idx < len(row) else None
                    if val:
                        tickets.add(str(val).strip().upper())
                        consecutive_empty = 0
                    else:
                        consecutive_empty += 1
                        if consecutive_empty >= 25:
                            break
                    
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
        finally:
            if workbook:
                try:
                    workbook.close()
                except Exception:
                    pass
