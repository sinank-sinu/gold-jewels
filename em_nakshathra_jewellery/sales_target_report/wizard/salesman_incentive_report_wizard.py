from odoo import models, fields, api
from io import BytesIO
import base64
from openpyxl import Workbook
from openpyxl.styles import Font


class SalesmanIncentiveReportWizard(models.TransientModel):
    _name = 'salesman.incentive.report.wizard'
    _description = 'Salesman Incentive Report Wizard'

    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)

    branch_id = fields.Many2one(
        'res.branch',
        string='Branch'
    )
    salesman_ids = fields.Many2many(
        'res.users',
        string='Salespersons',
        domain=[('share', '=', False)]
    )

    file_data = fields.Binary(readonly=True)
    file_name = fields.Char(readonly=True)

    def action_generate_report(self):
        self.ensure_one()

        domain = [
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ]

        if self.branch_id:
            domain.append(('branch_id', '=', self.branch_id.id))

        if self.salesman_ids:
            domain.append(('salesman_id', 'in', self.salesman_ids.ids))

        records = self.env['salesman.target'].search(
            domain,
            order='branch_id, salesman_id, date_from'
        )

        wb = Workbook()
        ws = wb.active
        ws.title = "Salesman Incentive"

        headers = [
            'Salesman Name',
            'Branch',
            '18CT Amount',
            '18KTD Amount',
            '22KT Amount',
            '18CT %',
            '18KTD %',
            '22KT %',
            '18CT MC amount (calculated)',
            '18KTD MC amount (calculated)',
            '22KT MC amount (calculated)',
            'Total Incentive Amount',
            'Receipts'
        ]

        # ---------------------------
        # HEADER STYLE
        # ---------------------------
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.value = header
            cell.font = Font(bold=True)

        row = 2

        for rec in records:
            
            # Fetch related receipts dynamically
            order_lines = self.env['sale.order.line'].search([
                ('order_id.user_id', '=', rec.salesman_id.id),
                ('order_id.date_order', '>=', rec.date_from),
                ('order_id.date_order', '<=', rec.date_to),
                ('order_id.state', 'in', ['sale', 'done']),
                ('purity_id.name', 'in', ['18CT', '18KTD','22KT', '18ct', '18ktd','22kt']),
            ])
            receipts = list(set(order_lines.mapped('order_id.name')))
            receipts_str = ' | '.join(receipts)

            ws.cell(row, 1).value = rec.salesman_id.name or ''
            ws.cell(row, 2).value = rec.branch_id.name or ''
            ws.cell(row, 3).value = rec.mc_amount_18ct
            ws.cell(row, 4).value = rec.mc_amount_18ktd
            ws.cell(row, 5).value = rec.mc_amount_22kt
            ws.cell(row, 6).value = rec.inc_18ct
            ws.cell(row, 7).value = rec.dmd_inc
            ws.cell(row, 8).value = rec.gold_inc
            ws.cell(row, 9).value = (rec.mc_amount_18ct * (rec.inc_18ct / 100.0)) if rec.mc_amount_18ct else 0.0
            ws.cell(row, 10).value = (rec.mc_amount_18ktd * (rec.dmd_inc / 100.0)) if rec.mc_amount_18ktd else 0.0
            ws.cell(row, 11).value = (rec.mc_amount_22kt * (rec.gold_inc / 100.0)) if rec.mc_amount_22kt else 0.0
            ws.cell(row, 12).value = rec.earned_incentive
            ws.cell(row, 13).value = receipts_str
            row += 1

        # Adjust column widths
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter

            for cell in column:
                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))

            ws.column_dimensions[column_letter].width = max_length + 5

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        self.file_data = base64.b64encode(output.read())
        self.file_name = 'Salesman_Incentive_Report.xlsx'
        output.close()

        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/web/content/?model=salesman.incentive.report.wizard'
                '&id=%s'
                '&field=file_data'
                '&filename_field=file_name'
                '&download=true'
            ) % self.id,
            'target': 'self',
        }
