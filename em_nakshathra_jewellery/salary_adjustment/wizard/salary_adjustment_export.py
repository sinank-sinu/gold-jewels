import base64
import csv
import io
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SalaryAdjustmentExportWizard(models.TransientModel):
    _name = 'salary.adjustment.export.wizard'
    _description = 'Salary Adjustment Export Wizard'

    salary_adjustment_id = fields.Many2one(
        'salary.adjustment', 
        string='Salary Adjustment Sheet', 
        required=True, 
        default=lambda self: self.env.context.get('active_id')
    )
    country = fields.Selection([
        ('uae', 'UAE (WPS SIF)'),
        ('ksa', 'Saudi Arabia (Mudad CSV)'),
        ('qat', 'Qatar (WPS CSV)'),
        ('omn', 'Oman (CBO CSV)'),
        ('bhr', 'Bahrain (LMRA CSV)'),
        ('kwt', 'Kuwait (MGRP SIF)'),
        ('mys_epf', 'Malaysia (EPF Borang A TXT)'),
        ('mys_socso', 'Malaysia (SOCSO Borang 8A TXT)'),
        ('mys_pcb', 'Malaysia (PCB CP39 TXT)'),
        ('mys_bank', 'Malaysia (Bank Transfer CSV)')
    ], string='Export Format', required=True, default='uae')

    file_name = fields.Char(string='File Name', readonly=True)
    file_data = fields.Binary(string='File Data', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done')
    ], string='State', default='draft')

    def action_export(self):
        self.ensure_one()
        sheet = self.salary_adjustment_id
        if not sheet.line_ids:
            raise UserError(_("There are no adjustment lines in this sheet to export."))

        company = sheet.company_id
        now = datetime.now()
        date_str = now.strftime('%Y%m%d')
        time_str = now.strftime('%H%M')
        
        start_date = sheet.date_start or fields.Date.today()
        end_date = sheet.date_end or fields.Date.today()
        salary_month_mmyyyy = start_date.strftime('%m%Y')
        salary_month_yyyymm = start_date.strftime('%Y-%m')

        file_content = ""
        extension = "csv"

        # Generate formats
        if self.country == 'uae':
            # UAE WPS SIF format
            extension = "sif"
            scr_est_id = (company.mol_est_id or '1234567890123')[:13].rjust(13, '0')
            scr_bank_code = (company.company_bank_code or '999999999')[:9].rjust(9, '0')
            
            # Prepare EDR rows
            edr_rows = []
            total_net = 0.0
            for line in sheet.line_ids:
                emp = line.employee_id
                bank = emp.bank_account_id
                
                basic = line.basic_wage
                net = line.net_wage
                allowances = line.allowance
                deductions = line.deduction
                total_net += net

                emp_card = (emp.labor_card_no or emp.national_id or '00000000000000')[:14].rjust(14, '0')
                emp_routing = (bank.routing_code or '000000000')[:9].rjust(9, '0')
                emp_iban = (bank.acc_number or 'AE000000000000000000000')
                days_paid = (end_date - start_date).days + 1

                edr_line = f"EDR,{emp_card},{emp_routing},{emp_iban},{start_date.strftime('%Y-%m-%d')},{end_date.strftime('%Y-%m-%d')},{days_paid},{basic:.2f},{allowances:.2f},{deductions:.2f}"
                edr_rows.append(edr_line)

            # Build Header (SCR)
            scr_line = f"SCR,{scr_est_id},{scr_bank_code},{now.strftime('%Y-%m-%d')},{time_str},{salary_month_mmyyyy},{len(edr_rows)},{total_net:.2f},AED"
            file_content = scr_line + "\n" + "\n".join(edr_rows) + "\n"

        elif self.country == 'ksa':
            # Saudi Arabia Mudad CSV
            extension = "csv"
            output = io.StringIO()
            writer = csv.writer(output, delimiter=',')
            
            est_id = company.mol_est_id or '1234567890'
            employer_iban = company.partner_id.bank_ids and company.partner_id.bank_ids[0].acc_number or 'SA0000000000000000000000'
            total_net = sum(sheet.line_ids.mapped('net_wage') or [0.0])
            
            # Header row
            writer.writerow([est_id, employer_iban, salary_month_yyyymm, now.strftime('%Y-%m-%d %H:%M:%S'), len(sheet.line_ids), f"{total_net:.2f}"])
            
            # Employee details
            for line in sheet.line_ids:
                emp = line.employee_id
                bank = emp.bank_account_id
                
                basic = line.basic_wage
                net = line.net_wage
                allowances = line.allowance
                deductions = line.deduction
                
                writer.writerow([
                    emp.name,
                    emp.national_id or '0000000000',
                    bank.acc_number or 'SA0000000000000000000000',
                    f"{net:.2f}",
                    f"{basic:.2f}",
                    f"{allowances:.2f}",
                    "0.00",
                    f"{deductions:.2f}"
                ])
            file_content = output.getvalue()

        elif self.country == 'qat':
            # Qatar QCB CSV
            extension = "csv"
            output = io.StringIO()
            writer = csv.writer(output, delimiter=',')
            
            est_id = company.mol_est_id or '1234567890'
            total_net = sum(sheet.line_ids.mapped('net_wage') or [0.0])
            
            # Row 1: Company Info
            writer.writerow([est_id, now.strftime('%Y-%m-%d'), salary_month_mmyyyy, len(sheet.line_ids), f"{total_net:.2f}"])
            
            # Row 2 & 3: Blank/headers
            writer.writerow([])
            writer.writerow(['Employee QID', 'Employee Name', 'Employee IBAN', 'Basic Salary', 'Other Allowances', 'Deductions', 'Deduction Reason Code'])
            
            for line in sheet.line_ids:
                emp = line.employee_id
                bank = emp.bank_account_id
                
                basic = line.basic_wage
                allowances = line.allowance
                deductions = line.deduction
                
                drc_code = "/DRC/01" if deductions > 0 else ""
                
                writer.writerow([
                    emp.national_id or '00000000000',
                    emp.name,
                    bank.acc_number or 'QA000000000000000000000',
                    f"{basic:.2f}",
                    f"{allowances:.2f}",
                    f"{deductions:.2f}",
                    drc_code
                ])
            file_content = output.getvalue()

        elif self.country == 'omn':
            # Oman Central Bank CSV
            extension = "csv"
            output = io.StringIO()
            writer = csv.writer(output, delimiter=',')
            
            cr_num = company.cr_number or '1234567'
            mol_id = company.mol_est_id or '1234567890'
            total_net = sum(sheet.line_ids.mapped('net_wage') or [0.0])
            
            # Control Record
            writer.writerow([cr_num, mol_id, now.strftime('%Y-%m-%d'), salary_month_yyyymm, len(sheet.line_ids), f"{total_net:.2f}"])
            
            # Employee Records
            for line in sheet.line_ids:
                emp = line.employee_id
                bank = emp.bank_account_id
                
                basic = line.basic_wage
                allowances = line.allowance
                deductions = line.deduction
                net = line.net_wage
                
                writer.writerow([
                    emp.national_id or emp.labor_card_no or '00000000',
                    emp.name,
                    bank.acc_number or 'OM00000000000000000000',
                    f"{basic:.2f}",
                    f"{allowances:.2f}",
                    f"{deductions:.2f}",
                    f"{net:.2f}"
                ])
            file_content = output.getvalue()

        elif self.country == 'bhr':
            # Bahrain LMRA CSV
            extension = "csv"
            output = io.StringIO()
            writer = csv.writer(output, delimiter=',')
            
            cr_num = company.cr_number or '1234567'
            bank_id = company.company_bank_code or '999'
            total_net = sum(sheet.line_ids.mapped('net_wage') or [0.0])
            
            # Header
            writer.writerow([cr_num, bank_id, now.strftime('%Y-%m-%d'), f"{total_net:.2f}", len(sheet.line_ids)])
            
            # Details
            for line in sheet.line_ids:
                emp = line.employee_id
                bank = emp.bank_account_id
                
                basic = line.basic_wage
                allowances = line.allowance
                deductions = line.deduction
                net = line.net_wage
                
                writer.writerow([
                    emp.national_id or '000000000',
                    emp.name,
                    bank.acc_number or 'BH00000000000000000000',
                    f"{basic:.2f}",
                    f"{allowances:.2f}",
                    "0.00",
                    f"{deductions:.2f}",
                    f"{net:.2f}"
                ])
            file_content = output.getvalue()

        elif self.country == 'kwt':
            # Kuwait MGRP SIF format
            extension = "sif"
            emp_civil_id = company.employer_civil_id or '123456789012'
            total_net = sum(sheet.line_ids.mapped('net_wage') or [0.0])
            
            # Header
            header = f"MGRP,{emp_civil_id},{now.strftime('%d%m%y')},001"
            
            # Detail Records
            detail_lines = []
            for line in sheet.line_ids:
                emp = line.employee_id
                bank = emp.bank_account_id
                
                basic = line.basic_wage
                allowances = line.allowance
                deductions = line.deduction
                net = line.net_wage
                
                detail_lines.append(f"EREC,{emp.national_id or '000000000000'},{bank.acc_number or 'KW000000000000000000000000'},{basic:.2f},{allowances:.2f},{deductions:.2f},{net:.2f}")
            
            # Trailer
            trailer = f"MTOT,{len(sheet.line_ids)},{total_net:.2f}"
            file_content = header + "\n" + "\n".join(detail_lines) + "\n" + trailer + "\n"

        elif self.country == 'mys_epf':
            # Malaysia EPF Borang A format (TXT)
            extension = "txt"
            lines = []
            lines.append("EPF Borang A Submission File")
            lines.append(f"Employer Name: {company.name}")
            lines.append(f"Employer Registration No: {company.company_registry or ''}")
            lines.append(f"Salary Month: {salary_month_mmyyyy}")
            lines.append("-" * 80)
            
            for line in sheet.line_ids:
                emp = line.employee_id
                basic = line.basic_wage
                emp_epf = basic * 0.11
                empr_epf = basic * 0.13
                
                lines.append(f"Employee: {emp.name:<30} | EPF No: {emp.epf_no or 'N/A':<10} | IC/Passport: {emp.national_id or 'N/A':<15} | Wage: {basic:>8.2f} | Employee EPF: {emp_epf:>8.2f} | Employer EPF: {empr_epf:>8.2f}")
            
            file_content = "\n".join(lines) + "\n"

        elif self.country == 'mys_socso':
            # Malaysia SOCSO Borang 8A format (TXT)
            extension = "txt"
            lines = []
            lines.append("SOCSO Borang 8A Submission File")
            lines.append(f"Employer Name: {company.name}")
            lines.append(f"Employer Registration No: {company.company_registry or ''}")
            lines.append(f"Salary Month: {salary_month_mmyyyy}")
            lines.append("-" * 80)
            
            for line in sheet.line_ids:
                emp = line.employee_id
                basic = line.basic_wage
                emp_socso = basic * 0.005
                empr_socso = basic * 0.0175
                
                lines.append(f"Employee: {emp.name:<30} | SOCSO No: {emp.socso_no or 'N/A':<10} | IC/Passport: {emp.national_id or 'N/A':<15} | Wage: {basic:>8.2f} | Employee SOCSO: {emp_socso:>8.2f} | Employer SOCSO: {empr_socso:>8.2f}")
            
            file_content = "\n".join(lines) + "\n"

        elif self.country == 'mys_pcb':
            # Malaysia PCB CP39 format (TXT)
            extension = "txt"
            lines = []
            lines.append("LHDN CP39 PCB Tax Submission File")
            lines.append(f"Employer Name: {company.name}")
            lines.append(f"Salary Month: {salary_month_mmyyyy}")
            lines.append("-" * 80)
            
            for line in sheet.line_ids:
                emp = line.employee_id
                pcb = line.deduction
                
                lines.append(f"Employee: {emp.name:<30} | Tax No (TIN): {emp.tax_no or 'N/A':<12} | IC/Passport: {emp.national_id or 'N/A':<15} | PCB Deducted: {pcb:>8.2f}")
            
            file_content = "\n".join(lines) + "\n"

        elif self.country == 'mys_bank':
            # Malaysia Bank Transfer CSV format
            extension = "csv"
            output = io.StringIO()
            writer = csv.writer(output, delimiter=',')
            
            writer.writerow(['Employee Name', 'Bank Name', 'Account Number', 'Net Salary', 'Reference'])
            for line in sheet.line_ids:
                emp = line.employee_id
                bank = emp.bank_account_id
                net = line.net_wage
                
                writer.writerow([
                    emp.name,
                    bank.bank_id.name if bank.bank_id else 'MALAYSIAN BANK',
                    bank.acc_number or '000000000000',
                    f"{net:.2f}",
                    f"Salary {start_date.strftime('%B %Y')}"
                ])
            file_content = output.getvalue()

        # Save generated file directly to the sheet
        sheet.write({
            'file_name': f"salary_export_{self.country}_{date_str}_{time_str}.{extension}",
            'file_data': base64.b64encode(file_content.encode('utf-8')),
        })

        # Save generated file in wizard for download
        self.write({
            'file_name': f"salary_export_{self.country}_{date_str}_{time_str}.{extension}",
            'file_data': base64.b64encode(file_content.encode('utf-8')),
            'state': 'done'
        })

        # Reopen wizard form to let user download
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'salary.adjustment.export.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
