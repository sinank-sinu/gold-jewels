import openpyxl
import logging
import os
from odoo import http
from odoo.http import request
from odoo.modules.module import get_module_resource

_logger = logging.getLogger(__name__)

class EmployeeImportController(http.Controller):

    @http.route('/import/employees/now', type='http', auth='user')
    def trigger_import(self, **kwargs):
        file_name = 'Employee Master(hr.employee) (3).xlsx'
        file_path = get_module_resource('custom_hr_import', 'data', file_name)
        
        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"

        try:
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            sheet = workbook.active
            
            h_map = {str(sheet.cell(row=1, column=i).value).strip(): i 
                     for i in range(1, sheet.max_column + 1) 
                     if sheet.cell(row=1, column=i).value}

            count = 0
            skipped = 0
            last_valid_dept = False
            last_valid_company = False

            for row_idx in range(2, sheet.max_row + 1):
                def get_v(col_name):
                    idx = h_map.get(col_name)
                    return sheet.cell(row=row_idx, column=idx).value if idx else False

                # Merged cell carry-forward
                current_dept = get_v('Department')
                if current_dept: last_valid_dept = str(current_dept).strip()
                
                current_company = get_v('Company')
                if current_company: last_valid_company = str(current_company).strip()

                emp_name = str(get_v('Employee Name')).strip() if get_v('Employee Name') else False
                if not emp_name:
                    continue
                
                if request.env['hr.employee'].search([('name', '=', emp_name)], limit=1):
                    skipped += 1
                    continue

                # 1. Create/Find the Partner (Standard practice for HR bank accounts)
                partner_id = self._get_or_create_partner(emp_name)

                # 2. Prepare Vals
                vals = {
                    'name': emp_name,
                    'work_email': get_v('Work Email'),
                    'work_phone': get_v('Work Phone'),
                    'job_id': request.env['hr.job'].search([('name', '=', get_v('Job Position'))], limit=1).id,
                    'company_id': request.env['res.company'].search([('name', '=', last_valid_company)], limit=1).id or request.env.company.id,
                    'department_id': request.env['hr.department'].search([('name', '=', last_valid_dept)], limit=1).id,
                    'parent_id': request.env['hr.employee'].search([('name', '=', get_v('Manager'))], limit=1).id,
                    'emergency_contact': get_v('Contact Name'),
                    'emergency_phone': get_v('Contact Phone'),
                    'bank_account_id': self._get_or_create_bank_account(get_v('Bank Account Number'), partner_id),
                }

                salary = get_v('Salary')
                
                try:
                    new_emp = request.env['hr.employee'].create(vals)
                    if salary:
                        self._create_contract(new_emp, salary, get_v('Joining Date'), get_v('Expiry Date'))
                    count += 1
                except Exception as row_err:
                    _logger.error(f"Failed to create {emp_name}: {str(row_err)}")
                    # If the main transaction fails, we want to skip to next row
                    request.env.cr.rollback() 

            request.env.cr.commit()
            return f"<h1>Import Finished</h1><p>Created: {count} | Skipped: {skipped}</p>"

        except Exception as e:
            _logger.error(f"Import Failed: {str(e)}")
            return f"<h1>Error</h1><p>{str(e)}</p>"

    def _get_or_create_partner(self, name):
        """ Creates a private partner record for the employee """
        partner = request.env['res.partner'].search([('name', '=', name), ('type', '=', 'private')], limit=1)
        if not partner:
            partner = request.env['res.partner'].create({
                'name': name,
            })
        return partner.id

    def _get_or_create_bank_account(self, acc_number, partner_id):
        """ Finds or creates a bank account linked to the required partner_id """
        if not acc_number or str(acc_number).lower() in ['none', '']:
            return False

        acc_number = str(acc_number).strip()
        bank_rec = request.env['res.partner.bank'].search([('acc_number', '=', acc_number)], limit=1)
        
        if bank_rec:
            return bank_rec.id
        
        try:
            # We pass partner_id here to satisfy the NOT NULL constraint seen in your error log
            new_bank = request.env['res.partner.bank'].create({
                'acc_number': acc_number,
                'partner_id': partner_id,
            })
            return new_bank.id
        except Exception as e:
            _logger.warning(f"Bank Account creation failed: {e}")
            return False

    def _create_contract(self, employee, wage, start_date, expiry_date):
        try:
            request.env['hr.contract'].create({
                'name': f"Contract - {employee.name}",
                'employee_id': employee.id,
                'wage': float(wage or 0),
                'date_start': start_date,
                'date_end': expiry_date,
                'state': 'open',
            })
        except Exception as e:
            _logger.warning(f"Contract error for {employee.name}: {e}")


