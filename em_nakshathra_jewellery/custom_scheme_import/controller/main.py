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
    @http.route('/import/schemes/opening', type='http', auth='user')
    def trigger_scheme_import(self, **kwargs):
        file_name = 'SCHEME - ONE OPENING ENTRY 03-08-2026.xlsx'
        file_path = get_module_resource('custom_scheme_import', 'data', file_name)
        
        if not file_path or not os.path.exists(file_path):
            return request.make_response(f"<h1>Error</h1><p>File not found at {file_path}</p>", headers=[('Content-Type', 'text/html')])

        start_row = int(kwargs.get('start_row', 2))
        db_name = request.env.cr.dbname
        uid = request.env.uid

        end_row, max_row = process_import_chunk(db_name, uid, file_path, start_row, chunk_size=500)
        
        if end_row == -1:
            return request.make_response("<h1>Import Failed</h1><p>Check terminal logs for errors.</p>", headers=[('Content-Type', 'text/html')])

        if end_row > max_row:
            html = "<html><head><style>body{font-family:Arial;text-align:center;margin-top:50px;background:#f9f9f9;}h1{color:#28a745;}</style></head><body><h1>Import Completed Successfully!</h1><p>All rows have been imported.</p></body></html>"
        else:
            progress = min(100, int((end_row / max_row) * 100))
            html = f"""
            <html>
                <head>
                    <meta http-equiv="refresh" content="0; url=/import/schemes/opening?start_row={end_row}" />
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
