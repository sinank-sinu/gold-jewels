from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from io import BytesIO
import base64
from openpyxl import Workbook
from openpyxl.styles import Font


class NonLabelledReportWizard(models.TransientModel):
    _name = "non.labelled.report.wizard"
    _description = "Non Labelled Ornament Report"

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    branch_ids = fields.Many2many(
        "res.branch",
        string="Branches",
    )

    file_data = fields.Binary(readonly=True)
    file_name = fields.Char(readonly=True)

    @api.constrains("start_date", "end_date")
    def _check_dates(self):
        for rec in self:
            if rec.end_date and rec.start_date and rec.end_date < rec.start_date:
                raise ValidationError(_("End Date must be greater than or equal to Start Date."))

    def _get_report_data(self):
        query = """
            WITH lbl AS (
                SELECT
                    pl.purchase_id,
                    pl.job_work_id,
                    pl.product_id,
                    SUM(pl.purchase_gross_weight) AS labelled_weight
                FROM product_label pl
                WHERE
                    pl.active = TRUE
                    AND pl.create_date::date BETWEEN %s AND %s
                GROUP BY
                    pl.purchase_id,
                    pl.job_work_id,
                    pl.product_id
            ),

            po_qty AS (
                SELECT
                    pol.order_id AS purchase_id,
                    pol.product_id,
                    SUM(pol.product_qty) AS gross_weight
                FROM purchase_order_line pol
                GROUP BY
                    pol.order_id,
                    pol.product_id
            ),

            jw_qty AS (
                SELECT
                    jl.job_work_id,
                    jl.product_id,
                    SUM(jl.quantity) AS gross_weight
                FROM jewellery_job_work_line jl
                GROUP BY
                    jl.job_work_id,
                    jl.product_id
            ),

            purity AS (
                SELECT
                    pl.purchase_id,
                    pl.job_work_id,
                    pl.product_id,
                    STRING_AGG(DISTINCT gp.name, ', ' ORDER BY gp.name) AS caret
                FROM product_label pl
                LEFT JOIN gold_purity gp
                    ON gp.id = pl.purity_id
                WHERE
                    pl.active = TRUE
                    AND pl.create_date::date BETWEEN %s AND %s
                GROUP BY
                    pl.purchase_id,
                    pl.job_work_id,
                    pl.product_id
            )

            SELECT

                po.name AS po_number,

                COALESCE(job_partner.name, po_partner.name) AS party_name,

                jw.name AS job_work_no,

                COALESCE(pr.caret, '') AS caret,

                CASE
                    WHEN lbl.purchase_id IS NOT NULL
                        THEN COALESCE(pq.gross_weight, 0)
                    ELSE
                        COALESCE(jq.gross_weight, 0)
                END AS total_weight,

                COALESCE(lbl.labelled_weight, 0) AS total_labelled,

                (
                    CASE
                        WHEN lbl.purchase_id IS NOT NULL
                            THEN COALESCE(pq.gross_weight, 0)
                        ELSE
                            COALESCE(jq.gross_weight, 0)
                    END
                    - COALESCE(lbl.labelled_weight, 0)
                ) AS total_unlabelled

            FROM lbl

            LEFT JOIN purchase_order po
                ON po.id = lbl.purchase_id

            LEFT JOIN jewellery_job_work jw
                ON jw.id = lbl.job_work_id

            LEFT JOIN res_partner po_partner
                ON po_partner.id = po.partner_id

            LEFT JOIN res_partner job_partner
                ON job_partner.id = jw.job_worker_id

            LEFT JOIN po_qty pq
                ON pq.purchase_id = lbl.purchase_id
               AND pq.product_id = lbl.product_id

            LEFT JOIN jw_qty jq
                ON jq.job_work_id = lbl.job_work_id
               AND jq.product_id = lbl.product_id

            LEFT JOIN purity pr
                ON pr.purchase_id IS NOT DISTINCT FROM lbl.purchase_id
               AND pr.job_work_id IS NOT DISTINCT FROM lbl.job_work_id
               AND pr.product_id = lbl.product_id
        """

        params = [
            self.start_date,
            self.end_date,  # lbl
            self.start_date,
            self.end_date,  # purity
        ]

        if self.branch_ids:
            query += """
                WHERE EXISTS (
                    SELECT 1
                    FROM product_label pl2
                    WHERE
                        pl2.active = TRUE
                        AND pl2.create_date::date BETWEEN %s AND %s
                        AND pl2.purchase_id IS NOT DISTINCT FROM lbl.purchase_id
                        AND pl2.job_work_id IS NOT DISTINCT FROM lbl.job_work_id
                        AND pl2.product_id = lbl.product_id
                        AND pl2.branch_id = ANY(%s)
                )
            """
            params.extend([
                self.start_date,
                self.end_date,
                self.branch_ids.ids,
            ])

        query += """
            ORDER BY
                po.name,
                jw.name
        """

        self.env.cr.execute(query, params)
        return self.env.cr.dictfetchall()
    def action_print_report(self):
        self.ensure_one()

        records = self._get_report_data()

        wb = Workbook()
        ws = wb.active
        ws.title = "Non Labelled Report"

        bold = Font(bold=True)

        headers = [
            "Sl No",
            "Party",
            "PO Number",
            "Job Work No",
            "Caret",
            "Gross Weight",
            "Labelled Weight",
            "Unlabelled Weight",
        ]

        # Header
        for col, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col)
            cell.value = header
            cell.font = bold

        row = 2
        sl = 1

        gross_total = 0.0
        labelled_total = 0.0
        unlabelled_total = 0.0

        row = 2
        sl = 1

        for rec in records:

            gross = float(rec.get("total_weight") or 0)
            labelled = float(rec.get("total_labelled") or 0)
            unlabelled = gross - labelled

            # Skip fully labelled POs
            if unlabelled <= 0:
                continue

            ws.cell(row, 1).value = sl
            ws.cell(row, 2).value = rec.get("party_name") or ""
            ws.cell(row, 3).value = rec.get("po_number") or ""
            ws.cell(row, 4).value = rec.get("job_work_no") or ""
            ws.cell(row, 5).value = rec.get("caret") or ""
            ws.cell(row, 6).value = gross
            ws.cell(row, 7).value = labelled
            ws.cell(row, 8).value = unlabelled

            ws.cell(row, 6).number_format = "0.000"
            ws.cell(row, 7).number_format = "0.000"
            ws.cell(row, 8).number_format = "0.000"

            gross_total += gross
            labelled_total += labelled
            unlabelled_total += unlabelled

            row += 1
            sl += 1


        # Total row
        ws.cell(row=row, column=5).value = "TOTAL"
        ws.cell(row=row, column=5).font = bold

        ws.cell(row=row, column=6).value = gross_total
        ws.cell(row=row, column=7).value = labelled_total
        ws.cell(row=row, column=8).value = unlabelled_total

        ws.cell(row=row, column=6).font = bold
        ws.cell(row=row, column=7).font = bold
        ws.cell(row=row, column=8).font = bold

        ws.cell(row=row, column=6).number_format = "0.000"
        ws.cell(row=row, column=7).number_format = "0.000"
        ws.cell(row=row, column=8).number_format = "0.000"

        # Auto-size columns
        for column_cells in ws.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter

            for cell in column_cells:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except Exception:
                    pass

            ws.column_dimensions[column_letter].width = max_length + 5

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        self.file_data = base64.b64encode(output.read())
        self.file_name = "Non_Labelled_Ornament_Report.xlsx"

        output.close()

        return {
            "type": "ir.actions.act_url",
            "url": (
                       "/web/content/?model=non.labelled.report.wizard"
                       "&id=%s"
                       "&field=file_data"
                       "&filename_field=file_name"
                       "&download=true"
                   ) % self.id,
            "target": "self",
        }