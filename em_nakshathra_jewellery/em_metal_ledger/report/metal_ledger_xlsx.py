from odoo import models


class MetalLedgerXlsx(models.AbstractModel):
    _name = 'report.em_metal_ledger.metal_ledger_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, docs):

        sheet = workbook.add_worksheet('Metal Ledger')

        # =========================
        # Formats
        # =========================
        header_format = workbook.add_format({
            'bold': True,
            'border': 1,
            'align': 'center'
        })

        text_format = workbook.add_format({'border': 1})
        number_format = workbook.add_format({
            'border': 1,
            'num_format': '0.000'
        })
        bold_format = workbook.add_format({
            'bold': True,
            'border': 1,
            'num_format': '0.000'
        })

        # =========================
        # Title
        # =========================
        sheet.merge_range('A1:M1', 'Metal Ledger Report', bold_format)

        # =========================
        # Headers
        # =========================
        headers = [
            '#', 'Date', 'Branch', 'Voucher / Ref', 'Partner', 'Type',
            'Metal', 'Metal Fine', 'MC Fine',
            'Fine Weight', 'Stock In', 'Stock Out', 'Balance Weight'
        ]

        for col, header in enumerate(headers):
            sheet.write(2, col, header, header_format)

        # =========================
        # Column Width
        # =========================
        sheet.set_column('A:A', 5)
        sheet.set_column('B:B', 12)
        sheet.set_column('C:C', 18)
        sheet.set_column('D:D', 20)
        sheet.set_column('E:E', 25)
        sheet.set_column('F:F', 12)
        sheet.set_column('G:G', 12)
        sheet.set_column('H:M', 15)

        # =========================
        # Detect Partner Filter
        # =========================
        partner_ids = list(set(docs.mapped('partner_id.id')))
        partner_filter = len(partner_ids) == 1

        # =========================
        # Sorting
        # =========================
        if partner_filter:
            # Partner-wise (needed for running balance)
            docs = docs.sorted(key=lambda r: (
                r.partner_id.id or 0,
                r.date or '',
                r.id
            ))
        else:
            # Pure date-wise
            docs = docs.sorted(key=lambda r: (
                r.date or '',
                r.id
            ))

        # =========================
        # Data Rows
        # =========================
        row = 3
        row_no = 1

        total_metal_fine = 0.0
        total_mc_fine = 0.0
        total_fine_weight = 0.0
        total_stock_in = 0.0
        total_stock_out = 0.0

        # Running balance variables
        current_partner = None
        running_balance = 0.0

        for rec in docs:

            # =========================
            # Balance Logic
            # =========================
            if partner_filter:
                # Running balance ONLY when single partner selected

                if rec.partner_id.id != current_partner:
                    current_partner = rec.partner_id.id

                    # First row
                    running_balance = rec.fine_weight or 0.0
                else:
                    if rec.transaction_type == 'purchase':
                        running_balance += rec.fine_weight or 0.0
                    elif rec.transaction_type == 'sale':
                        running_balance -= rec.fine_weight or 0.0
                    else:
                        running_balance += rec.fine_weight or 0.0

                balance_value = running_balance

            else:
                # Normal report → use stored balance
                balance_value = rec.balance_weight or 0.0

            # =========================
            # Write Data
            # =========================
            sheet.write(row, 0, row_no, text_format)
            sheet.write(row, 1, str(rec.date or ''), text_format)
            sheet.write(row, 2, rec.branch_id.name or '', text_format)
            sheet.write(row, 3, rec.voucher_name or '', text_format)
            sheet.write(row, 4, rec.partner_id.name if rec.partner_id else '', text_format)
            sheet.write(row, 5, (rec.transaction_type or '').capitalize(), text_format)
            sheet.write(row, 6, rec.metal_id.name or '', text_format)

            sheet.write(row, 7, rec.metal_fine, number_format)
            sheet.write(row, 8, rec.mc_fine, number_format)
            sheet.write(row, 9, rec.fine_weight, number_format)
            sheet.write(row, 10, rec.stock_in, number_format)
            sheet.write(row, 11, rec.stock_out, number_format)
            sheet.write(row, 12, balance_value, number_format)

            # =========================
            # Totals
            # =========================
            total_metal_fine += rec.metal_fine
            total_mc_fine += rec.mc_fine
            total_fine_weight += rec.fine_weight
            total_stock_in += rec.stock_in
            total_stock_out += rec.stock_out

            row += 1
            row_no += 1

        # =========================
        # Totals Row
        # =========================
        sheet.write(row, 0, '', bold_format)
        sheet.write(row, 1, '', bold_format)
        sheet.write(row, 2, '', bold_format)
        sheet.write(row, 3, '', bold_format)
        sheet.write(row, 4, '', bold_format)
        sheet.write(row, 5, 'Total', bold_format)
        sheet.write(row, 6, '', bold_format)
        sheet.write(row, 7, total_metal_fine, bold_format)
        sheet.write(row, 8, total_mc_fine, bold_format)
        sheet.write(row, 9, total_fine_weight, bold_format)
        sheet.write(row, 10, total_stock_in, bold_format)
        sheet.write(row, 11, total_stock_out, bold_format)

        # No total for balance
        sheet.write(row, 12, '', bold_format)