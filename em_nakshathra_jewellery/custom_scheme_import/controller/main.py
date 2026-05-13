import openpyxl
import logging
import os
from odoo import http, fields
from odoo.http import request
from odoo.modules.module import get_module_resource

_logger = logging.getLogger(__name__)

class SchemeImportController(http.Controller):

    @http.route('/import/schemes/now', type='http', auth='user')
    def trigger_scheme_import(self, **kwargs):
        file_name = 'Scheme_Import.xlsx'
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
                def get_v(col_name):
                    idx = h_map.get(col_name)
                    return sheet.cell(row=row_idx, column=idx).value if idx else False

                current_ticket_raw = get_v('Ticket Number')
                if current_ticket_raw:
                    last_valid_ticket = str(current_ticket_raw).strip()
                
                if not last_valid_ticket:
                    continue

                # --- 1. Enrollment Logic ---
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

                # --- 2. Dynamic Move & Installment Logic ---
                line_date = get_v('Scheme Line/Date')
                line_amount = get_v('Scheme Line/Amount')

                if scheme_id and (line_date or line_amount):
                    # Fetch Journal dynamically from report column
                    journal_name = get_v('Scheme Line/Journal')
                    journal = self._find_m2o('account.journal', journal_name)
                    
                    excel_move_id = self._find_m2o('account.move', get_v('Scheme Line/Move'))
                    generated_move_id = False

                    # Create Move based on the Journal found
                    if not excel_move_id and journal and line_amount:
                        # Use the default account assigned to the Journal (e.g., the Bank account)
                        dynamic_account_id = journal.default_account_id.id
                        
                        if dynamic_account_id:
                            try:
                                move_vals = {
                                    'journal_id': journal.id,
                                    'date': line_date or fields.Date.today(),
                                    'ref': f"Scheme: {last_valid_ticket}",
                                    'move_type': 'entry',
                                    'line_ids': [
                                        (0, 0, {
                                            'name': 'Scheme Payment',
                                            'account_id': dynamic_account_id,
                                            'debit': float(line_amount),
                                            'credit': 0.0,
                                        }),
                                        (0, 0, {
                                            'name': 'Scheme Liability',
                                            'account_id': dynamic_account_id,
                                            'debit': 0.0,
                                            'credit': float(line_amount),
                                        }),
                                    ],
                                }
                                new_move = request.env['account.move'].create(move_vals)
                                new_move.action_post()
                                generated_move_id = new_move.id
                            except Exception as move_err:
                                _logger.error(f"Row {row_idx}: Move creation failed - {str(move_err)}")

                    # Final Installment Creation
                    request.env['jewellery.scheme.installment'].create({
                        'enrollment_id': scheme_id,
                        'date': line_date,
                        'amount': line_amount,
                        'journal_id': journal.id if journal else False,
                        'state': str(get_v('Scheme Line/State')).lower() if get_v('Scheme Line/State') else 'draft',
                        'move_id': excel_move_id.id if excel_move_id else generated_move_id,
                        'transaction_id': get_v('Scheme Line/Transaction ID'),
                    })
                    count_lines += 1

            request.env.cr.commit()
            return f"<h1>Import Success</h1><p>Enrollments: {count_scheme} | Installments: {count_lines}</p>"

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Import Failure: {str(e)}")
            return f"<h1>Error</h1><p>{str(e)}</p>"

    def _find_m2o(self, model, name):
        if not name: return False
        return request.env[model].search([('name', '=', str(name).strip())], limit=1)

    def _find_or_create_partner(self, name, phone):
        if not name: return False
        partner = request.env['res.partner'].search([('name', '=', name)], limit=1)
        if not partner:
            partner = request.env['res.partner'].create({
                'name': name,
                'phone': str(phone) if phone else False,
                'customer_rank': 1,
            })
        return partner


# import openpyxl
# import logging
# import os
# from odoo import http, fields
# from odoo.http import request
# from odoo.modules.module import get_module_resource

# _logger = logging.getLogger(__name__)

# class SchemeImportController(http.Controller):

#     @http.route('/import/schemes/now', type='http', auth='user')
#     def trigger_scheme_import(self, **kwargs):
#         # Path to the specific Excel file
#         file_name = 'Scheme_Import.xlsx'
#         file_path = get_module_resource('custom_scheme_import', 'data', file_name)
        
#         if not file_path or not os.path.exists(file_path):
#             return f"<h1>Error</h1><p>File not found at {file_path}</p>"

#         try:
#             workbook = openpyxl.load_workbook(file_path, data_only=True)
#             sheet = workbook.active
            
#             # Map headers to column indices
#             h_map = {str(sheet.cell(row=1, column=i).value).strip(): i 
#                      for i in range(1, sheet.max_column + 1) 
#                      if sheet.cell(row=1, column=i).value}

#             last_valid_ticket = False
#             scheme_tracker = {} # Key: Ticket Number, Value: Scheme ID
#             count_scheme = 0
#             count_lines = 0

#             for row_idx in range(2, sheet.max_row + 1):
#                 def get_v(col_name):
#                     idx = h_map.get(col_name)
#                     return sheet.cell(row=row_idx, column=idx).value if idx else False

