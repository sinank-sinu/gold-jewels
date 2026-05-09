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

            for row_idx in range(2, sheet.max_row + 1):
                def get_v(col_name):
                    idx = h_map.get(col_name)
                    return sheet.cell(row=row_idx, column=idx).value if idx else False

                emp_name = str(get_v('Employee Name')).strip() if get_v('Employee Name') else False
                work_email = str(get_v('Work Email')).strip() if get_v('Work Email') else False

                if not emp_name:
                    continue
                
                domain = [('name', '=', emp_name)] 
                # domain = [('work_email', '=', work_email)] if work_email else [('name', '=', emp_name)]
                existing_emp = request.env['hr.employee'].search(domain, limit=1)
                
                if existing_emp:
                    _logger.info(f"Employee {emp_name} already exists, skipping.")
                    skipped += 1
                    continue

                vals = {
                    'name': emp_name,
                    'work_email': work_email,
                    'work_phone': get_v('Work Phone'),
                    'job_id': request.env['hr.job'].search([('name', '=', get_v('Job Position'))], limit=1).id,
                    'bank_account_id': self._get_bank_account(get_v('Bank Account Number')),
                    'company_id': request.env['res.company'].search([('name', '=', get_v('Company'))], limit=1).id or request.env.company.id,
                    'department_id': request.env['hr.department'].search([('name', '=', get_v('Department'))], limit=1).id,
                    'parent_id': request.env['hr.employee'].search([('name', '=', get_v('Manager'))], limit=1).id,
                    'emergency_contact': get_v('Contact Name'),
                    'emergency_phone': get_v('Contact Phone'),
                    # If you have a custom joining date field on employee, use that here. 
                    # Note: create_date is a system field and usually can't be set manually this way.
                }

                salary = get_v('Salary')
                
                try:
                    new_emp = request.env['hr.employee'].create(vals)
                    _logger.info(f"Created Employee: {emp_name}")
                    
                    if salary:
                        # Passing Expiry Date to the contract helper
                        self._create_contract(
                            new_emp, 
                            salary, 
                            get_v('Joining Date'), 
                            get_v('Expiry Date'), 
                            get_v('Employee Type')
                        )
                        
                    count += 1
                except Exception as row_err:
                    _logger.error(f"Failed to create {emp_name}: {str(row_err)}")

            request.env.cr.commit()
            return f"<h1>Import Finished</h1><p>Successfully imported: {count}</p><p>Skipped: {skipped}</p>"

        except Exception as e:
            _logger.error(f"Import Failed: {str(e)}")
            return f"<h1>Error</h1><p>{str(e)}</p>"

    def _get_bank_account(self, acc_number):
        if not acc_number:
            return False
        res_partner_bank = request.env['res.partner.bank'].search([('acc_number', '=', str(acc_number))], limit=1)
        return res_partner_bank.id if res_partner_bank else False

    # Updated signature to accept expiry_date and emp_type
    def _create_contract(self, employee, wage, start_date, expiry_date, emp_type):
        """ Helper to create a contract with Start and End (Expiry) dates """
        try:
            request.env['hr.contract'].create({
                'name': f"Contract - {employee.name}",
                'employee_id': employee.id,
                'wage': float(wage or 0),
                'date_start': start_date,
                'date_end': expiry_date, # This maps to 'Expiry Date'
                'state': 'open',
                # You could also map emp_type to a contract_type_id if needed
            })
        except Exception as e:
            _logger.warning(f"Could not create contract for {employee.name}: {str(e)}")



