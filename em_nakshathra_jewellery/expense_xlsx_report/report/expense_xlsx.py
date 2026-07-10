from odoo import models

class ExpenseXlsx(models.AbstractModel):
    _name = 'report.expense_xlsx_report.expense_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, wizards):
        for wizard in wizards:
            sheet = workbook.add_worksheet('Expense Report')
            bold = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#D3D3D3', 'border': 1})
            date_format = workbook.add_format({'num_format': 'yyyy-mm-dd', 'border': 1})
            border = workbook.add_format({'border': 1})
            money = workbook.add_format({'num_format': '#,##0.00', 'border': 1})

            headers = ['Branch', 'Date', 'Journal Entry', 'Partner', 'Reference', 'Label', 'Account', 'Amount']
            for col, header in enumerate(headers):
                sheet.write(0, col, header, bold)
            
            sheet.set_column(0, 0, 20)
            sheet.set_column(1, 1, 15)
            sheet.set_column(2, 2, 20)
            sheet.set_column(3, 3, 30)
            sheet.set_column(4, 4, 20)
            sheet.set_column(5, 5, 30)
            sheet.set_column(6, 6, 25)
            sheet.set_column(7, 7, 15)

            # =========================================================
            # PERFORMANCE OPTIMIZATION FOR LAKHS OF DATA
            # Bypassing the Odoo ORM layer entirely to achieve 
            # O(1) memory complexity in Python using fetchmany() 
            # and the fastest possible SQL execution time.
            # =========================================================
            # Check for hr_payslip schema to ensure cross-environment compatibility
            self.env.cr.execute("SELECT table_name FROM information_schema.tables WHERE table_name='hr_payslip'")
            has_payslip_table = bool(self.env.cr.fetchone())
            
            has_move_id = False
            if has_payslip_table:
                self.env.cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name='hr_payslip' AND column_name='move_id'")
                has_move_id = bool(self.env.cr.fetchone())

            partner_coalesce_parts = ["p.name", "exp_emp.name"]
            payslip_joins = ""

            if has_payslip_table:
                partner_coalesce_parts.insert(1, "e.name")
                if has_move_id:
                    payslip_joins = """
                    LEFT JOIN hr_payslip hs ON hs.move_id = m.id
                    LEFT JOIN hr_employee e ON hs.employee_id = e.id"""
                else:
                    payslip_joins = """
                    LEFT JOIN hr_payslip hs ON hs.number = m.ref
                    LEFT JOIN hr_employee e ON hs.employee_id = e.id"""
                    
            partner_coalesce = f"COALESCE({', '.join(partner_coalesce_parts)}) as partner_name"

            query = f"""
                SELECT 
                    b.name as branch_name,
                    l.date as date,
                    m.name as move_name,
                    {partner_coalesce},
                    m.ref as reference,
                    l.name as label,
                    a.name as account_name,
                    COALESCE(l.debit, 0.0) as amount
                FROM account_move_line l
                JOIN account_move m ON l.move_id = m.id
                JOIN account_account a ON l.account_id = a.id
                LEFT JOIN res_branch b ON l.branch_id = b.id
                LEFT JOIN res_partner p ON l.partner_id = p.id{payslip_joins}
                LEFT JOIN hr_expense he ON he.id = l.expense_id
                LEFT JOIN hr_employee exp_emp ON he.employee_id = exp_emp.id
                WHERE m.state = 'posted'
                  AND l.date >= %s
                  AND l.date <= %s
            """
            params = [wizard.date_from, wizard.date_to]
            
            if wizard.account_ids:
                query += " AND l.account_id IN %s"
                params.append(tuple(wizard.account_ids.ids))
            else:
                query += " AND a.account_type IN %s"
                params.append(('expense',))
                
            # Explicitly exclude Stock Input accounts regardless of database configuration
            # Note: account.name is a JSONB translated field in Odoo 16+, so we cast it to ::text
            query += " AND a.name::text NOT ILIKE %s"
            params.append('%Stock input%')
                
            if wizard.branch_ids:
                query += " AND l.branch_id IN %s"
                params.append(tuple(wizard.branch_ids.ids))

            query += " ORDER BY b.name ASC NULLS LAST, l.date ASC"
            
            self.env.cr.execute(query, params)

            row = 1
            while True:
                # Fetch rows in chunks of 5000 to prevent RAM exhaustion
                chunk = self.env.cr.fetchmany(5000)
                if not chunk:
                    break
                
                for data in chunk:
                    # In Odoo 16+, translated fields are returned as JSONB dicts in raw SQL.
                    # This helper extracts the string value safely.
                    def get_string(val):
                        if isinstance(val, dict):
                            return next(iter(val.values())) if val else ''
                        return val or ''

                    sheet.write(row, 0, get_string(data[0]), border)  # branch_name
                    sheet.write(row, 1, data[1], date_format)         # date
                    sheet.write(row, 2, get_string(data[2]), border)  # move_name
                    sheet.write(row, 3, get_string(data[3]), border)  # partner_name
                    sheet.write(row, 4, get_string(data[4]), border)  # reference
                    sheet.write(row, 5, get_string(data[5]), border)  # label
                    sheet.write(row, 6, get_string(data[6]), border)  # account_name
                    sheet.write(row, 7, data[7] or 0.0, money)        # amount
                    row += 1
