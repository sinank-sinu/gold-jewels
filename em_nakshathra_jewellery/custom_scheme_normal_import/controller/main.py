import openpyxl
import logging
import os
from datetime import datetime, date
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
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%Y/%m/%d', '%m-%d-%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    _logger.warning("parse_date: Could not parse date value '%s'", value)
    return False

def safe_float(value):
    try:
        return float(value) if value not in (None, False, '') else 0.0
    except (TypeError, ValueError):
        return 0.0

def process_import_chunk(db_name, uid, file_path, start_row, chunk_size=100):
    try:
        registry = http.request.env.registry
        with registry.cursor() as cr:
            env = http.request.env(cr=cr, user=uid)
            
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            sheet = workbook.active

            h_map = {str(sheet.cell(row=1, column=i).value).strip(): i
                     for i in range(1, sheet.max_column + 1)
                     if sheet.cell(row=1, column=i).value}

            def get_v(row_val, col_name):
                idx = h_map.get(col_name)
                return sheet.cell(row=row_val, column=idx).value if idx else None
                
            max_row = sheet.max_row
            end_row = min(start_row + chunk_size, max_row + 1)

            _account_cache = {}
            last_valid_ticket = False

            for row_idx in range(start_row, end_row):
                try:
                    with env.cr.savepoint():
                        ticket_raw = get_v(row_idx, 'Ticket Number')
                        if ticket_raw:
                            last_valid_ticket = str(ticket_raw).strip().upper()

                        if not last_valid_ticket:
                            continue

                        scheme_id = False
                        existing_scheme = env['jewellery.scheme.enrollment'].search([
                            ('ticket_number', '=', last_valid_ticket)
                        ], limit=1)

                        if existing_scheme:
                            scheme_id = existing_scheme.id
                        else:
                            partner_name = str(get_v(row_idx, 'Partner')).strip() if get_v(row_idx, 'Partner') else False
                            if partner_name:
                                partner = env['res.partner'].search([('name', '=', partner_name)], limit=1)
                                if not partner:
                                    phone = get_v(row_idx, 'Phone')
                                    partner = env['res.partner'].create({
                                        'name': partner_name,
                                        'phone': str(phone) if phone else False,
                                        'customer_rank': 1,
                                    })

                                active_raw = get_v(row_idx, 'Active')
                                is_active = str(active_raw).lower() in ['true', '1', 'yes'] if active_raw else True

                                branch_name = get_v(row_idx, 'Branch Name')
                                branch_id = False
                                if branch_name:
                                    branch_record = env['res.branch'].search([('name', '=', str(branch_name).strip())], limit=1)
                                    if branch_record:
                                        branch_id = branch_record.id
                                    else:
                                        _logger.warning("Branch '%s' not found for ticket %s", branch_name, last_valid_ticket)

                                line_date_raw = get_v(row_idx, 'Scheme Line/Date')
                                line_amount   = get_v(row_idx, 'Scheme Line/Amount')
                                scheme_record = env['jewellery.scheme.enrollment'].create({
                                    'ticket_number':   last_valid_ticket,
                                    'partner_id':      partner.id,
                                    'date_of_joining': parse_date(line_date_raw) or fields.Date.today(),
                                    'branch_id':       branch_id,
                                    'active':          is_active,
                                    'duration':        get_v(row_idx, 'Duration') or 11,
                                    'installment_amount':   safe_float(line_amount),
                                    'phone':           str(get_v(row_idx, 'Phone')).replace('.0', '') if get_v(row_idx, 'Phone') else False,
                                    'whatsapp_number': str(get_v(row_idx, 'Whatsapp Number')).replace('.0', '') if get_v(row_idx, 'Whatsapp Number') else False,
                                    'address':         str(get_v(row_idx, 'Address')) if get_v(row_idx, 'Address') else False,
                                    'nominee':         str(get_v(row_idx, 'Nominee')) if get_v(row_idx, 'Nominee') else False,
                                    'name': str(get_v(row_idx, 'Name')).strip() if get_v(row_idx, 'Name') else False,
                                })
                                scheme_id = scheme_record.id

                        line_date_raw = get_v(row_idx, 'Scheme Line/Date')
                        line_amount   = get_v(row_idx, 'Scheme Line/Amount')
                        line_date     = parse_date(line_date_raw)
                        line_amount_f = safe_float(line_amount)

                        if not scheme_id or not (line_date or line_amount_f):
                            continue
                            
                        # Duplicate protection
                        dup_domain = [
                            ('enrollment_id', '=', scheme_id),
                            ('date', '=', line_date),
                            ('amount', '=', line_amount_f)
                        ]
                        t_id = get_v(row_idx, 'Scheme Line/Transaction ID')
                        if t_id:
                            dup_domain.append(('transaction_id', '=', str(t_id)))
                        
                        existing_installment = env['jewellery.scheme.installment'].search(dup_domain, limit=1)
                        
                        if existing_installment:
                            continue

                        journal_name = get_v(row_idx, 'Scheme Line/Journal')
                        journal = env['account.journal'].search([('name', '=', str(journal_name).strip())], limit=1) if journal_name else False
                        
                        excel_move_name = get_v(row_idx, 'Scheme Line/Move')
                        excel_move_id = env['account.move'].search([('name', '=', str(excel_move_name).strip())], limit=1) if excel_move_name else False
                        generated_move_id = False

                        if not excel_move_id and journal and line_amount_f:
                            if journal.id not in _account_cache:
                                ob_acc = env['account.account'].search([
                                    ('company_id', '=', journal.company_id.id),
                                    ('name', 'ilike', 'Opening Balance%'),
                                ], limit=1)
                                dr_acc = env['account.account'].search([
                                    ('company_id', '=', journal.company_id.id),
                                    ('name', 'ilike', 'Debtors'),
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
                                
                        env['jewellery.scheme.installment'].create({
                            'enrollment_id':  scheme_id,
                            'date':           line_date or fields.Date.today(),
                            'amount':         line_amount_f,
                            'journal_id':     journal.id if journal else False,
                            'state':          str(get_v(row_idx, 'Scheme Line/State')).lower() if get_v(row_idx, 'Scheme Line/State') else 'draft',
                            'move_id':        excel_move_id.id if excel_move_id else generated_move_id,
                            'transaction_id': get_v(row_idx, 'Scheme Line/Transaction ID'),
                        })
                        _logger.info("Row %s: Imported Normal Installment - Ticket: %s", row_idx, last_valid_ticket)

                except Exception as row_err:
                    _logger.error("Row %s skipped - %s", row_idx, str(row_err))
                    
            _logger.info("Successfully committed chunk from row %s to %s.", start_row, end_row - 1)
            env.cr.commit()
            return end_row, max_row
            
    except Exception as e:
        _logger.error("Import Failure: %s", str(e))
        return -1, -1

class SchemeImportController(http.Controller):
    @http.route('/import/schemes/normal/now', type='http', auth='user')
    def trigger_scheme_import(self, **kwargs):
        file_name = 'Gold Scheme New Joining Register April To July.xlsx'
        file_path = get_module_resource('custom_scheme_normal_import', 'data', file_name)
        
        if not file_path or not os.path.exists(file_path):
            file_path = os.path.join(os.path.dirname(__file__), '..', 'data', file_name)
            
        if not file_path or not os.path.exists(file_path):
            return request.make_response(f"<h1>Error</h1><p>File not found at {file_path}</p>", headers=[('Content-Type', 'text/html')])

        start_row = int(kwargs.get('start_row', 2))
        db_name = request.env.cr.dbname
        uid = request.env.uid

        end_row, max_row = process_import_chunk(db_name, uid, file_path, start_row, chunk_size=40)
        
        if end_row == -1:
            return request.make_response("<h1>Import Failed</h1><p>Check terminal logs for errors.</p>", headers=[('Content-Type', 'text/html')])

        if end_row > max_row:
            html = "<html><head><style>body{font-family:Arial;text-align:center;margin-top:50px;background:#f9f9f9;}h1{color:#28a745;}</style></head><body><h1>Import Completed Successfully!</h1><p>All rows have been imported.</p></body></html>"
        else:
            progress = min(100, int((end_row / max_row) * 100))
            html = f"""
            <html>
                <head>
                    <meta http-equiv="refresh" content="0; url=/import/schemes/normal/now?start_row={end_row}" />
                    <style>
                        body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; background: #f9f9f9; }}
                        h1 {{ color: #007bff; }}
                        .progress-bar {{ width: 50%; height: 30px; background: #ddd; margin: 20px auto; border-radius: 15px; overflow: hidden; }}
                        .progress-fill {{ width: {progress}%; height: 100%; background: #28a745; transition: width 0.5s; align-items: center; justify-content: center; color: white; display: flex; font-weight: bold; }}
                        .msg {{ font-size: 18px; color: #555; }}
                    </style>
                </head>
                <body>
                    <h1>Importing Data... Please Wait</h1>
                    <div class="progress-bar"><div class="progress-fill">{progress}%</div></div>
                    <p class="msg">Processed up to row {end_row - 1} of {max_row}</p>
                    <p class="msg" style="color:#dc3545;"><strong>Do not close this tab! It will auto-refresh until completed.</strong></p>
                </body>
            </html>
            """
        return request.make_response(html, headers=[('Content-Type', 'text/html')])
