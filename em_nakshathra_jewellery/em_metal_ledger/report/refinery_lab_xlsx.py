from odoo import models

class RefineryLabXlsx(models.AbstractModel):
    _name = 'report.em_metal_ledger.refinery_lab_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, docs):

        sheet = workbook.add_worksheet('Refinery Lab')

        # =========================
        # Formats
        # =========================
        header_format = workbook.add_format({'bold': True, 'border': 1, 'align': 'center'})
        text_format = workbook.add_format({'border': 1})
        number_format = workbook.add_format({'border': 1, 'num_format': '0.000'})
        bold_format = workbook.add_format({'bold': True, 'border': 1, 'num_format': '0.000'})

        # =========================
        # Title
        # =========================
        sheet.merge_range('A1:N1', 'Refinery Lab Report', bold_format)

        # =========================
        # Headers
        # =========================
       
        headers = [
            'Date', 'Voucher Name', 'Branch', 'Refinery', 'Type', 'Issued Weight',
            'Net Weight', 'Purity', 'Lab Weight', 'Lab Purity(%)', 'UPD Fine Weight',  
            'Fine Weight', 'Fine GMS Price', 'Fine Amount', 'Balance', 
        ]

        for col, header in enumerate(headers):
            sheet.write(2, col, header, header_format)

        # =========================
        # Column Width
        # =========================
        sheet.set_column('A:A', 12)
        sheet.set_column('B:B', 20)
        sheet.set_column('C:D', 15)
        sheet.set_column('E:P', 15)
        # =========================
        # Filters
        # =========================
        partner_ids = data.get('partner_ids') if data else []

        if partner_ids:
            docs = docs.filtered(lambda r: r.refinery_id.id in partner_ids)

        partner_filter = len(partner_ids) == 1

        # =========================
        # Sorting
        # =========================
        if partner_filter:
            docs = docs.sorted(key=lambda r: (
                r.refinery_id.id or 0,
                r.date or '',
                r.id
            ))
        else:
            docs = docs.sorted(key=lambda r: (
                r.date or '',
                r.id
            ))

        # =========================
        # Data
        # =========================
        row = 3

        total_issued = 0.0
        total_net = 0.0
        total_lab_weight = 0.0
        total_upd_fine = 0.0
        total_fine = 0.0
        total_fine_amount = 0.0


        current_partner = None
        running_balance = 0.0

        for rec in docs:

            # =========================
            # Running Balance (MATCH MODEL LOGIC)
            # =========================
            if partner_filter:

                # New partner → reset
                if rec.refinery_id.id != current_partner:
                    current_partner = rec.refinery_id.id
                    running_balance = 0.0

                # Apply same logic as model
                if rec.type == 'issue':
                    running_balance -= rec.fine_weight or 0.0
                elif rec.type == 'receive':
                    running_balance += rec.fine_weight or 0.0

                balance_value = running_balance

            else:
                # Normal → use stored balance
                balance_value = rec.balance or 0.0

            # =========================
            # Write Data
            # =========================
            sheet.write(row, 0, str(rec.date or ''), text_format)
            sheet.write(row, 1, rec.voucher_name or '', text_format)
            sheet.write(row, 2, rec.branch_id.name or '', text_format)
            sheet.write(row, 3, rec.refinery_id.name or '', text_format)
            sheet.write(row, 4, (rec.type or '').capitalize(), text_format)

            sheet.write(row, 5, rec.issued_weight, number_format)
            sheet.write(row, 6, rec.net_weight, number_format)
            sheet.write(row, 7, rec.purity_id.name if rec.purity_id else '', text_format)

            sheet.write(row, 8, rec.lab_weight, number_format)
            sheet.write(row, 9, rec.lab_purity, number_format)
            sheet.write(row, 10, rec.lab_fine_weight, number_format)

            sheet.write(row, 11, rec.fine_weight, number_format)
            sheet.write(row, 12, rec.fine_gms_price, number_format)
            sheet.write(row, 13, rec.fine_amount, number_format)
            sheet.write(row, 14, balance_value, number_format)
            
            # =========================
            # Totals
            # =========================
            total_issued += rec.issued_weight
            total_net += rec.net_weight
            total_lab_weight += rec.lab_weight
            total_upd_fine += rec.lab_fine_weight
            total_fine += rec.fine_weight
            total_fine_amount += rec.fine_amount

            row += 1
        # =========================
        # Totals Row
        # =========================
        sheet.write(row, 0, '', bold_format)
        sheet.write(row, 1, '', bold_format)
        sheet.write(row, 2, '', bold_format)
        sheet.write(row, 2, '', bold_format)
        sheet.write(row, 4, 'Total', bold_format)
        sheet.write(row, 5, total_issued, bold_format)
        sheet.write(row, 6, total_net, bold_format)
        sheet.write(row, 7, '', bold_format)
        sheet.write(row, 8, total_lab_weight, bold_format)
        sheet.write(row, 9, '', bold_format)
        sheet.write(row, 10, total_upd_fine, bold_format)
        sheet.write(row, 11, total_fine, bold_format)
        sheet.write(row, 12, '', bold_format)
        sheet.write(row, 13, total_fine_amount, bold_format)
        sheet.write(row, 14, '', bold_format)
