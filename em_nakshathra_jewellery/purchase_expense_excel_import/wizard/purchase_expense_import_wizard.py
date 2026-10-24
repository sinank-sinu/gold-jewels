import base64
import io
from collections import OrderedDict
from datetime import date, datetime

from openpyxl import load_workbook

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class PurchaseExpenseImportWizard(models.TransientModel):
    _name = "purchase.expense.import.wizard"
    _description = "Import Purchase Expenses from Excel"

    file = fields.Binary(string="Excel File", required=True)
    file_name = fields.Char()
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    payment_journal_id = fields.Many2one(
        "account.journal",
        string="Bank Payment Journal",
        required=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
        check_company=True,
    )

    @staticmethod
    def _normalize_header(value):
        return " ".join(str(value or "").strip().lower().replace("_", " ").split())

    @staticmethod
    def _number(value, label, row_number, required=True):
        if value in (None, ""):
            if required:
                raise ValidationError(
                    _("Row %(row)s: %(label)s is required.", row=row_number, label=label)
                )
            return None
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            raise ValidationError(
                _("Row %(row)s: %(label)s must be a number.", row=row_number, label=label)
            ) from None

    def _date(self, value, row_number):
        if not value:
            return fields.Date.context_today(self)
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(str(value).strip(), date_format).date()
            except ValueError:
                continue
        raise ValidationError(
            _("Row %s: Bill Date must be a valid date (for example, 2026-10-23).")
            % row_number
        )

    def _read_rows(self):
        self.ensure_one()
        try:
            workbook = load_workbook(
                io.BytesIO(base64.b64decode(self.file)), data_only=True, read_only=True
            )
        except Exception as error:
            raise ValidationError(
                _("Could not read the uploaded workbook. Please upload a valid .xlsx file.")
            ) from error

        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        try:
            headers = next(rows)
        except StopIteration:
            raise ValidationError(_("The Excel file is empty.")) from None

        header_map = {}
        for index, header in enumerate(headers):
            normalized = self._normalize_header(header)
            if normalized:
                if normalized in header_map:
                    raise ValidationError(_("The Excel file has duplicate column headers."))
                header_map[normalized] = index

        required_headers = ("vendor", "bill reference", "product", "quantity", "unit price")
        missing = [header for header in required_headers if header not in header_map]
        if missing:
            raise ValidationError(
                _("Missing required Excel columns: %s") % ", ".join(missing)
            )

        grouped = OrderedDict()
        for row_number, row in enumerate(rows, start=2):
            if not any(value not in (None, "") for value in row):
                continue

            def cell(column):
                index = header_map.get(column)
                return row[index] if index is not None and index < len(row) else None

            vendor_name = str(cell("vendor") or "").strip()
            reference = str(cell("bill reference") or "").strip()
            product_name = str(cell("product") or "").strip()
            if not vendor_name or not reference or not product_name:
                raise ValidationError(
                    _("Row %s: Vendor, Bill Reference and Product are required.")
                    % row_number
                )

            quantity = self._number(cell("quantity"), _("Quantity"), row_number)
            price_unit = self._number(cell("unit price"), _("Unit Price"), row_number)
            subtotal = self._number(
                cell("subtotal"), _("Subtotal"), row_number, required=False
            ) if "subtotal" in header_map else None
            if quantity <= 0:
                raise ValidationError(_("Row %s: Quantity must be greater than zero.") % row_number)
            if price_unit < 0:
                raise ValidationError(_("Row %s: Unit Price cannot be negative.") % row_number)

            bill_date = self._date(cell("bill date"), row_number)
            key = (vendor_name.casefold(), reference.casefold())
            if key not in grouped:
                grouped[key] = {
                    "vendor_name": vendor_name,
                    "reference": reference,
                    "bill_date": bill_date,
                    "lines": [],
                    "row_number": row_number,
                }
            elif grouped[key]["bill_date"] != bill_date:
                raise ValidationError(
                    _("Rows for vendor '%s' and bill reference '%s' have different bill dates.")
                    % (vendor_name, reference)
                )

            grouped[key]["lines"].append({
                "row_number": row_number,
                "product_name": product_name,
                "quantity": quantity,
                "price_unit": price_unit,
                "tax_names": str(cell("tax") or "").strip(),
                "subtotal": subtotal,
            })

        if not grouped:
            raise ValidationError(_("The workbook contains no expense lines."))
        workbook.close()
        return grouped

    def _find_unique(self, model, domain, description, row_number):
        records = self.env[model].search(domain, limit=2)
        if not records:
            raise ValidationError(_("Row %s: %s was not found.") % (row_number, description))
        if len(records) > 1:
            raise ValidationError(
                _("Row %s: %s is ambiguous; use a unique name or internal reference.")
                % (row_number, description)
            )
        return records

    def _resolve_vendor(self, name, row_number):
        return self._find_unique(
            "res.partner",
            [
                ("name", "=", name),
                ("supplier_rank", ">", 0),
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.company_id.id),
            ],
            _("Vendor '%s'") % name,
            row_number,
        )

    def _resolve_product(self, name, row_number):
        product_model = self.env["product.product"]
        products = product_model.search([
            ("purchase_ok", "=", True),
            ("active", "=", True),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id),
            "|",
            ("name", "=", name),
            ("default_code", "=", name),
        ], limit=2)
        if not products:
            raise ValidationError(_("Row %s: Product '%s' was not found.") % (row_number, name))
        if len(products) > 1:
            raise ValidationError(
                _("Row %s: Product '%s' is ambiguous; use its unique internal reference.")
                % (row_number, name)
            )
        return products

    def _resolve_taxes(self, tax_names, row_number):
        taxes = self.env["account.tax"]
        for name in (part.strip() for part in tax_names.split("|")):
            if not name:
                continue
            tax = self._find_unique(
                "account.tax",
                [
                    ("name", "=", name),
                    ("type_tax_use", "=", "purchase"),
                    ("active", "=", True),
                    ("company_id", "=", self.company_id.id),
                ],
                _("Purchase tax '%s'") % name,
                row_number,
            )
            taxes |= tax
        return taxes

    def _prepare_import(self):
        self.ensure_one()
        if not self.file:
            raise ValidationError(_("Please upload an Excel file."))
        if (
            self.payment_journal_id.type != "bank"
            or self.payment_journal_id.company_id != self.company_id
            or not self.payment_journal_id.outbound_payment_method_line_ids
        ):
            raise ValidationError(
                _("Choose a bank journal for this company with an outbound payment method.")
            )

        prepared = []
        for group in self._read_rows().values():
            first_row = group["row_number"]
            vendor = self._resolve_vendor(group["vendor_name"], first_row)
            duplicate = self.env["account.move"].search([
                ("move_type", "=", "in_invoice"),
                ("partner_id", "=", vendor.id),
                ("company_id", "=", self.company_id.id),
                ("ref", "=", group["reference"]),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("Vendor bill '%s' already exists for vendor '%s'.")
                    % (group["reference"], group["vendor_name"])
                )

            bill_lines = []
            for line in group["lines"]:
                product = self._resolve_product(line["product_name"], line["row_number"])
                taxes = self._resolve_taxes(line["tax_names"], line["row_number"])
                if line["subtotal"] is not None:
                    tax_result = taxes.compute_all(
                        line["price_unit"],
                        currency=self.company_id.currency_id,
                        quantity=line["quantity"],
                        product=product,
                        partner=vendor,
                    )
                    computed_subtotal = tax_result["total_excluded"]
                    if not self.company_id.currency_id.is_zero(
                        computed_subtotal - line["subtotal"]
                    ):
                        raise ValidationError(
                            _(
                                "Row %(row)s: Subtotal %(given)s does not match the "
                                "calculated untaxed subtotal %(computed)s."
                            )
                            % {
                                "row": line["row_number"],
                                "given": line["subtotal"],
                                "computed": computed_subtotal,
                            }
                        )
                bill_lines.append({
                    "name": product.display_name,
                    "product_id": product.id,
                    "product_uom_id": product.uom_id.id,
                    "quantity": line["quantity"],
                    "price_unit": line["price_unit"],
                    "tax_ids": [fields.Command.set(taxes.ids)],
                })
            prepared.append({
                "vendor": vendor,
                "reference": group["reference"],
                "bill_date": group["bill_date"],
                "lines": bill_lines,
            })
        return prepared

    def action_import(self):
        self.ensure_one()
        bills = self._prepare_import()
        payment_method_line = self.payment_journal_id.outbound_payment_method_line_ids[:1]

        for bill_values in bills:
            bill = self.env["account.move"].create({
                "move_type": "in_invoice",
                "partner_id": bill_values["vendor"].id,
                "company_id": self.company_id.id,
                "invoice_date": bill_values["bill_date"],
                "ref": bill_values["reference"],
                "invoice_line_ids": [
                    fields.Command.create(line) for line in bill_values["lines"]
                ],
            })
            bill.action_post()

            payment_register = self.env["account.payment.register"].with_context(
                active_model="account.move",
                active_ids=bill.ids,
            ).create({
                "journal_id": self.payment_journal_id.id,
                "payment_method_line_id": payment_method_line.id,
                "payment_date": fields.Date.context_today(self),
            })
            payment_register.action_create_payments()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Purchase expenses imported"),
                "message": _("%s vendor bill(s) posted and paid.") % len(bills),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
