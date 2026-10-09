

from io import BytesIO
import base64
import xlsxwriter
from odoo import api, fields, models


class LabelSummaryWizard(models.TransientModel):
    _name = "label.summary.wizard"
    _description = "Purchase Job Work Label Summary"

    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)

    branch_ids = fields.Many2many(
        "res.branch",
        string="Branches"
    )

    source = fields.Selection(
        [
            ("purchase", "Purchase"),
            ("job", "Job Work"),
            ("both", "Both"),
        ],
        default="both",
        required=True,
    )

    file_data = fields.Binary(readonly=True)
    file_name = fields.Char(readonly=True)

    def action_print_excel(self):
        self.ensure_one()
        return self._generate_excel()



    def _get_report_data(self):
        self.ensure_one()

        params = {
            "date_from": self.date_from,
            "date_to": self.date_to,
        }

        params = {
            "date_from": self.date_from,
            "date_to": self.date_to,
        }

        purchase_branch_filter = ""
        jobwork_branch_filter = ""

        if self.branch_ids:
            params["branch_ids"] = tuple(self.branch_ids.ids)
            purchase_branch_filter = "AND po.branch_id IN %(branch_ids)s"
            jobwork_branch_filter = "AND jw.branch_id IN %(branch_ids)s"

        purchase_sql = f"""
            SELECT
                'Purchase' AS source,

                po.id AS document_id,
                po.name AS document_no,
                po.date_order::date AS document_date,

                rb.id AS branch_id,
                rb.name AS branch_name,

                rp.id AS party_id,
                rp.name AS party_name,

                pp.id AS product_id,
                pt.name AS product_name,

                gp.name AS purity,
                COALESCE(gp.percentage, 0.0) AS purity_percentage,

                pol.product_qty AS total_qty

            FROM purchase_order_line pol

            JOIN purchase_order po
                ON po.id = pol.order_id

            JOIN product_product pp
                ON pp.id = pol.product_id

            JOIN product_template pt
                ON pt.id = pp.product_tmpl_id

            LEFT JOIN gold_purity gp
                ON gp.id = COALESCE(pol.purity_id, pp.purity_id)

            LEFT JOIN res_partner rp
                ON rp.id = po.partner_id

            LEFT JOIN res_branch rb
                ON rb.id = po.branch_id

            WHERE
    po.state IN ('purchase','done')
    AND pt.type IN ('product', 'consu')
    AND EXISTS (
        SELECT 1
        FROM product_label pl
        WHERE pl.purchase_id = po.id
          AND pl.active = TRUE
    )
    AND po.date_order::date BETWEEN %(date_from)s
                               AND %(date_to)s
    {purchase_branch_filter}
        """

        jobwork_sql = f"""
            SELECT
                'Job Work' AS source,

                jw.id AS document_id,
                jw.name AS document_no,
                jw.order_date::date AS document_date,

                rb.id AS branch_id,
                rb.name AS branch_name,

                rp.id AS party_id,
                rp.name AS party_name,

                pp.id AS product_id,
                pt.name AS product_name,

                gp.name AS purity,
                COALESCE(gp.percentage, 0.0) AS purity_percentage,

                jwl.quantity AS total_qty

            FROM jewellery_job_work_line jwl

            JOIN jewellery_job_work jw
                ON jw.id = jwl.job_work_id

            JOIN product_product pp
                ON pp.id = jwl.product_id

            JOIN product_template pt
                ON pt.id = pp.product_tmpl_id

            LEFT JOIN gold_purity gp
                ON gp.id = COALESCE(jwl.purity_id, pp.purity_id)

            LEFT JOIN res_partner rp
                ON rp.id = jw.job_worker_id

            LEFT JOIN res_branch rb
                ON rb.id = jw.branch_id

            WHERE
                jw.state = 'done'
                AND pt.type IN ('product', 'consu')
                AND EXISTS (
                    SELECT 1
                    FROM product_label pl
                    WHERE pl.job_work_id = jw.id
                      AND pl.active = TRUE
                )
                                AND jw.order_date::date BETWEEN %(date_from)s
                                     AND %(date_to)s
                {jobwork_branch_filter}
        """

        sql = f"""
            {purchase_sql}

            UNION ALL

            {jobwork_sql}

            ORDER BY
                branch_name,
                source,
                document_no,
                product_name
        """

        self.env.cr.execute(sql, params)
        raw_summary_rows = self.env.cr.dictfetchall()

        grouped_rows = {}
        for row in raw_summary_rows:
            key = (row["source"], row["document_id"], row["product_id"])
            if key not in grouped_rows:
                grouped_rows[key] = row
            else:
                grouped_rows[key]["total_qty"] = (grouped_rows[key].get("total_qty") or 0.0) + (row.get("total_qty") or 0.0)
                
        summary_rows = list(grouped_rows.values())

        product_ids = list(set([row["product_id"] for row in summary_rows if row.get("product_id")]))
        products = self.env["product.product"].browse(product_ids)
        product_map = {p.id: p.display_name for p in products}

        for row in summary_rows:
            if isinstance(row.get("product_name"), dict):
                row["product_name"] = (
                        row["product_name"].get(self.env.lang)
                        or row["product_name"].get("en_US")
                        or next(iter(row["product_name"].values()), "")
                )

            purity_pct = row.get("purity_percentage") or 0.0
            total_qty = row["total_qty"] or 0.0
            row["variety"] = product_map.get(row["product_id"], "")
            row["fine_weight"] = round(total_qty * (purity_pct / 100.0), 3)
            row["labelled_qty"] = 0.0
            row["unlabelled_qty"] = total_qty
            row["labels"] = []

        summary_map = {
            (
                row["source"],
                row["document_id"],
                row["product_id"],
            ): row
            for row in summary_rows
        }
        label_sql = """
            SELECT
                'Purchase' AS source,
                pl.purchase_id AS document_id,
                pl.product_id,
                pl.name AS label_number,
                pl.sale_gross_weight AS tag_weight
            FROM product_label pl
            WHERE
                pl.active = TRUE
                AND pl.purchase_id IS NOT NULL

            UNION ALL

            SELECT
                'Job Work' AS source,
                pl.job_work_id AS document_id,
                pl.product_id,
                pl.name AS label_number,
                pl.sale_gross_weight AS tag_weight
            FROM product_label pl
            WHERE
                pl.active = TRUE
                AND pl.job_work_id IS NOT NULL

            ORDER BY
                source,
                document_id,
                product_id,
                label_number
        """

        self.env.cr.execute(label_sql)
        label_rows = self.env.cr.dictfetchall()
        for label in label_rows:

            key = (
                label["source"],
                label["document_id"],
                label["product_id"],
            )

            summary = summary_map.get(key)

            if not summary:
                continue

            tag_weight = label["tag_weight"] or 0.0
            purity_pct = summary.get("purity_percentage") or 0.0
            fine_weight = round(tag_weight * (purity_pct / 100.0), 3)

            summary["labels"].append({
                "label_number": label["label_number"],
                "tag_weight": tag_weight,
                "fine_weight": fine_weight,
            })

            summary["labelled_qty"] += tag_weight

        for row in summary_rows:
            row["unlabelled_qty"] = max(
                (row["total_qty"] or 0.0) - row["labelled_qty"],
                0.0,
            )
        documents = {}

        for row in summary_rows:

            doc_key = (
                row["source"],
                row["document_id"],
            )

            if doc_key not in documents:
                documents[doc_key] = {
                    "source": row["source"],
                    "document_id": row["document_id"],
                    "document_no": row["document_no"],
                    "document_date": row["document_date"],
                    "branch_id": row["branch_id"],
                    "branch_name": row["branch_name"],
                    "party_id": row["party_id"],
                    "party_name": row["party_name"],
                    "products": [],
                }

            documents[doc_key]["products"].append({
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "variety": row["variety"],
                "purity": row["purity"],
                "total_qty": row["total_qty"] or 0.0,
                "fine_weight": row["fine_weight"] or 0.0,
                "labelled_qty": row["labelled_qty"] or 0.0,
                "unlabelled_qty": row["unlabelled_qty"] or 0.0,
                "labels": sorted(
                    row["labels"],
                    key=lambda x: x["label_number"] or ""
                ),
            })

        result = list(documents.values())

        result.sort(
            key=lambda x: (
                x["branch_name"] or "",
                x["source"] or "",
                x["document_no"] or "",
            )
        )

        return result

    def _generate_excel(self):
        report_data = self._get_report_data()

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Label Summary")

        worksheet.set_landscape()
        worksheet.fit_to_pages(1, 0)
        worksheet.freeze_panes(3, 0)

        worksheet.set_column("A:A", 18)
        worksheet.set_column("B:B", 12)
        worksheet.set_column("C:C", 18)
        worksheet.set_column("D:D", 30)
        worksheet.set_column("E:E", 30)
        worksheet.set_column("F:F", 60)
        worksheet.set_column("G:G", 25)
        worksheet.set_column("H:L", 15)
        title_fmt = workbook.add_format({
            "bold": True,
            "font_size": 16,
            "align": "center",
            "valign": "vcenter",
            "font_color": "black",
            "border": 1,
        })

        header_fmt = workbook.add_format({
            "bold": True,
            "align": "center",
            "valign": "vcenter",
            "border": 1,
        })

        summary_fmt = workbook.add_format({
            "border": 1,
            "bold": True,
        })

        detail_fmt = workbook.add_format({
            "border": 1,
        })

        qty_fmt = workbook.add_format({
            "border": 1,
            "num_format": "#,##0.000",
        })

        qty_summary_fmt = workbook.add_format({
            "border": 1,
            "bold": True,
            "num_format": "#,##0.000",
        })

        count_summary_fmt = workbook.add_format({
            "border": 1,
            "bold": True,
            "align": "center",
        })

        worksheet.merge_range(
            "A1:L1",
            "Purchase / Job Work Label Summary",
            title_fmt,
        )

        worksheet.write(
            "A2",
            f"From : {self.date_from.strftime('%d/%m/%Y')}"
        )

        worksheet.write(
            "D2",
            f"To : {self.date_to.strftime('%d/%m/%Y')}"
        )

        headers = [
            "Branch",
            "Source",
            "Document No",
            "Party",
            "Product",
            "Variety",
            "Label No",
            "Purity",
            "Total Qty",
            "Fine Weight",
            "Labelled Qty",
            "Unlabelled Qty",
        ]

        row = 2

        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_fmt)

        row += 1
        grand_total_qty = 0.0
        grand_fine_weight = 0.0
        grand_labelled_qty = 0.0
        grand_unlabelled_qty = 0.0
        grand_label_count = 0

        for document in report_data:
            first_product = True
            doc_total_qty = 0.0
            doc_fine_weight = 0.0
            doc_labelled_qty = 0.0
            doc_unlabelled_qty = 0.0
            doc_label_count = 0

            for product in document["products"]:
                label_count = len(product["labels"])
                doc_label_count += label_count
                grand_label_count += label_count

                worksheet.write(
                    row,
                    0,
                    document["branch_name"] if first_product else "",
                    summary_fmt,
                )

                worksheet.write(
                    row,
                    1,
                    document["source"] if first_product else "",
                    summary_fmt,
                )

                worksheet.write(
                    row,
                    2,
                    document["document_no"] if first_product else "",
                    summary_fmt,
                )

                worksheet.write(
                    row,
                    3,
                    document["party_name"] if first_product else "",
                    summary_fmt,
                )
                worksheet.write(row, 4, product["product_name"], summary_fmt)
                worksheet.write(row, 5, product["variety"], summary_fmt)
                worksheet.write_number(row, 6, label_count, count_summary_fmt)
                worksheet.write(row, 7, product["purity"], summary_fmt)

                worksheet.write_number(row, 8, product["total_qty"], qty_summary_fmt)
                worksheet.write_number(row, 9, product["fine_weight"], qty_summary_fmt)
                worksheet.write_number(row, 10, product["labelled_qty"], qty_summary_fmt)
                worksheet.write_number(row, 11, product["unlabelled_qty"], qty_summary_fmt)
                grand_total_qty += product["total_qty"]
                grand_fine_weight += product["fine_weight"]
                grand_labelled_qty += product["labelled_qty"]
                grand_unlabelled_qty += product["unlabelled_qty"]

                row += 1
                first_product = False

                for label in product["labels"]:
                    worksheet.write(
                        row,
                        4,
                        "",
                        detail_fmt,
                    )
                    
                    worksheet.write(
                        row,
                        5,
                        "",
                        detail_fmt,
                    )

                    worksheet.write(
                        row,
                        6,
                        label["label_number"] or "",
                        detail_fmt,
                    )

                    worksheet.write(
                        row,
                        7,
                        "",
                        detail_fmt,
                    )

                    worksheet.write_blank(row, 8, None, detail_fmt)
                    worksheet.write_number(row, 9, label["fine_weight"], qty_fmt)
                    worksheet.write_number(row, 10, label["tag_weight"], qty_fmt)
                    worksheet.write_blank(row, 11, None, detail_fmt)
                    row += 1

                doc_total_qty += product["total_qty"]
                doc_fine_weight += product["fine_weight"]
                doc_labelled_qty += product["labelled_qty"]
                doc_unlabelled_qty += product["unlabelled_qty"]

            worksheet.write(row, 4, f"TOTAL FOR {document['document_no']}", summary_fmt)
            worksheet.write_blank(row, 5, None, summary_fmt)
            worksheet.write_number(row, 6, doc_label_count, count_summary_fmt)
            worksheet.write_blank(row, 7, None, summary_fmt)
            worksheet.write_number(row, 8, doc_total_qty, qty_summary_fmt)
            worksheet.write_number(row, 9, doc_fine_weight, qty_summary_fmt)
            worksheet.write_number(row, 10, doc_labelled_qty, qty_summary_fmt)
            worksheet.write_number(row, 11, doc_unlabelled_qty, qty_summary_fmt)

            row += 1
        total_fmt = workbook.add_format({
            "bold": True,
            "border": 1,
            "num_format": "#,##0.000",
        })

        total_text_fmt = workbook.add_format({
            "bold": True,
            "border": 1,
        })

        worksheet.write(row, 0, "GRAND TOTAL", total_text_fmt)

        worksheet.write_blank(row, 1, None, total_text_fmt)
        worksheet.write_blank(row, 2, None, total_text_fmt)
        worksheet.write_blank(row, 3, None, total_text_fmt)
        worksheet.write_blank(row, 4, None, total_text_fmt)
        worksheet.write_blank(row, 5, None, total_text_fmt)
        worksheet.write_number(row, 6, grand_label_count, count_summary_fmt)
        worksheet.write_blank(row, 7, None, total_text_fmt)

        worksheet.write_number(row, 8, grand_total_qty, total_fmt)
        worksheet.write_number(row, 9, grand_fine_weight, total_fmt)
        worksheet.write_number(row, 10, grand_labelled_qty, total_fmt)
        worksheet.write_number(row, 11, grand_unlabelled_qty, total_fmt)

        # Close workbook after all writing is complete
        workbook.close()

        # Read the generated Excel file
        output.seek(0)
        file_data = base64.b64encode(output.read())

        filename = "Purchase_Job_Work_Label_Summary.xlsx"

        self.write({
            "file_data": file_data,
            "file_name": filename,
        })

        return {
            "type": "ir.actions.act_url",
            "url": (
                       "/web/content/?model=%s&id=%s"
                       "&field=file_data"
                       "&filename_field=file_name"
                       "&download=true"
                   ) % (
                       self._name,
                       self.id,
                   ),
            "target": "self",
        }