#                 # 1. Multi-line Logic: Track the Ticket Number across merged/blank rows
#                 current_ticket_raw = get_v('Ticket Number')
#                 if current_ticket_raw:
#                     last_valid_ticket = str(current_ticket_raw).strip()
                
#                 if not last_valid_ticket:
#                     continue

#                 # --- 2. Find or Create Parent Scheme (Enrollment) ---
#                 scheme_id = scheme_tracker.get(last_valid_ticket)
                
#                 if not scheme_id:
#                     existing_scheme = request.env['jewellery.scheme.enrollment'].search([
#                         ('ticket_number', '=', last_valid_ticket)
#                     ], limit=1)
                    
#                     if existing_scheme:
#                         scheme_id = existing_scheme.id
#                     else:
#                         partner_name = str(get_v('Partner')).strip() if get_v('Partner') else False
#                         if partner_name:
#                             partner = self._find_or_create_partner(partner_name, get_v('Phone'))
#                             scheme_vals = {
#                                 'name': get_v('Name'),
#                                 'ticket_number': last_valid_ticket,
#                                 'partner_id': partner.id,
#                                 'phone': get_v('Phone'),
#                                 'whatsapp_number': get_v('Whatsapp Number'),
#                                 'address': get_v('Address'),
#                                 'duration': get_v('Duration'),
#                                 'installment_amount': get_v('Installment Amount'),
#                                 'total_paid': get_v('Total Paid'),
#                                 'balance_amount': get_v('Balance Amount'),
#                                 'state': str(get_v('State')).lower() if get_v('State') else 'draft',
#                                 'active': True if str(get_v('Active')).lower() in ['true', '1', 'yes'] else False,
#                                 'nominee': get_v('Nominee'),
#                             }
#                             new_scheme = request.env['jewellery.scheme.enrollment'].create(scheme_vals)
#                             scheme_id = new_scheme.id
#                             count_scheme += 1
                    
#                     if scheme_id:
#                         scheme_tracker[last_valid_ticket] = scheme_id

#                 # --- 3. Create Installment & Specific Journal Entry ---
#                 line_date = get_v('Scheme Line/Date')
#                 line_amount = get_v('Scheme Line/Amount')

#                 if scheme_id and (line_date or line_amount):
#                     journal_id = self._find_m2o('account.journal', get_v('Scheme Line/Journal'))
#                     excel_move_id = self._find_m2o('account.move', get_v('Scheme Line/Move'))
#                     generated_move_id = False

#                     # Create move if it doesn't exist and we have enough data
#                     if not excel_move_id and journal_id and line_amount:
#                         try:
#                             # Search for Account 100201 as seen in Screenshot
#                             account = request.env['account.account'].search([('code', '=', '100201')], limit=1)
#                             # Fallback to journal default if code not found
#                             act_id = account.id if account else journal_id.default_account_id.id

#                             move_vals = {
#                                 'journal_id': journal_id.id,
#                                 'date': line_date or fields.Date.today(),
#                                 'ref': f"Scheme: {last_valid_ticket}",
#                                 'move_type': 'entry',
#                                 'line_ids': [
#                                     # Debit Line
#                                     (0, 0, {
#                                         'name': 'Scheme Payment',
#                                         'account_id': act_id,
#                                         'debit': float(line_amount),
#                                         'credit': 0.0,
#                                     }),
#                                     # Credit Line
#                                     (0, 0, {
#                                         'name': 'Scheme Liability',
#                                         'account_id': act_id,
#                                         'debit': 0.0,
#                                         'credit': float(line_amount),
#                                     }),
#                                 ],
#                             }
#                             new_move = request.env['account.move'].create(move_vals)
#                             new_move.action_post() # Set to 'Posted'
#                             generated_move_id = new_move.id
#                         except Exception as move_err:
#                             _logger.error(f"Move Creation Error on row {row_idx}: {str(move_err)}")

#                     # Final Installment Creation
#                     line_vals = {
#                         'enrollment_id': scheme_id,
#                         'date': line_date,
#                         'amount': line_amount,
#                         'journal_id': journal_id.id if journal_id else False,
#                         'state': str(get_v('Scheme Line/State')).lower() if get_v('Scheme Line/State') else 'draft',
#                         'move_id': excel_move_id or generated_move_id,
#                         'transaction_id': get_v('Scheme Line/Transaction ID'),
#                     }
#                     request.env['jewellery.scheme.installment'].create(line_vals)
#                     count_lines += 1

#             request.env.cr.commit()
#             return f"<h1>Import Success</h1><p>Enrollments: {count_scheme} | Installments: {count_lines}</p>"

#         except Exception as e:
#             request.env.cr.rollback()
#             _logger.error(f"Import Failure: {str(e)}")
#             return f"<h1>Error</h1><p>{str(e)}</p>"

#     def _find_m2o(self, model, name):
#         if not name: return False
#         return request.env[model].search([('name', '=', str(name).strip())], limit=1)

#     def _find_or_create_partner(self, name, phone):
#         if not name: return False
#         partner = request.env['res.partner'].search([('name', '=', name)], limit=1)
#         if not partner:
#             partner = request.env['res.partner'].create({
#                 'name': name,
#                 'phone': str(phone) if phone else False,
#                 'customer_rank': 1,
#             })
#         return partner
