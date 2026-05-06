from odoo import models

class RefineryMarginXlsx(models.AbstractModel):
    _name = 'report.em_metal_ledger.refinery_margin_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, docs):

        sheet = workbook.add_worksheet('Refinery Margin')

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
        sheet.merge_range('A1:P1', 'Refinery Margin Report', bold_format)

        # =========================
        # Headers
        # =========================
        headers = [
            'Date', 'Refinery Name', 'Type', 'Batches',
            'Gross Weight', 'Net Weight', 'Purity',
            'Expected Fine', 'Melting Loss', 'Lab Weight',
            'Refinery Issue Weight', 'Scrap Bar Fine',
            'Total Fine Weight', 'Balance', 'Amount', 'Fine Rate'
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
        # Partner Filter from Wizard
        # =========================
        partner_ids = data.get('partner_ids') if data else []
        partner_filter = len(partner_ids) == 1

        if partner_ids:
            docs = docs.filtered(lambda r: r.issue_id.refinery_partner_id.id in partner_ids)

        # =========================
        # Sorting
        # =========================
        if partner_filter:
            docs = docs.sorted(key=lambda r: (
                r.issue_id.refinery_partner_id.id or 0,
                r.date or '',
                r.id
            ))
        else:
            docs = docs.sorted(key=lambda r: (
                r.date or '',
                r.id
            ))

        # =========================
        # Data Section
        # =========================
        row = 3  # ✅ IMPORTANT

        total_gross = 0.0
        total_net = 0.0
        total_expected = 0.0
        total_loss = 0.0
        total_lab = 0.0
        total_issue = 0.0
        total_scrap = 0.0
        total_fine = 0.0
        total_amount = 0.0

        # Running balance variables
        current_partner = None
        running_balance = 0.0

        for rec in docs:

            # =========================
            # Running Balance Logic
            # =========================
            if partner_filter:
                partner = rec.issue_id.refinery_partner_id.id

                if partner != current_partner:
                    current_partner = partner

                    # FIRST ROW (Issue)
                    running_balance = rec.expected_fine or 0.0

                else:
                    if rec.type == 'issue':
                        running_balance = rec.expected_fine or 0.0

                    elif rec.type == 'receive':
                        running_balance = (rec.scrap_bar_fine_weight or 0.0) - running_balance

                balance_value = running_balance

            else:
                # Normal mode
                balance_value = rec.balance or 0.0

            # =========================
            # Write Data
            # =========================
            sheet.write(row, 0, str(rec.date or ''), text_format)
            sheet.write(row, 1, rec.name or '', text_format)
            sheet.write(row, 2, (rec.type or '').capitalize(), text_format)
            sheet.write(row, 3, rec.batches or '', text_format)

            sheet.write(row, 4, rec.gross_weight, number_format)
            sheet.write(row, 5, rec.net_weight, number_format)
            sheet.write(row, 6, rec.purity_id.name if rec.purity_id else '', text_format)

            sheet.write(row, 7, rec.expected_fine, number_format)
            sheet.write(row, 8, rec.melting_loss, number_format)
            sheet.write(row, 9, rec.lab_weight, number_format)

            sheet.write(row, 10, rec.refinery_issue_weight, number_format)
            sheet.write(row, 11, rec.scrap_bar_fine_weight, number_format)
            sheet.write(row, 12, rec.total_fine_weight, number_format)

            # ✅ Custom Balance
            sheet.write(row, 13, balance_value, number_format)

            sheet.write(row, 14, rec.amount, number_format)
            sheet.write(row, 15, rec.fine_rate, number_format)

            # =========================
            # Totals
            # =========================
            total_gross += rec.gross_weight
            total_net += rec.net_weight
            total_expected += rec.expected_fine
            total_loss += rec.melting_loss
            total_lab += rec.lab_weight
            total_issue += rec.refinery_issue_weight
            total_scrap += rec.scrap_bar_fine_weight
            total_fine += rec.total_fine_weight
            total_amount += rec.amount

            row += 1

        # =========================
        # Totals Row
        # =========================
        sheet.write(row, 0, '', bold_format)
        sheet.write(row, 1, '', bold_format)
        sheet.write(row, 2, '', bold_format)
        sheet.write(row, 3, 'Total', bold_format)

        sheet.write(row, 4, total_gross, bold_format)
        sheet.write(row, 5, total_net, bold_format)
        sheet.write(row, 6, '', bold_format)

        sheet.write(row, 7, total_expected, bold_format)
        sheet.write(row, 8, total_loss, bold_format)
        sheet.write(row, 9, total_lab, bold_format)

        sheet.write(row, 10, total_issue, bold_format)
        sheet.write(row, 11, total_scrap, bold_format)
        sheet.write(row, 12, total_fine, bold_format)

        sheet.write(row, 13, '', bold_format)  # no total for balance
        sheet.write(row, 14, total_amount, bold_format)
        sheet.write(row, 15, '', bold_format)