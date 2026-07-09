from odoo import models, fields,api
from io import BytesIO
import base64
from openpyxl import Workbook
from openpyxl.styles import Font


class SalesmanTargetReportWizard(models.TransientModel):
    _name = 'salesman.target.report.wizard'
    _description = 'Salesman Target Report Wizard'

    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)

    salesman_ids = fields.Many2many(
        'res.users',
        string='Salespersons'
    )


    file_data = fields.Binary(readonly=True)
    file_name = fields.Char(readonly=True)

    def action_generate_report(self):
        self.ensure_one()


        domain = [
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ]


        if self.salesman_ids:
            domain.append(
                ('salesman_id', 'in', self.salesman_ids.ids)
            )

        records = self.env['salesman.target'].search(
            domain,
            order='salesman_id,date_from'
        )


        wb = Workbook()
        ws = wb.active
        ws.title = "Salesman Targets"

        headers = [
            'Reference',
            'Salesman',
            'Employee',
            'Branch',

            'Period From',
            'Period To',

            'Target Amount',
            'Target GMS 22K',
            'Target GMS 18CT',
            'Target GMS 22KT',
            'Target Diamond CT',

            'Incentive Amount',

            'Branch Target Amount',
            'Branch Target GMS 22K',
            'Branch Target GMS 18CT',
            'Branch Target GMS 22KT',
            'Branch Target Diamond CT',

            'Achieved Amount',
            'Achieved GMS 22K',
            'Achieved GMS 18CT',
            'Achieved GMS 22KT',
            'Achieved Diamond CT',
            'Achieved Total GMS',

            'Branch Achieved GMS 22K',
            'Branch Achieved GMS 18CT',
            'Branch Achieved GMS 22KT',
            'Branch Achieved Diamond CT',

            'Amount Progress %',
            'GMS Progress %',

            'Is Achieved',
            'Earned Incentive',

            'State',
            'Payment Date',

            'Branch Salesman Count',

            'Notes'
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
            ws.cell(row, 1).value = rec.name
            ws.cell(row, 2).value = rec.salesman_id.name or ''
            ws.cell(row, 3).value = rec.employee_id.name or ''
            ws.cell(row, 4).value = rec.branch_id.name or ''

            ws.cell(row, 5).value = str(rec.date_from or '')
            ws.cell(row, 6).value = str(rec.date_to or '')

            ws.cell(row, 7).value = rec.target_amount
            ws.cell(row, 8).value = rec.target_gms_22k
            ws.cell(row, 9).value = rec.target_gms_18ct
            ws.cell(row, 10).value = rec.target_gms_22kt
            ws.cell(row, 11).value = rec.target_diamond_ct

            ws.cell(row, 12).value = rec.earned_incentive

            ws.cell(row, 13).value = rec.branch_target_amount
            ws.cell(row, 14).value = rec.branch_target_gms_22k
            ws.cell(row, 15).value = rec.branch_target_gms_18ct
            ws.cell(row, 16).value = rec.branch_target_gms_22kt
            ws.cell(row, 17).value = rec.branch_target_diamond_ct

            ws.cell(row, 18).value = rec.achieved_amount
            ws.cell(row, 19).value = rec.achieved_gms_22k
            ws.cell(row, 20).value = rec.achieved_gms_18ct
            ws.cell(row, 21).value = rec.achieved_gms_22kt
            ws.cell(row, 22).value = rec.achieved_diamond_ct
            ws.cell(row, 23).value = rec.achieved_gms

            ws.cell(row, 24).value = rec.branch_achieved_gms_22k
            ws.cell(row, 25).value = rec.branch_achieved_gms_18ct
            ws.cell(row, 26).value = rec.branch_achieved_gms_22kt
            ws.cell(row, 27).value = rec.branch_achieved_diamond_ct

            ws.cell(row, 28).value = rec.amount_progress
            ws.cell(row, 29).value = rec.gms_progress

            ws.cell(row, 30).value = 'Yes' if rec.is_achieved else 'No'
            ws.cell(row, 31).value = rec.earned_incentive

            ws.cell(row, 32).value = rec.state
            ws.cell(row, 33).value = str(rec.payment_date or '')

            ws.cell(row, 34).value = rec.branch_salesman_count

            ws.cell(row, 35).value = rec.notes or ''

            row += 1


        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter

            for cell in column:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))

            ws.column_dimensions[column_letter].width = max_length + 5


        output = BytesIO()
        wb.save(output)
        output.seek(0)

        self.file_data = base64.b64encode(output.read())
        self.file_name = 'Salesman_Target_Report.xlsx'
        output.close()

        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/web/content/?model=salesman.target.report.wizard'
                '&id=%s'
                '&field=file_data'
                '&filename_field=file_name'
                '&download=true'
            ) % self.id,
            'target': 'self',
        }