from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

import base64
from io import BytesIO
from openpyxl import load_workbook


class ProductLabelImportWizard(models.TransientModel):
    _name = "product.label.import.wizard"
    _description = "Product Label Excel Import"

    file = fields.Binary(
        string="Excel File",
        required=True
    )

    filename = fields.Char(
        string="Filename"
    )

    COLUMN_MAP = {
        "label_name": "Label Name",
        "label_number": "Label Number",
        "barcode": "Barcode",

        "product": "Product",
        "branch": "Branch",
        "purity": "Purity",

        "purchase_order": "Purchase Order",
        "job_work": "Job Work",

        "source_location": "Source Location",
        "destination_location": "Destination Location",

        "tag_weight": "Tag Weight (g)",

        "sale_gross_weight": "Sale Gross Weight (g)",
        "sale_stone_weight": "Sale Stone Weight (g)",
        "sale_stone_weight_ct": "Sale Stone Weight (ct)",
        "sale_diamond_weight_gm": "Sale Diamond Weight (g)",
        "sale_diamond_weight_ct": "Sale Diamond Weight (ct)",

        "sale_making_charge_type": "Sale Making Charge Type",
        "sale_making_charge_value": "Sale Making Charge Max",
        "sale_making_charge_min": "Sale Making Charge Min",

        "sale_stone_rate": "Sale Stone Amount",
        "sale_diamond_rate": "Sale Diamond Amount",

        "purchase_price_per_gram": "Purchase fine Rate / gram",

        "purchase_gross_weight": "Purchase Gross Weight (g)",
        "purchase_stone_weight": "Purchase Stone Weight (g)",
        "purchase_stone_weight_ct": "Purchase Stone Weight (ct)",
        "purchase_diamond_weight_gm": "Purchase Diamond Weight (g)",
        "purchase_diamond_weight_ct": "Purchase Diamond Weight (ct)",

        "purchase_making_charge_type": "Purchase Making Charge Type",
        "purchase_making_charge_value": "Purchase Making Charge",

        "purchase_stone_rate": "Purchase Stone Amount",
        "purchase_diamond_rate": "Purchase Diamond Amount",

        "certification_charge": "Certification Charge",
        "transportation_charge": "Transportation Charge",
        "cargo_charge": "Cargo Charge",
        "others": "Others",

        "active": "Active",
    }

    def action_import(self):
        self.ensure_one()

        if not self.file:
            raise ValidationError(_("Please upload an Excel file."))

        try:
            workbook = load_workbook(
                filename=BytesIO(base64.b64decode(self.file)),
                data_only=True
            )
        except Exception:
            raise ValidationError(_("Invalid Excel file."))

        sheet = workbook.active

        headers = [
            str(cell.value).strip() if cell.value else ""
            for cell in sheet[1]
        ]

        header_map = {
            header: index
            for index, header in enumerate(headers)
        }

        self._validate_headers(header_map)

        created = 0

        for row_no, row in enumerate(
                sheet.iter_rows(min_row=2, values_only=True),
                start=2):

            if not any(row):
                continue

            values = self._prepare_row_values(
                row,
                header_map,
                row_no
            )

            self.env["product.label"].create(values)
            created += 1

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Import Completed"),
                "message": _("%s Product Labels imported successfully.") % created,
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window_close",
                },
            },
        }

    # ---------------------------------------------------------
    # HEADER VALIDATION
    # ---------------------------------------------------------

    def _validate_headers(self, header_map):
        required_headers = [
            self.COLUMN_MAP["product"],
            self.COLUMN_MAP["branch"],
        ]

        missing = [h for h in required_headers if h not in header_map]

        if missing:
            raise ValidationError(
                _("Missing required columns:\n%s") % "\n".join(missing)
            )

    # ---------------------------------------------------------
    # VALUE HELPERS
    # ---------------------------------------------------------

    def _get(self, row, header_map, column):
        if column not in header_map:
            return False
        value = row[header_map[column]]
        if value is None:
            return False
        return value

    def _float(self, value):
        if value in (None, "", False):
            return 0.0
        try:
            return float(value)
        except Exception:
            return 0.0

    def _bool(self, value):
        if value in (True, 1, "1", "TRUE", "True", "true", "YES", "Yes", "yes"):
            return True
        return False

    # ---------------------------------------------------------
    # SELECTION MAPPING
    # ---------------------------------------------------------

    def _mc_type(self, value):
        if not value:
            return "percent"

        value = str(value).strip().lower()

        mapping = {
            "percentage": "percent",
            "percent": "percent",
            "%": "percent",
            "amount": "amount",
            "rate per gram": "rate_per_gram",
            "rate_per_gm": "rate_per_gram",
            "rate/gm": "rate_per_gram",
            "rate/g": "rate_per_gram",
        }

        return mapping.get(value, "percent")

    # ---------------------------------------------------------
    # PRODUCT
    # ---------------------------------------------------------

    def _find_product(self, name):
        if not name:
            return False

        name = str(name).strip()

        product = self.env["product.product"].search([
            ("name", "=", name)
        ], limit=1)

        if product:
            return product

        template = self.env["product.template"].create({
            "name": name,
            "type": "product",
            "purchase_ok": True,
            "sale_ok": True,
        })

        return template.product_variant_id

    # ---------------------------------------------------------
    # BRANCH
    # ---------------------------------------------------------

    def _find_branch(self, name):

        if not name:
            return False

        name = str(name).strip()

        branch = self.env["res.branch"].search([
            ("name", "=", name)
        ], limit=1)

        if branch:
            return branch

        return self.env["res.branch"].create({
            "name": name,
            "company_id": self.env.company.id,
        })

    # ---------------------------------------------------------
    # PURITY
    # ---------------------------------------------------------

    def _find_purity(self, value):

        if not value:
            return False

        purity = self.env["gold.purity"].search([
            "|",
            ("name", "=", str(value)),
            ("percentage", "=", self._float(value))
        ], limit=1)

        if purity:
            return purity

        percentage = self._float(value)

        return self.env["gold.purity"].create({
            "name": str(value),
            "percentage": percentage,
        })

    # ---------------------------------------------------------
    # STOCK LOCATION
    # ---------------------------------------------------------

    def _find_location(self, name, branch=False):

        if not name:
            return False

        name = str(name).strip()

        location = self.env["stock.location"].search([
            "|",
            ("complete_name", "=", name),
            ("name", "=", name),
        ], limit=1)

        if location:
            return location

        vals = {
            "name": name,
            "usage": "internal",
        }

        # Add branch only if the field exists
        if branch and "branch_id" in self.env["stock.location"]._fields:
            vals["branch_id"] = branch.id

        return self.env["stock.location"].create(vals)

    # ---------------------------------------------------------
    # PURCHASE ORDER
    # ---------------------------------------------------------

    def _find_purchase(self, po, row_no):

        if not po:
            return False

        purchase = self.env["purchase.order"].search([
            ("name", "=", str(po).strip())
        ], limit=1)

        if not purchase:
            raise ValidationError(
                _("Row %s : Purchase Order '%s' not found.") % (
                    row_no,
                    po,
                )
            )

        return purchase

    # ---------------------------------------------------------
    # JOB WORK
    # ---------------------------------------------------------

    def _find_job_work(self, job):

        if not job:
            return False

        return self.env["jewellery.job.work"].search([
            ("name", "=", str(job).strip())
        ], limit=1)

    def action_import(self):
        self.ensure_one()

        if not self.file:
            raise ValidationError(_("Please upload an Excel file."))

        try:
            workbook = load_workbook(
                filename=BytesIO(base64.b64decode(self.file)),
                data_only=True
            )
        except Exception:
            raise ValidationError(_("Invalid Excel file."))

        sheet = workbook.active

        headers = [
            str(cell.value).strip() if cell.value else ""
            for cell in sheet[1]
        ]

        header_map = {
            header: index
            for index, header in enumerate(headers)
        }

        self._validate_headers(header_map)

        created = 0
        skipped = 0
        errors = []

        for row_no, row in enumerate(
                sheet.iter_rows(min_row=2, values_only=True),
                start=2):

            if not any(row):
                continue

            try:
                values = self._prepare_row_values(
                    row,
                    header_map,
                    row_no
                )

                # Duplicate barcode / label number
                if not values:
                    skipped += 1
                    errors.append(
                        _("Row %s : Duplicate Barcode or Label Number") % row_no
                    )
                    continue

                self.env["product.label"].create(values)
                created += 1

            except Exception as e:
                skipped += 1
                errors.append(
                    _("Row %s : %s") % (row_no, str(e))
                )

        # ----------------------------------------------------
        # SHOW SUMMARY
        # ----------------------------------------------------

        message = _(
            "Import Completed\n\n"
            "Created : %s\n"
            "Skipped : %s"
        ) % (
                      created,
                      skipped,
                  )

        if errors:
            # Show only first 15 errors to avoid huge notification
            message += _("\n\nSkipped Rows:\n")
            message += "\n".join(errors[:15])

            if len(errors) > 15:
                message += _(
                    "\n\n...and %s more."
                ) % (len(errors) - 15)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Product Label Import"),
                "message": message,
                "sticky": True,
                "type": "success",
                "next": {
                    "type": "ir.actions.act_window_close",
                },
            },
        }