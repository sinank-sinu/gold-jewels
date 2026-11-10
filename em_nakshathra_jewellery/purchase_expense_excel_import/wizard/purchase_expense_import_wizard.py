import base64
from html import escape
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
        string="Payment Journal",
        required=True,
        domain="[('type', 'in', ['bank', 'cash']), ('company_id', '=', company_id)]",
        check_company=True,
    )
    imported_purchase_order_ids = fields.Many2many(
        "purchase.order",
        string="Imported Purchase Orders",
        readonly=True,
    )
    import_completed = fields.Boolean(readonly=True)
    import_result = fields.Char(readonly=True)

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

        required_headers = (
            "vendor",
            "bill reference",
            "product",
            "quantity",
            "unit price",
            "company",
            "branch",
        )
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
            company_name = " ".join(str(cell("company") or "").split())
            branch_name = " ".join(str(cell("branch") or "").split())
            missing_fields = [
                label
                for label, value in (
                    (_("Vendor"), vendor_name),
                    (_("Bill Reference"), reference),
                    (_("Product"), product_name),
                    (_("Company"), company_name),
                    (_("Branch"), branch_name),
                )
                if not value
            ]
            if missing_fields:
                raise ValidationError(
                    _("Row %(row)s: %(fields)s are required or were read as blank.")
                    % {"row": row_number, "fields": ", ".join(missing_fields)}
                )
            company = self._resolve_company(company_name, row_number)
            branch = self._resolve_branch(branch_name, company, row_number)

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
            key = (
                company.id,
                branch.id,
                vendor_name.casefold(),
                reference.casefold(),
            )
            if key not in grouped:
                grouped[key] = {
                    "company": company,
                    "branch": branch,
                    "vendor_name": vendor_name,
                    "reference": reference,
                    "bill_date": bill_date,
                    "lines": [],
                    "narrations": [],
                    "row_number": row_number,
                }
            elif grouped[key]["bill_date"] != bill_date:
                raise ValidationError(
                    _("Rows for vendor '%s' and bill reference '%s' have different bill dates.")
                    % (vendor_name, reference)
                )

            narration = str(cell("narration") or "").strip()
            if narration and narration not in grouped[key]["narrations"]:
                grouped[key]["narrations"].append(narration)

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

    @staticmethod
    def _normalized_name(name):
        return " ".join(name.split()).casefold()

    def _resolve_company(self, name, row_number):
        normalized_name = self._normalized_name(name)
        companies = self.env["res.company"].search(
            [("name", "ilike", name)]
        ).filtered(
            lambda company: self._normalized_name(company.name) == normalized_name
        )
        if not companies:
            raise ValidationError(
                _("Row %s: Company '%s' was not found.") % (row_number, name)
            )
        if len(companies) > 1:
            raise ValidationError(
                _("Row %s: Company '%s' is ambiguous.") % (row_number, name)
            )
        return companies

    def _resolve_branch(self, name, company, row_number):
        normalized_name = self._normalized_name(name)
        branches = self.env["res.branch"].search(
            [("company_id", "=", company.id), ("name", "ilike", name)]
        ).filtered(
            lambda branch: self._normalized_name(branch.name) == normalized_name
        )
        if not branches:
            raise ValidationError(
                _("Row %(row)s: Branch '%(branch)s' was not found for company '%(company)s'.")
                % {"row": row_number, "branch": name, "company": company.name}
            )
        if len(branches) > 1:
            raise ValidationError(
                _("Row %(row)s: Branch '%(branch)s' is ambiguous for company '%(company)s'.")
                % {"row": row_number, "branch": name, "company": company.name}
            )
        if not branches.branch_code:
            raise ValidationError(
                _("Row %(row)s: Branch '%(branch)s' has no branch code for Purchase Order numbering.")
                % {"row": row_number, "branch": name}
            )
        return branches

    def _resolve_picking_type(self, branch, row_number):
        picking_type_model = self.env["stock.picking.type"]
        domain = [
            ("code", "=", "incoming"),
            ("company_id", "=", branch.company_id.id),
            ("warehouse_id.branch_id", "=", branch.id),
        ]
        picking_types = picking_type_model.search(domain, limit=2)
        if not picking_types:
            domain[-1] = ("warehouse_id.branch_id", "=", False)
            picking_types = picking_type_model.search(domain, limit=2)
        if not picking_types:
            raise ValidationError(
                _("Row %s: No incoming receipt operation type is configured for branch '%s'.")
                % (row_number, branch.name)
            )
        if len(picking_types) > 1:
            raise ValidationError(
                _("Row %s: More than one incoming receipt operation type is configured for branch '%s'.")
                % (row_number, branch.name)
            )
        return picking_types

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
        partner_model = self.env["res.partner"]
        company_domain = [
            ("name", "=", name),
            ("active", "=", True),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id),
        ]
        vendors = partner_model.search(
            company_domain + [("supplier_rank", ">", 0)], limit=2
        )
        if len(vendors) > 1:
            raise ValidationError(
                _("Row %s: Vendor '%s' is ambiguous; use a unique vendor name.")
                % (row_number, name)
            )
        if vendors:
            return vendors

        matching_partners = partner_model.search(company_domain, limit=2)
        if len(matching_partners) > 1:
            raise ValidationError(
                _("Row %s: Vendor '%s' matches multiple contacts; resolve the duplicate names first.")
                % (row_number, name)
            )
        if matching_partners:
            vendor = matching_partners
            vendor.write({"supplier_rank": max(vendor.supplier_rank, 1)})
            return vendor

        return partner_model.create({
            "name": name,
            "supplier_rank": 1,
            "company_id": self.company_id.id,
        })

    def _resolve_product(self, name, row_number):
        name = name.strip()
        normalized_name = " ".join(name.split()).casefold()
        product_model = self.env["product.product"]
        template_model = self.env["product.template"]
        company_scopes = (
            self.company_id.id,
            False,
        )
        for company_id in company_scopes:
            template_domain = [
                ("company_id", "=", company_id),
                ("active", "=", True),
                ("purchase_ok", "=", True),
            ]
            variant_scope_domain = [
                ("product_tmpl_id.company_id", "=", company_id),
                ("product_tmpl_id.active", "=", True),
                ("product_tmpl_id.purchase_ok", "=", True),
                ("active", "=", True),
            ]
            reference_matches = product_model.search(
                variant_scope_domain + [("default_code", "=", name)]
            )
            if reference_matches:
                if len(reference_matches) > 1:
                    raise ValidationError(
                        _("Row %s: Internal Reference '%s' matches multiple products.")
                        % (row_number, name)
                    )
                return reference_matches

            matching_templates = template_model.search(
                template_domain + [("name", "ilike", name)]
            ).filtered(
                lambda template: " ".join((template.name or "").split()).casefold()
                == normalized_name
            )
            products = matching_templates.product_variant_ids.filtered(
                lambda product: product.active
            )
            if products:
                if len(products) > 1:
                    raise ValidationError(
                        _(
                            "Row %s: Product '%s' matches multiple purchasable products. "
                            "Set a unique Internal Reference on the intended product and use "
                            "that reference in Excel, or archive the duplicate product."
                        )
                        % (row_number, name)
                    )
                return products

        raise ValidationError(
            _("Row %s: Purchasable product '%s' was not found. Check that it is active, "
              "enabled for purchase, and available to the selected company.")
            % (row_number, name)
        )

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
        groups = self._read_rows()
        companies = {group["company"].id for group in groups.values()}
        branches = {group["branch"].id for group in groups.values()}
        if len(companies) != 1:
            raise ValidationError(
                _("The workbook must contain expenses for one company only.")
            )
        if len(branches) != 1:
            raise ValidationError(
                _("The workbook must contain expenses for one branch only.")
            )
        company = groups[next(iter(groups))]["company"]
        branch = groups[next(iter(groups))]["branch"]
        if company != self.company_id:
            raise ValidationError(
                _("The selected company '%s' does not match the Company in the workbook ('%s').")
                % (self.company_id.name, company.name)
            )
        if (
            self.payment_journal_id.type not in ("bank", "cash")
            or self.payment_journal_id.company_id != company
            or not self.payment_journal_id.outbound_payment_method_line_ids
        ):
            raise ValidationError(
                _(
                    "Choose a bank or cash journal for this company with an "
                    "outbound payment method."
                )
            )
        if self.payment_journal_id.branch_id != branch:
            raise ValidationError(
                _(
                    "The selected payment journal must belong to workbook branch '%s'."
                )
                % branch.name
            )

        prepared = []
        for group in groups.values():
            first_row = group["row_number"]
            vendor = self._resolve_vendor(group["vendor_name"], first_row)
            if vendor.branch_id and vendor.branch_id != group["branch"]:
                raise ValidationError(
                    _("Row %(row)s: Vendor '%(vendor)s' belongs to branch '%(vendor_branch)s', "
                      "not workbook branch '%(branch)s'.")
                    % {
                        "row": first_row,
                        "vendor": vendor.display_name,
                        "vendor_branch": vendor.branch_id.name,
                        "branch": group["branch"].name,
                    }
                )
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
            duplicate_order = self.env["purchase.order"].search([
                ("partner_id", "=", vendor.id),
                ("company_id", "=", self.company_id.id),
                ("partner_ref", "=", group["reference"]),
                ("is_purchase_expense", "=", True),
                ("state", "!=", "cancel"),
            ], limit=1)
            if duplicate_order:
                raise ValidationError(
                    _(
                        "Purchase Expense Order '%(reference)s' already exists "
                        "for vendor '%(vendor)s'."
                    )
                    % {
                        "reference": group["reference"],
                        "vendor": group["vendor_name"],
                    }
                )

            purchase_lines = []
            for line in group["lines"]:
                product = self._resolve_product(line["product_name"], line["row_number"])
                if product.branch_id and product.branch_id != group["branch"]:
                    raise ValidationError(
                        _("Row %(row)s: Product '%(product)s' belongs to branch "
                          "'%(product_branch)s', not workbook branch '%(branch)s'.")
                        % {
                            "row": line["row_number"],
                            "product": product.display_name,
                            "product_branch": product.branch_id.name,
                            "branch": group["branch"].name,
                        }
                    )
                if product.detailed_type not in ("consu", "service"):
                    raise ValidationError(
                        _(
                            "Row %(row)s: Product '%(product)s' is not eligible for "
                            "a Purchase Expense order. Use a Consumable or Service product."
                        )
                        % {
                            "row": line["row_number"],
                            "product": product.display_name,
                        }
                    )
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
                purchase_lines.append({
                    "name": product.display_name,
                    "product_id": product.id,
                    "product_qty": line["quantity"],
                    "product_uom": product.uom_id.id,
                    "price_unit": line["price_unit"],
                    "taxes_id": [fields.Command.set(taxes.ids)],
                    "date_planned": fields.Datetime.to_datetime(group["bill_date"]),
                })
            prepared.append({
                "vendor": vendor,
                "company": group["company"],
                "branch": group["branch"],
                "picking_type": self._resolve_picking_type(group["branch"], first_row),
                "reference": group["reference"],
                "bill_date": group["bill_date"],
                "narration": "\n".join(group["narrations"]),
                "lines": purchase_lines,
            })
        return prepared

    def _validate_expense_receipts(self, purchase_order, bill_date):
        transfer_datetime = fields.Datetime.to_datetime(bill_date)
        accounting_date = fields.Date.to_string(bill_date)
        lines_to_receive = purchase_order.order_line.filtered(
            lambda line: line.qty_received_method == "stock_moves"
            and line.product_qty > line.qty_received
        )
        if not lines_to_receive:
            return

        pickings = lines_to_receive.mapped("move_ids.picking_id").filtered(
            lambda picking: picking.state not in ("done", "cancel")
        )
        lines_without_receipts = lines_to_receive.filtered(
            lambda line: not line.move_ids.filtered(
                lambda move: move.picking_id in pickings
            )
        )
        if lines_without_receipts:
            raise ValidationError(
                _(
                    "Could not create an incoming receipt for expense products: %s."
                )
                % ", ".join(lines_without_receipts.mapped("product_id.display_name"))
            )

        for picking in pickings:
            picking.scheduled_date = transfer_datetime
            receipt_moves = picking.move_ids.filtered(
                lambda move: move.purchase_line_id in lines_to_receive
                and move.state not in ("done", "cancel")
            )
            for move in receipt_moves:
                move.quantity = move.product_uom_qty

            result = picking.with_context(
                force_period_date=accounting_date
            ).button_validate()
            if isinstance(result, dict):
                if result.get("res_model") == "stock.backorder.confirmation":
                    wizard_context = dict(result.get("context", {}))
                    wizard_context["force_period_date"] = accounting_date
                    wizard = self.env[result["res_model"]].with_context(
                        **wizard_context,
                    ).create({})
                    wizard.process_cancel_backorder()
                else:
                    raise ValidationError(
                        _(
                            "Odoo requires an additional step to validate the "
                            "expense receipt %(receipt)s (%(step)s)."
                        )
                        % {
                            "receipt": picking.display_name,
                            "step": result.get("name") or result.get("res_model") or _("unknown"),
                        }
                    )

            if picking.state != "done":
                raise ValidationError(
                    _("Expense receipt %s was not validated.")
                    % picking.display_name
                )
            picking.write({"date_done": transfer_datetime})
            picking.move_ids.write({"date": transfer_datetime})
            picking.move_line_ids.write({"date": transfer_datetime})

        lines_to_receive.invalidate_recordset(
            ["qty_received", "qty_to_invoice"]
        )
        not_invoiceable = lines_to_receive.filtered(
            lambda line: line.qty_to_invoice <= 0
        )
        if not_invoiceable:
            raise ValidationError(
                _(
                    "The following expense products are still not invoiceable "
                    "after receipt: %s."
                )
                % ", ".join(not_invoiceable.mapped("product_id.display_name"))
            )

    def action_import(self):
        self.ensure_one()
        if self.import_completed:
            return self.action_view_purchase_orders()
        bills = self._prepare_import()
        payment_method_line = self.payment_journal_id.outbound_payment_method_line_ids[:1]
        purchase_orders = self.env["purchase.order"]
        can_approve_bills = (
            self.env.is_superuser()
            or self.env.user.has_group("base.group_system")
            or self.env.user.has_group("base.group_erp_manager")
            or bool(
                (manager_group := self.env.ref(
                    "em_jewellery_management.group_jewellery_manager",
                    raise_if_not_found=False,
                ))
                and manager_group in self.env.user.groups_id
            )
        )

        for bill_values in bills:
            purchase_order = self.env["purchase.order"].with_company(
                bill_values["company"]
            ).create({
                "partner_id": bill_values["vendor"].id,
                "company_id": bill_values["company"].id,
                "branch_id": bill_values["branch"].id,
                "picking_type_id": bill_values["picking_type"].id,
                "currency_id": bill_values["company"].currency_id.id,
                "date_order": fields.Datetime.to_datetime(bill_values["bill_date"]),
                "partner_ref": bill_values["reference"],
                "is_purchase_expense": True,
                "notes": (
                    "<p>%s</p>"
                    % "<br/>".join(
                        escape(line) for line in bill_values["narration"].splitlines()
                    )
                    if bill_values["narration"]
                    else False
                ),
                "order_line": [
                    fields.Command.create(line) for line in bill_values["lines"]
                ],
            })
            purchase_orders |= purchase_order

            purchase_order.button_confirm()
            purchase_order.picking_ids.write({"branch_id": bill_values["branch"].id})
            if purchase_order.state not in ("purchase", "done"):
                raise ValidationError(
                    _(
                        "Purchase Order for vendor '%(vendor)s' and reference "
                        "'%(reference)s' requires purchase-manager approval."
                    )
                    % {
                        "vendor": bill_values["vendor"].display_name,
                        "reference": bill_values["reference"],
                    }
                )

            self._validate_expense_receipts(
                purchase_order, bill_values["bill_date"]
            )
            purchase_order.action_create_invoice()
            bill = purchase_order.invoice_ids.filtered(
                lambda move: move.move_type == "in_invoice" and move.state == "draft"
            )[:1]
            if not bill:
                raise ValidationError(
                    _(
                        "No draft vendor bill was generated from Purchase Order "
                        "%s."
                    )
                    % purchase_order.display_name
                )
            bill.write({
                "invoice_date": bill_values["bill_date"],
                "ref": bill_values["reference"],
            })
            if "is_approved" in bill._fields and can_approve_bills:
                bill.write({"is_approved": True})
            bill.action_post()

            payment_register = self.env["account.payment.register"].with_company(
                bill_values["company"]
            ).with_context(
                active_model="account.move", active_ids=bill.ids
            ).create({
                "journal_id": self.payment_journal_id.id,
                "payment_method_line_id": payment_method_line.id,
                "payment_date": bill_values["bill_date"],
            })
            payment_register.action_create_payments()

        self.write({
            "imported_purchase_order_ids": [fields.Command.set(purchase_orders.ids)],
            "import_completed": True,
            "import_result": _(
                "%(count)s Purchase Order(s) created. Vendor bills were posted "
                "and paid successfully."
            ) % {"count": len(purchase_orders)},
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Imported Purchase Orders"),
            "res_model": self._name,
            "view_mode": "form",
            "views": [(self.env.ref(
                "purchase_expense_excel_import.view_purchase_expense_import_wizard_form"
            ).id, "form")],
            "res_id": self.id,
            "target": "new",
        }

    def action_view_purchase_orders(self):
        self.ensure_one()
        if not self.imported_purchase_order_ids:
            raise ValidationError(_("There are no imported Purchase Orders to show."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Imported Purchase Orders"),
            "res_model": "purchase.order",
            "view_mode": "tree,form",
            "domain": [("id", "in", self.imported_purchase_order_ids.ids)],
            "target": "current",
        }
