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
    """Safely convert a value to float, return 0.0 on failure."""
    try:
        return float(value) if value not in (None, False, '') else 0.0
    except (TypeError, ValueError):
        return 0.0


class SchemeImportController(http.Controller):

    @http.route('/import/schemes/now', type='http', auth='user')
    def trigger_scheme_import(self, **kwargs):
        file_name = 'Jewellery_Scheme_Enrollment_Processed_v2.xlsx'
        file_path = get_module_resource('custom_scheme_import', 'data', file_name)

        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"

        errors = []

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

                def get_v(col_name, _row=row_idx):
                    idx = h_map.get(col_name)
                    return sheet.cell(row=_row, column=idx).value if idx else False

                # ── PER-ROW SAVEPOINT ──────────────────────────────────────────
                # If anything fails inside, we roll back only this row and
                # continue – the transaction itself stays healthy.
                try:
                    with request.env.cr.savepoint():

                        current_ticket_raw = get_v('Ticket Number')
                        if current_ticket_raw:
                            last_valid_ticket = str(current_ticket_raw).strip()

                        if not last_valid_ticket:
                            continue

                        # --------------------------------------------------------
                        # 1.  Enrollment Logic
                        # --------------------------------------------------------
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
                                    if not partner:
                                        raise ValueError(f"Could not find/create partner '{partner_name}'")

                                    active_raw = get_v('Active')
                                    is_active = str(active_raw).lower() in ['true', '1', 'yes'] if active_raw else False

                                    scheme_id = request.env['jewellery.scheme.enrollment'].create({
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
                                    }).id
                                    count_scheme += 1

                            if scheme_id:
                                scheme_tracker[last_valid_ticket] = scheme_id

                        # --------------------------------------------------------
                        # 2.  Installment + Journal Entry Logic
                        # --------------------------------------------------------
                        line_date_raw = get_v('Scheme Line/Date')
                        line_amount   = get_v('Scheme Line/Amount')
                        line_date     = parse_date(line_date_raw)
                        line_amount_f = safe_float(line_amount)

                        if not scheme_id or not (line_date or line_amount_f):
                            continue

                        journal_name      = get_v('Scheme Line/Journal')
                        journal           = self._find_m2o('account.journal', journal_name)
                        excel_move_id     = self._find_m2o('account.move', get_v('Scheme Line/Move'))
                        generated_move_id = False

                        if not excel_move_id and journal and line_amount_f:
                            # Inner savepoint so a bad journal entry does not
                            # kill the installment line creation either.
                            try:
                                with request.env.cr.savepoint():
                                    # Find Opening Balance Account
                                    opening_balance_account = request.env['account.account'].search([
                                        '|',
                                        ('name', 'ilike', 'opening balance'),
                                        ('account_type', '=', 'current_assets')
                                    ], limit=1)

                                    if not opening_balance_account:
                                        raise ValueError("Opening Balance account not found.")

                                    # Find Debtors Account
                                    debtors_account = request.env['account.account'].search([
                                        '|',
                                        ('name', 'ilike', 'debtor'),
                                        ('account_type', '=', 'asset_receivable')
                                    ], limit=1)
                                    
                                    if not debtors_account:
                                        # Fallback to partner's receivable account if available
                                        partner = request.env['res.partner'].browse(scheme_tracker.get(last_valid_ticket, request.env['jewellery.scheme.enrollment']).partner_id.id) if scheme_tracker.get(last_valid_ticket) else False
                                        if partner and hasattr(partner, 'property_account_receivable_id') and partner.property_account_receivable_id:
                                            debtors_account = partner.property_account_receivable_id
                                        else:
                                            raise ValueError("Debtors account not found.")

                                    scheme_record = request.env['jewellery.scheme.enrollment'].browse(scheme_id)
                                    line_partner_id = scheme_record.partner_id.id if scheme_record else False

                                    move_vals = {
                                        'journal_id': journal.id,
                                        'date': line_date or fields.Date.today(),
                                        'ref': f"Scheme Payment: {last_valid_ticket}",
                                        'move_type': 'entry',
                                        'line_ids': [
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
                                        ],
                                    }
                                    new_move = request.env['account.move'].create(move_vals)
                                    new_move.action_post()
                                    generated_move_id = new_move.id
                                    _logger.info(
                                        "Row %s: Journal entry created (id=%s) ticket=%s amount=%.2f",
                                        row_idx, generated_move_id, last_valid_ticket, line_amount_f
                                    )
                            except Exception as move_err:
                                _logger.warning(
                                    "Row %s: Journal entry skipped - %s", row_idx, str(move_err)
                                )
                                errors.append(f"Row {row_idx} move: {move_err}")
                                # installment line is still created below without a move

                        request.env['jewellery.scheme.installment'].create({
                            'enrollment_id':  scheme_id,
                            'date':           line_date or fields.Date.today(),
                            'amount':         line_amount_f,
                            'journal_id':     journal.id if journal else False,
                            'state':          str(get_v('Scheme Line/State')).lower() if get_v('Scheme Line/State') else 'draft',
                            'move_id':        excel_move_id.id if excel_move_id else generated_move_id,
                            'transaction_id': get_v('Scheme Line/Transaction ID'),
                        })
                        count_lines += 1

                except Exception as row_err:
                    _logger.error("Row %s skipped - %s", row_idx, str(row_err))
                    errors.append(f"Row {row_idx}: {row_err}")
                    if getattr(request.env.cr, 'closed', False):
                        errors.append("Database cursor closed unexpectedly. Stopping import.")
                        break
                    continue   # transaction is still alive; move to next row

                # Batch commit to avoid transaction timeout and memory bloat on large files
                if row_idx % 200 == 0:
                    try:
                        request.env.cr.commit()
                        if hasattr(request.env, 'invalidate_all'):
                            request.env.invalidate_all()
                        else:
                            request.env.clear()
                        _logger.info("Batch commit successful at row %s", row_idx)
                    except Exception as commit_err:
                        _logger.error("Batch commit failed at row %s: %s", row_idx, str(commit_err))
                        errors.append(f"Batch commit failed at row {row_idx}: {commit_err}")
                        break

            request.env.cr.commit()

            error_html = ""
            if errors:
                error_items = "".join(f"<li>{e}</li>" for e in errors)
                error_html = f"<h3>Skipped rows ({len(errors)}):</h3><ul>{error_items}</ul>"

            return (
                f"<h1>Import Complete</h1>"
                f"<p>Enrollments created: {count_scheme} | Installments created: {count_lines}</p>"
                f"{error_html}"
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
