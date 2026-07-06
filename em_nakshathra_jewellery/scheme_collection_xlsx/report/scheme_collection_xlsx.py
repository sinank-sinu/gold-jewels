# -*- coding: utf-8 -*-
from odoo import models

class SchemeCollectionXlsx(models.AbstractModel):
    _name = 'report.scheme_collection_xlsx.scheme_collection_xlsx'
    _inherit = 'report.report_xlsx.abstract'
    _description = 'Scheme Collection Report XLSX Engine'

    def generate_xlsx_report(self, workbook, data, wizard_record):
        sheet = workbook.add_worksheet('Scheme Collection Report')
        
  
        grey_fill_color = '#D9D9D9'  
        
        title_format = workbook.add_format({
            'bold': True, 
            'font_size': 16, 
            'font_name': 'Arial'
        })
        
        filter_label_format = workbook.add_format({
            'bold': True,
            'font_size': 11, 
            'font_name': 'Arial',
            'bg_color': grey_fill_color,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        filter_value_format = workbook.add_format({
            'font_size': 11, 
            'font_name': 'Arial', 
            'num_format': 'yyyy-mm-dd',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })
        
        header_format = workbook.add_format({
            'bold': True,
            'font_size': 11, 
            'font_name': 'Arial', 
            'bg_color': grey_fill_color,
            'align': 'center', 
            'valign': 'vcenter',
            'border': 1
        })
        
        data_format = workbook.add_format({
            'font_size': 11, 
            'font_name': 'Arial',
            'border': 1
        })
        amount_format = workbook.add_format({
            'font_size': 11, 
            'font_name': 'Arial', 
            'num_format': '#,##0.00',
            'border': 1
        })

        sheet.set_column('A:A', 16)  # Date
        sheet.set_column('B:B', 35)  # Scheme Name
        sheet.set_column('C:C', 28)  # Customer Name
        sheet.set_column('D:D', 22)  # Salesman
        sheet.set_column('E:E', 18)  # Branch
        sheet.set_column('F:F', 45)  # No of installment(how-many-th installment)
        sheet.set_column('G:G', 25)  # Installment month
        sheet.set_column('H:H', 18)  # Installment Amt

        sheet.set_row(1, 20)  # Row 2 (From Date)
        sheet.set_row(2, 20)  # Row 3 (To Date)
        sheet.set_row(3, 15)  # Row 4 (Line Gap)
        sheet.set_row(4, 25)  # Row 5 (Table Header Row height)

        
        sheet.write('A1', 'Scheme Collection Report', title_format)
        
        date_from = data.get('date_from') or (wizard_record.start_date if wizard_record else False)
        date_to = data.get('date_to') or (wizard_record.end_date if wizard_record else False)
        
        sheet.write(1, 0, 'From Date', filter_label_format)
        sheet.write(1, 1, date_from or '', filter_value_format)
            
        sheet.write(2, 0, 'To Date', filter_label_format)
        sheet.write(2, 1, date_to or '', filter_value_format)

       
        headers = [
            'Date', 
            'Scheme', 
            'Customer Name', 
            'Salesman', 
            'Branch', 
            'No of installment', 
            'Installment month', 
            'Installment Amt'
        ]
        
        for col_num, header_title in enumerate(headers):
            sheet.write(4, col_num, header_title, header_format)

        
        domain = []
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        if data.get('branch_ids'):
            domain.append(('enrollment_id.branch_id', 'in', data.get('branch_ids')))
        if data.get('partner_ids'):
            domain.append(('enrollment_id.partner_id', 'in', data.get('partner_ids')))
            
        installment_lines = self.env['jewellery.scheme.installment'].search(domain, order='date asc, id asc')

        row = 5
        for line in installment_lines:
            sheet.write(row, 0, line.date or '', filter_value_format)
            
            parent_enrollment = line.enrollment_id 
            scheme_name = parent_enrollment.name if parent_enrollment and parent_enrollment.name else ''
            customer_name = parent_enrollment.partner_id.name if parent_enrollment and parent_enrollment.partner_id else ''
            branch_name = parent_enrollment.branch_id.name if parent_enrollment and parent_enrollment.branch_id else ''
            
            sheet.write(row, 1, scheme_name, data_format)       
            sheet.write(row, 2, customer_name, data_format)     
            sheet.write(row, 3, line.create_uid.name or '', data_format) 
            sheet.write(row, 4, branch_name, data_format)       
            
            installment_nth_string = ""
            if parent_enrollment:
                all_scheme_lines = parent_enrollment.scheme_line_ids.sorted(key=lambda l: (l.date or '', l.id))
                
                if line in all_scheme_lines:
                    nth_count = list(all_scheme_lines).index(line) + 1
                    
                    if nth_count % 10 == 1 and nth_count % 100 != 11:
                        suffix = "st"
                    elif nth_count % 10 == 2 and nth_count % 100 != 12:
                        suffix = "nd"
                    elif nth_count % 10 == 3 and nth_count % 100 != 13:
                        suffix = "rd"
                    else:
                        suffix = "th"
                    
                    installment_nth_string = f"{nth_count}{suffix} Installment"
            
            sheet.write(row, 5, installment_nth_string, data_format) 
            
            installment_month = line.date.strftime('%B') if line.date else ''
            sheet.write(row, 6, installment_month, data_format)     
            sheet.write(row, 7, line.amount or 0.00, amount_format)  
            
            row += 1
