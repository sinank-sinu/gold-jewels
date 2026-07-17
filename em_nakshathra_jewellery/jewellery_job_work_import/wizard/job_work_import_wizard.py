import base64
import io
from collections import defaultdict
from datetime import datetime, date

from openpyxl import load_workbook

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class JobWorkImportWizard(models.TransientModel):
    _name = "job.work.import.wizard"
    _description = "Import Jewellery Job Work"

    file = fields.Binary(
        string="Excel File",
        required=True,
    )

    filename = fields.Char()

    # Main Import

    def action_import(self):

        self.ensure_one()
        master = self._load_master_data()

        if not self.file:
            raise ValidationError(_("Please upload an Excel file."))

        try:
            workbook = load_workbook(
                filename=io.BytesIO(
                    base64.b64decode(self.file)
                ),
                data_only=True,
            )

        except Exception as e:
            raise ValidationError(str(e))

        sheet = workbook.active

        headers = [
            str(c.value).strip() if c.value else ""
            for c in sheet[1]
        ]

        header_map = {
            h: i
            for i, h in enumerate(headers)
        }

        required = [

            "Job Work Number",

            "Job Worker",

            "Order Date",

            "Branch",

        ]

        missing = [
            x
            for x in required
            if x not in header_map
        ]

        if missing:
            raise ValidationError(
                _("Missing columns\n\n%s")
                % ("\n".join(missing))
            )

        self._load_master_data()

        grouped_rows = defaultdict(list)

        for row in sheet.iter_rows(
                min_row=2,
                values_only=True,
        ):

            if not any(row):
                continue

            number = row[
                header_map["Job Work Number"]
            ]

            if not number:
                continue

            grouped_rows[
                str(number).strip()
            ].append(row)

        created = 0
        skipped = 0
        errors = []

        for job_number, rows in grouped_rows.items():

            try:

                existing = self.env[
                    "jewellery.job.work"
                ].search([
                    ("name", "=", job_number)
                ], limit=1)

                if existing:
                    skipped += 1
                    continue

                self._create_complete_job_work(
                    job_number,
                    rows,
                    header_map,
                )

                created += 1

            except Exception as e:

                errors.append(
                    "%s : %s"
                    % (
                        job_number,
                        str(e),
                    )
                )

        if errors:

            raise ValidationError(
                _(
                    "Created : %s\n"
                    "Skipped : %s\n\n"
                    "%s"
                ) % (
                    created,
                    skipped,
                    "\n".join(errors),
                )
            )

        return {
            "type": "ir.actions.act_window_close",
        }

    # ==========================================================
    # MASTER DATA
    # ==========================================================

    def _load_master_data(self):

        return {
            "partners": {
                p.name.strip().lower(): p
                for p in self.env["res.partner"].search([("is_job_worker", "=", True)])
                if p.name
            },

            "branches": {
                b.name.strip().lower(): b
                for b in self.env["res.branch"].search([])
                if b.name
            },

            "products": {
                (p.display_name or p.name).strip().lower(): p
                for p in self.env["product.product"].search([])
                if (p.display_name or p.name)
            },

            "purities": {
                p.name.strip().lower(): p
                for p in self.env["gold.purity"].search([])
                if p.name
            },

            "locations": {
                l.complete_name.strip().lower(): l
                for l in self.env["stock.location"].search([])
                if l.complete_name
            },

            "uoms": {
                u.name.strip().lower(): u
                for u in self.env["uom.uom"].search([])
                if u.name
            },

            "gram_ranges": {
                g.name.strip().lower(): g
                for g in self.env["gold.gram.range"].search([])
                if g.name
            },
        }
    # ==========================================================
    # LOOKUPS
    # ==========================================================

    def _find_partner(self, value):

        if not value:
            return False

        return self.partner_map.get(
            str(value).strip().lower()
        )

    def _find_branch(self, value):

        if not value:
            return False

        return self.branch_map.get(
            str(value).strip().lower()
        )

    def _find_product(self, value):

        if not value:
            return False

        return self.product_map.get(
            str(value).strip().lower()
        )

    def _find_purity(self, value):

        if value in (None, "", False):
            return False

        key = str(value).strip().lower()

        purity = self.purity_map.get(key)

        if purity:
            return purity

        try:
            key = str(float(value))
            return self.purity_map.get(key)
        except Exception:
            return False

    def _find_location(self, value):

        if not value:
            return False

        return self.location_map.get(
            str(value).strip().lower()
        )

    def _find_uom(self, value):

        if not value:
            return False

        return self.uom_map.get(
            str(value).strip().lower()
        )

    def _find_gram_range(self, value):

        if not value:
            return False

        return self.gram_range_map.get(
            str(value).strip().lower()
        )

    # ==========================================================
    # HELPERS
    # ==========================================================

    def _float(self, value):

        if value in (None, "", False):
            return 0.0

        if isinstance(value, (int, float)):
            return float(value)

        value = str(value)

        value = value.replace(",", "")

        value = value.strip()

        try:
            return float(value)
        except Exception:
            return 0.0

    def _int(self, value):

        return int(round(self._float(value)))

    def _date(self, value):

        if not value:
            return False

        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        value = str(value).strip()

        formats = (
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%m/%d/%Y",
            "%Y/%m/%d",
        )

        for fmt in formats:

            try:
                return datetime.strptime(
                    value,
                    fmt,
                ).date()

            except Exception:
                pass

        return False

    def _state_mapping(self, value):

        if not value:
            return "draft"

        value = str(value).strip().lower()

        mapping = {

            "draft": "draft",

            "issued": "issued",

            "received": "received",

            "done": "done",

        }

        return mapping.get(value, "draft")

    def _create_complete_job_work(
            self,
            job_number,
            rows,
            header_map,
    ):

        row = rows[0]

        # =====================================================
        # Job Worker
        # =====================================================

        partner = self._find_partner(
            row[header_map["Job Worker"]]
        )

        if not partner:
            raise ValidationError(
                _("Job Worker '%s' not found.")
                % row[header_map["Job Worker"]]
            )

        # =====================================================
        # Branch
        # =====================================================

        branch = self._find_branch(
            row[header_map["Branch"]]
        )

        if not branch:
            raise ValidationError(
                _("Branch '%s' not found.")
                % row[header_map["Branch"]]
            )

        # =====================================================
        # Create Job Work
        # =====================================================

        job_work_vals = {

            "name": job_number,

            "job_worker_id": partner.id,

            "branch_id": branch.id,

            "order_date": self._date(
                row[header_map["Order Date"]]
            ),

            "state": self._state_mapping(
                row[header_map["State"]]
            ),

        }

        job_work = self.env[
            "jewellery.job.work"
        ].create(job_work_vals)

        # =====================================================
        # Create Job Work Lines
        # =====================================================

        for line in rows:
            self._create_job_work_line(
                job_work,
                line,
                header_map,
            )

        # =====================================================
        # Issue Voucher
        # =====================================================

        issue = self._create_issue_voucher(
            job_work,
            row,
            header_map,
        )

        # =====================================================
        # Issue Voucher Lines
        # =====================================================

        for line in rows:
            self._create_issue_line(
                issue,
                line,
                header_map,
            )

        # =====================================================
        # Receive Voucher
        # =====================================================

        receive = self._create_receive_voucher(
            job_work,
            issue,
            row,
            header_map,
        )

        # =====================================================
        # Receive Voucher Lines
        # =====================================================

        for line in rows:
            self._create_receive_line(
                receive,
                issue,
                line,
                header_map,
            )

        return job_work

    def _create_job_work_line(
            self,
            job_work,
            row,
            header_map,
    ):

        # Product

        product = self._find_product(
            row[header_map["Job Work Line/Product"]]
        )

        if not product:
            raise ValidationError(
                _("Product '%s' not found.")
                % row[header_map["Job Work Line/Product"]]
            )

        # Purity

        purity = self._find_purity(
            row[header_map["Job Work Line/Purity"]]
        )

        if not purity:
            raise ValidationError(
                _("Purity '%s' not found.")
                % row[header_map["Job Work Line/Purity"]]
            )

        # Gram Range

        gram_range = False

        if "Job Work Line/Gram Range" in header_map:
            gram_range = self._find_gram_range(
                row[header_map["Job Work Line/Gram Range"]]
            )

        # Create Line

        vals = {

            "job_work_id": job_work.id,

            "product_id": product.id,

            "product_template_id": product.product_tmpl_id.id,

            "purity_id": purity.id,

            "quantity": self._float(
                row[header_map["Job Work Line/Quantity"]]
            ),

            "stone_weight": self._float(
                row[header_map["Job Work Line/Stone/Diamond Weight (g)"]]
            ),

            "net_weight": self._float(
                row[header_map["Job Work Line/Net Weight (g)"]]
            ),

            # "purchase_making_charge_value": self._float(
            #     row[header_map["Job Work Line/MC Fine"]]
            # ),

            "purchase_making_charge_value": 0.0,
            "purchase_price_per_gram": 0.0,

            "no_of_pieces": self._int(
                row[header_map["Job Work Line/No. of Pieces"]]
            ),

            "gram_range_id": gram_range.id if gram_range else False,

        }

        self.env[
            "jewellery.job.work.line"
        ].create(vals)

    def _create_issue_voucher(
            self,
            job_work,
            row,
            header_map,
    ):

        source_location = self._find_location(
            row[header_map["Issue Voucher/Source Location"]]
        )

        if not source_location:
            raise ValidationError(
                _("Source Location '%s' not found.")
                % row[header_map["Issue Voucher/Source Location"]]
            )

        vendor_location = self._find_location(
            row[header_map["Issue Voucher/Vendor Location"]]
        )

        if not vendor_location:
            raise ValidationError(
                _("Vendor Location '%s' not found.")
                % row[header_map["Issue Voucher/Vendor Location"]]
            )

        vals = {

            "name": row[
                header_map["Issue Voucher/Issue Voucher Number"]
            ],

            "job_work_id": job_work.id,

            "job_worker_id": job_work.job_worker_id.id,

            "branch_id": job_work.branch_id.id,

            "order_date": job_work.order_date,

            "source_location_id": source_location.id,

            "received_location_id": vendor_location.id,

            "total_fine_weight": self._float(
                row[
                    header_map[
                        "Issue Voucher/Total Fine Weight"
                    ]
                ]
            ),

        }

        if "State" in header_map:

            state = self._state_mapping(
                row[header_map["State"]]
            )

            if state == "issued":
                vals["state"] = "done"
            else:
                vals["state"] = "draft"

        issue = self.env[
            "jewellery.issue.voucher"
        ].create(vals)

        return issue

    def _create_issue_line(
            self,
            issue,
            row,
            header_map,
    ):

        product = self._find_product(
            row[header_map["Issue Voucher/Order Lines/Product"]]
        )

        if not product:
            raise ValidationError(
                _("Product '%s' not found.")
                % row[header_map["Issue Voucher/Order Lines/Product"]]
            )

        purity = self._find_purity(
            row[header_map["Issue Voucher/Order Lines/Purity"]]
        )

        if not purity:
            raise ValidationError(
                _("Purity '%s' not found.")
                % row[header_map["Issue Voucher/Order Lines/Purity"]]
            )

        uom = self._find_uom(
            row[header_map["Issue Voucher/Order Lines/UoM"]]
        )

        if not uom:
            uom = product.uom_id

        gram_range = False

        if "Issue Voucher/Order Lines/Gram Range" in header_map:
            gram_range = self._find_gram_range(
                row[header_map["Issue Voucher/Order Lines/Gram Range"]]
            )

        vals = {

            "voucher_id": issue.id,

            "product_id": product.id,

            "product_template_id": product.product_tmpl_id.id,

            "uom_id": uom.id if uom else False,

            "purity_id": purity.id,

            "issued_weight": self._float(
                row[
                    header_map[
                        "Issue Voucher/Order Lines/Issued Weight (g)"
                    ]
                ]
            ),

            "stone_weight": self._float(
                row[
                    header_map[
                        "Issue Voucher/Order Lines/Stone Weight (g)"
                    ]
                ]
            ),

            "diamond_weight": self._float(
                row[
                    header_map[
                        "Issue Voucher/Order Lines/Diamond Weight (g)"
                    ]
                ]
            ),

            "purchase_price_per_gram": self._float(
                row[
                    header_map[
                        "Issue Voucher/Order Lines/Purchase fine Rate / gram"
                    ]
                ]
            ),

            "purchase_making_charge_value": 0.0,

            "no_of_pieces": self._int(
                row[
                    header_map[
                        "Issue Voucher/Order Lines/No. of Pieces"
                    ]
                ]
            ),

            "gram_range_id": gram_range.id if gram_range else False,

            "fine_gms_price": self._float(
                row[
                    header_map[
                        "Issue Voucher/Order Lines/Fine GMS Price"
                    ]
                ]
            ),

            "fine_issue_amount": self._float(
                row[
                    header_map[
                        "Issue Voucher/Order Lines/Fine Amount"
                    ]
                ]
            ),

        }

        self.env[
            "jewellery.issue.voucher.line"
        ].create(vals)

    def _create_receive_voucher(
            self,
            job_work,
            issue,
            row,
            header_map,
    ):

        source_location = self._find_location(
            row[header_map["Receive Voucher/Source Location"]]
        )

        if not source_location:
            raise ValidationError(
                _("Receive Source Location '%s' not found.")
                % row[header_map["Receive Voucher/Source Location"]]
            )

        destination = self._find_location(
            row[header_map["Receive Voucher/Received Location"]]
        )

        if not destination:
            raise ValidationError(
                _("Receive Destination '%s' not found.")
                % row[header_map["Receive Voucher/Received Location"]]
            )

        vals = {

            "name": row[
                header_map[
                    "Receive Voucher/Receive Voucher Number"
                ]
            ],

            "job_work_id": job_work.id,

            "job_worker_id": job_work.job_worker_id.id,

            "issue_voucher_id": issue.id,

            "branch_id": job_work.branch_id.id,

            "order_date": self._date(
                row[
                    header_map[
                        "Receive Voucher/Order Date"
                    ]
                ]
            ),

            "source_location_id": source_location.id,

            "received_location_id": destination.id,

            "fine_rate": self._float(
                row[
                    header_map[
                        "Receive Voucher/Fine Rate (g)"
                    ]
                ]
            ),

            "job_type_selection": (
                "gold_alloy"
                if str(
                    row[
                        header_map[
                            "Receive Voucher/Job Type Selection"
                        ]
                    ]
                ).strip().lower()
                   == "gold + alloy"
                else "gold_only"
            ),

            "making_charge_type": {
                "percentage": "percent",
                "amount": "amount",
                "rate per gram": "rate_per_gram",
            }.get(
                str(
                    row[
                        header_map[
                            "Receive Voucher/MC Type"
                        ]
                    ]
                ).strip().lower(),
                "percent",
            ),

            "mc_percent": self._float(
                row[
                    header_map[
                        "Receive Voucher/MC%"
                    ]
                ]
            ),

            "rate_value": self._float(
                row[
                    header_map[
                        "Receive Voucher/Rate(g)"
                    ]
                ]
            ),

            "wastage_weight": self._float(
                row[
                    header_map[
                        "Receive Voucher/Wastage Weight"
                    ]
                ]
            ),

        }

        receive = self.env[
            "jewellery.receive.voucher"
        ].create(vals)

        return receive

    def _create_receive_line(
            self,
            receive,
            issue,
            row,
            header_map,
    ):

        # Product

        product = self._find_product(
            row[header_map["Receive Voucher/Order Lines/Product"]]
        )

        if not product:
            raise ValidationError(
                _("Receive Product '%s' not found.")
                % row[header_map["Receive Voucher/Order Lines/Product"]]
            )

        # Purity

        purity = self._find_purity(
            row[header_map["Receive Voucher/Order Lines/Purity"]]
        )

        if not purity:
            raise ValidationError(
                _("Purity '%s' not found.")
                % row[header_map["Receive Voucher/Order Lines/Purity"]]
            )

        # UOM

        uom = self._find_uom(
            row[header_map["Receive Voucher/Order Lines/UoM"]]
        )

        if not uom:
            uom = product.uom_id

        # Find Issue Line

        issue_line = issue.line_ids.filtered(
            lambda l: l.product_id.id == product.id
        )[:1]

        vals = {

            "voucher_id": receive.id,

            "issue_voucher_line_id": issue_line.id if issue_line else False,

            "product_id": product.id,

            "product_template_id": product.product_tmpl_id.id,

            "uom_id": uom.id if uom else False,

            "purity_id": purity.id,

            "gross_weight": self._float(
                row[
                    header_map[
                        "Receive Voucher/Order Lines/Gross Weight (g)"
                    ]
                ]
            ),

            "stone_weight": self._float(
                row[
                    header_map[
                        "Receive Voucher/Order Lines/Stone Weight (g)"
                    ]
                ]
            ),

            "diamond_weight": self._float(
                row[
                    header_map[
                        "Receive Voucher/Order Lines/Diamond Weight (g)"
                    ]
                ]
            ),

            "purchase_making_charge_value": self._float(
                row[
                    header_map[
                        "Receive Voucher/Order Lines/Purchase Making Charge"
                    ]
                ]
            ),

            "fine_gms_price": self._float(
                row[
                    header_map[
                        "Receive Voucher/Order Lines/Fine GMS Price"
                    ]
                ]
            ),

            "fine_issue_amount": self._float(
                row[
                    header_map[
                        "Receive Voucher/Order Lines/Fine Issue Amount"
                    ]
                ]
            ),

        }

        self.env[
            "jewellery.receive.voucher.line"
        ].create(vals)