import openpyxl
import logging
import os
from datetime import datetime, date
from odoo import http, fields
from odoo.http import request
from odoo.modules.module import get_module_resource

_logger = logging.getLogger(__name__)


def parse_date(value):
    """
    Robustly parse a date value from Excel.
    Handles:
      - Python date / datetime objects (openpyxl returns these for real date cells)
      - Strings in DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, YYYY/MM/DD formats
    Returns a datetime.date object, or False on failure.
    """
    if not value:
        return False
    # Already a date/datetime from openpyxl
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # String fallback – try common formats
    value = str(value).strip()
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%Y/%m/%d', '%m-%d-%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    _logger.warning("parse_date: Could not parse date value '%s'", value)
    return False


class SchemeImportController(http.Controller):

    @http.route('/import/schemes/now', type='http', auth='user')
    def trigger_scheme_import(self, **kwargs):
        file_name = 'Jewellery_Scheme_Enrollment_Processed.xlsx'
        file_path = get_module_resource('custom_scheme_import', 'data', file_name)

        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"

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

            for row_idx in range(2, sheet.max_row + 1):
                def get_v(col_name, _row=row_idx):          # capture row index in closure
                    idx = h_map.get(col_name)
                    return sheet.cell(row=_row, column=idx).value if idx else False

                current_ticket_raw = get_v('Ticket Number')
                if current_ticket_raw:
                    last_valid_ticket = str(current_ticket_raw).strip()

                if not last_valid_ticket:
                    continue

                # ----------------------------------------------------------------
                # 1.  Enrollment Logic
                # ----------------------------------------------------------------
                scheme_id = scheme_tracker.get(last_valid_ticket)
                if not scheme_id:
                    existing_scheme = request.env['jewellery.scheme.enrollment'].search([
                        ('ticket_number', '=', last_valid_ticket)
                    ], limit=1)

                    if existing_scheme:
                        scheme_id = existing_scheme.id
                    else:
                        partner_name = str(get_v('Partner')).strip() if get_v('Partner') else False
                        if partner_name:
                            partner = self._find_or_create_partner(partner_name, get_v('Phone'))
                            scheme_id = request.env['jewellery.scheme.enrollment'].create({
                                'name': get_v('Name'),
                                'ticket_number': last_valid_ticket,
                                'partner_id': partner.id,
                                'phone': get_v('Phone'),
                                'whatsapp_number': get_v('Whatsapp Number'),
                                'address': get_v('Address'),
                                'duration': get_v('Duration'),
                                'installment_amount': get_v('Installment Amount'),
                                'total_paid': get_v('Total Paid'),
                                'balance_amount': get_v('Balance Amount'),
                                'state': str(get_v('State')).lower() if get_v('State') else 'draft',
                                'active': True if str(get_v('Active')).lower() in ['true', '1', 'yes'] else False,
                                'nominee': get_v('Nominee'),
                            }).id
                            count_scheme += 1

                    if scheme_id:
                        scheme_tracker[last_valid_ticket] = scheme_id

                # ----------------------------------------------------------------
                # 2.  Installment + Journal Entry Logic
                # ----------------------------------------------------------------
                line_date_raw = get_v('Scheme Line/Date')
                line_amount   = get_v('Scheme Line/Amount')

                # FIX 1: Always parse the date – handles 'DD-MM-YYYY' strings and
                #         native date/datetime objects returned by openpyxl.
                line_date = parse_date(line_date_raw)

                if scheme_id and (line_date or line_amount):
                    journal_name = get_v('Scheme Line/Journal')
                    journal      = self._find_m2o('account.journal', journal_name)

                    excel_move_id   = self._find_m2o('account.move', get_v('Scheme Line/Move'))
                    generated_move_id = False

                    # FIX 2: Proper double-entry journal entry
                    #   DEBIT  → Bank / Cash account  (money received)
                    #   CREDIT → Scheme Liability / Receivable account
                    if not excel_move_id and journal and line_amount:
                        try:
                            # Debit side: bank / cash account linked to the journal
                            debit_account_id = journal.default_account_id.id

                            # Credit side: scheme liability account.
                            # Priority: account code 210100 (customise as needed)
                            # Fallback: outstanding receipts account of the journal
                            liability_account = request.env['account.account'].search(
                                [('code', '=', '210100')], limit=1
                            )
                            if not liability_account:
                                liability_account = journal.payment_credit_account_id  # Odoo 16/17

                            credit_account_id = (
                                liability_account.id
                                if liability_account
                                else debit_account_id        # last resort (keeps balanced)
                            )

                            if debit_account_id:
                                move_vals = {
                                    'journal_id': journal.id,
                                    'date': line_date or fields.Date.today(),
                                    'ref': f"Scheme Payment: {last_valid_ticket}",
                                    'move_type': 'entry',
                                    'line_ids': [
                                        # Debit: Bank/Cash – money comes IN
                                        (0, 0, {
                                            'name': f'Scheme Payment – {last_valid_ticket}',
                                            'account_id': debit_account_id,
                                            'debit': float(line_amount),
                                            'credit': 0.0,
                                        }),
                                        # Credit: Scheme Liability – obligation recorded
                                        (0, 0, {
                                            'name': f'Scheme Liability – {last_valid_ticket}',
                                            'account_id': credit_account_id,
                                            'debit': 0.0,
                                            'credit': float(line_amount),
                                        }),
                                    ],
                                }
                                new_move = request.env['account.move'].create(move_vals)
                                new_move.action_post()
                                generated_move_id = new_move.id
                                _logger.info(
                                    "Row %s: Journal entry created (id=%s) for ticket %s – amount %.2f",
                                    row_idx, generated_move_id, last_valid_ticket, float(line_amount)
                                )
                        except Exception as move_err:
                            _logger.error("Row %s: Move creation failed – %s", row_idx, str(move_err))

                    # Create the installment line
                    request.env['jewellery.scheme.installment'].create({
                        'enrollment_id':  scheme_id,
                        'date':           line_date,          # parsed date object
                        'amount':         line_amount,
                        'journal_id':     journal.id if journal else False,
                        'state':          str(get_v('Scheme Line/State')).lower() if get_v('Scheme Line/State') else 'draft',
                        'move_id':        excel_move_id.id if excel_move_id else generated_move_id,
                        'transaction_id': get_v('Scheme Line/Transaction ID'),
                    })
                    count_lines += 1

            request.env.cr.commit()
            return (
                f"<h1>Import Success</h1>"
                f"<p>Enrollments: {count_scheme} | Installments: {count_lines}</p>"
            )

        except Exception as e:
            request.env.cr.rollback()
            _logger.error("Import Failure: %s", str(e))
            return f"<h1>Error</h1><p>{str(e)}</p>"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_m2o(self, model, name):
        if not name:
            return False
        return request.env[model].search([('name', '=', str(name).strip())], limit=1)

    def _find_or_create_partner(self, name, phone):
        if not name:
            return False
        partner = request.env['res.partner'].search([('name', '=', name)], limit=1)
        if not partner:
            partner = request.env['res.partner'].create({
                'name': name,
                'phone': str(phone) if phone else False,
                'customer_rank': 1,
            })
        return partner
