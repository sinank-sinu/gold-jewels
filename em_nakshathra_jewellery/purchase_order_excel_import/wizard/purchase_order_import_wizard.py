# -*- coding: utf-8 -*-

import base64
import io
from collections import OrderedDict
from datetime import datetime, date
from openpyxl import load_workbook
from odoo.tests.common import Form

from odoo import _, fields, models
from odoo.exceptions import ValidationError

import logging
_logger = logging.getLogger(__name__)


class PurchaseOrderImportWizard(models.TransientModel):
    _name = "purchase.order.import.wizard"
    _description = "Purchase Order Excel Import Wizard"

    file = fields.Binary(
        string="Excel File",
        required=True,
    )
    file_name = fields.Char()


    def _cell_value(self, value):
        if value is None:
            return False

        if isinstance(value, str):
            value = value.strip()

        return value

    def _float(self, value):
        if value in (None, "", False):
            return 0.0

        try:
            return float(value)
        except Exception:
            return 0.0

    def _date(self, value):
        if not value:
            return False

        if isinstance(value, datetime):
            return value

        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())

        if isinstance(value, str):
            value = value.strip()

            formats = (
                "%d.%m.%Y",
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%Y-%m-%d",
                "%m/%d/%Y",
                "%d.%m.%Y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
            )

            for fmt in formats:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue

        raise ValidationError(_("Invalid date format: %s") % value)

    # Search Methods

    def _find_vendor(self, vendor_name, row_no):

        if not vendor_name:
            raise ValidationError(
                _("Row %s : Vendor is required.") % row_no
            )

        Partner = self.env["res.partner"]

        vendor = Partner.search([
            ("name", "=", vendor_name),
            ("supplier_rank", ">=", 0),
        ], limit=1)

        if not vendor:
            vendor = Partner.create({
                "name": vendor_name,
                "supplier_rank": 1,
                "company_type": "company",
            })

        return vendor

    def _find_buyer(self, buyer_name, row_no):

        if not buyer_name:
            return False

        user = self.env["res.users"].search([
            ("name", "=", buyer_name)
        ], limit=1)

        if not user:
            raise ValidationError(
                _("Row %s : Buyer '%s' not found.")
                % (row_no, buyer_name)
            )

        return user

    def _find_branch(self, branch_name, row_no):

        if not branch_name:
            return False

        Branch = self.env["res.branch"]

        branch = Branch.search([
            ("name", "=", branch_name)
        ], limit=1)

        if not branch:
            branch = Branch.create({
                "name": branch_name,
                "company_id": 1,
                "branch_code": branch_name
            })

        return branch

    def _find_purity(self, purity_name, row_no):

        if not purity_name:
            return False

        Purity = self.env["gold.purity"]

        purity = Purity.search([
            ("name", "=", purity_name)
        ], limit=1)

        if not purity:
            purity = Purity.create({
                "name": purity_name,
            })

        return purity

    def _find_product(self, product_template_name, row_no):

        if not product_template_name:
            raise ValidationError(
                _("Row %s : Product Template is required.") % row_no
            )

        ProductTemplate = self.env["product.template"]

        template = ProductTemplate.search([
            ("name", "=", product_template_name)
        ], limit=1)

        if not template:
            template = ProductTemplate.create({
                "name": product_template_name,
                "purchase_ok": True,
                "sale_ok": True,
                "detailed_type": "product",
            })

        product = template.product_variant_id

        if not product:
            product = self.env["product.product"].create({
                "product_tmpl_id": template.id,
            })

        return product

    def _find_product_template(self, template_name):

        if not template_name:
            return False

        template = self.env["product.template"].search([
            ("name", "=", template_name)
        ], limit=1)

        return template

    def _find_uom(self, uom_name, row_no):

        if not uom_name:
            raise ValidationError(
                _("Row %s : Unit Of Measure is required.") % row_no
            )

        Uom = self.env["uom.uom"]

        uom = Uom.search([
            ("name", "=", uom_name)
        ], limit=1)

        if not uom:
            category = self.env.ref("uom.product_uom_categ_unit")

            uom = Uom.create({
                "name": uom_name,
                "category_id": category.id,
                "uom_type": "reference",
                "rounding": 0.01,
                "factor": 1.0,
            })

        return uom

    def _find_tax(self, tax_name):

        if not tax_name:
            return [(5, 0, 0)]

        tax = self.env["account.tax"].search([
            ("name", "=", tax_name),
            ("type_tax_use", "in", ["purchase", "none"])
        ], limit=1)

        if not tax:
            return [(5, 0, 0)]

        return [(6, 0, tax.ids)]

    # Prepare Purchase Order

    def _prepare_purchase_order_vals(
            self,
            row,
            vendor,
            buyer,
            branch,
            company,
            order_deadline,
            order_reference,
    ):

        vals = {
            "partner_id": vendor.id,
            "origin": order_reference,
        }

        if buyer:
            vals["user_id"] = buyer.id

        if branch and "branch_id" in self.env["purchase.order"]._fields:
            vals["branch_id"] = branch.id

        if company:
            company_rec = self.env["res.company"].search(
                [("name", "=", company)],
                limit=1,
            )
            if company_rec:
                vals["company_id"] = company_rec.id

        if order_deadline:
            vals["date_order"] = order_deadline

        return vals

    # Prepare Purchase Order Line

    def _prepare_purchase_order_line_vals(
            self,
            order,
            row,
            product,
            product_template,
            purity,
            uom,
            taxes,
    ):

        vals = {
            "order_id": order.id,
            "product_id": product.id,
            "name": product.display_name,
            "product_qty": self._float(
                row["Order Lines/Quantity"]
            ),
            "product_uom": uom.id,
            "price_unit": self._float(
                row["Order Lines/Unit Price"]
            ),
            "taxes_id": taxes,
        }



        if (
                product_template
                and "product_template_id"
                in self.env["purchase.order.line"]._fields
        ):
            vals["product_template_id"] = product_template.id



        if purity:
            vals["purity_id"] = purity.id



        vals.update({
            "gross_weight":
                self._float(
                    row["Order Lines/Gross Weight (g)"]
                ),

            "net_weight":
                self._float(
                    row["Order Lines/Net Weight (g)"]
                ),

            "stone_weight":
                self._float(
                    row["Order Lines/Stone Weight (g)"]
                ),

            "diamond_weight_gm":
                self._float(
                    row["Order Lines/Diamond Weight (g)"]
                ),

            "gold_rate":
                self._float(
                    row["Order Lines/Rate(g)"]
                ),

            "purchase_price_per_gram":
                self._float(
                    row["Order Lines/Rate(g)"]
                ),

            "purchase_making_charge_type": (
                "percent"
                if row["Purchase Making Charge Type"] == "Percentage"
                else "amount"
                if row["Purchase Making Charge Type"] == "Amount"
                else "rate_per_gram"
                if row["Purchase Making Charge Type"] == "Rate Per Gram"
                else "percent"
            ),

            "purchase_making_charge_value":
                self._float(
                    row["Purchase Making Charge"]
                ),

            "purchase_making_charge_amount":
                self._float(
                    row["Purchase Making Charge Amount"]
                ),

            "stone_rate":
                self._float(
                    row["Stone Amount"]
                ),

            "diamond_rate":
                self._float(
                    row["Diamond Amount"]
                ),

            "rate_value":
                self._float(
                    row["Order Lines/Rate(g)"]
                ),
        })

        return vals


    def _create_purchase_order(
            self,
            row,
    ):

        vendor = self._find_vendor(
            row["Vendor"],
            row["row_no"],
        )

        buyer = self._find_buyer(
            row["Buyer"],
            row["row_no"],
        )

        branch = self._find_branch(
            row["Branch"],
            row["row_no"],
        )

        order = self.env["purchase.order"].create(

            self._prepare_purchase_order_vals(
                row=row,
                vendor=vendor,
                buyer=buyer,
                branch=branch,
                company=row["Company"],
                order_deadline=self._date(
                    row["Order Deadline"]
                ),
                order_reference=row["Order Reference"],
            )
        )

        return order

    def _create_purchase_order_line(
            self,
            order,
            row,
    ):

        template_name = row["Order Lines/Product Template"]

        product = self._find_product(
            template_name,
            row["row_no"],
        )

        template = product.product_tmpl_id

        # template = self._find_product_template(
        #     row["Order Lines/Product Template"]
        # )

        purity = self._find_purity(
            row["Purity"],
            row["row_no"],
        )

        uom = self._find_uom(
            row["Order Lines/Unit of Measure"],
            row["row_no"],
        )
        if product.uom_id.category_id != uom.category_id:
            product.product_tmpl_id.write({
                "uom_id": uom.id,
                "uom_po_id": uom.id,
            })

        taxes = self._find_tax(
            row["Order Lines/Taxes 3% GST"]
        )

        self.env["purchase.order.line"].create(

            self._prepare_purchase_order_line_vals(
                order=order,
                row=row,
                product=product,
                product_template=template,
                purity=purity,
                uom=uom,
                taxes=taxes,
            )

        )


    # Import

    def action_import(self):

        self.ensure_one()

        if not self.file:
            raise ValidationError(_("Please upload an Excel file."))

        try:
            workbook = load_workbook(
                filename=io.BytesIO(base64.b64decode(self.file)),
                data_only=True,
            )
        except Exception as e:
            raise ValidationError(
                _("Unable to read Excel file.\n%s") % str(e)
            )

        sheet = workbook.active

        headers = []

        for cell in sheet[1]:
            headers.append(str(cell.value).strip() if cell.value else "")

        required_columns = [
            "Buyer",
            "Company",
            "Order Deadline",
            "Order Reference",
            "Vendor",
            "Branch",
            "Order Lines/Product",
            "Order Lines/Product Template",
            "Purity",
            "Order Lines/Quantity",
            "Order Lines/Unit of Measure",
            "Order Lines/Gross Weight (g)",
            "Order Lines/Net Weight (g)",
            "Order Lines/Stone Weight (g)",
            "Order Lines/Diamond Weight (g)",
            "Order Lines/Rate(g)",
            "Purchase Making Charge Type",
            "Purchase Making Charge",
            "Purchase Making Charge Amount",
            "Stone Amount",
            "Diamond Amount",
            "Order Lines/Taxes 3% GST",
            "Order Lines/Unit Price",
        ]

        missing = []

        for column in required_columns:
            if column not in headers:
                missing.append(column)

        if missing:
            raise ValidationError(
                _(
                    "Following columns are missing:\n\n%s"
                ) % ("\n".join(missing))
            )

        grouped_orders = OrderedDict()

        for excel_row_no, row in enumerate(
                sheet.iter_rows(min_row=2, values_only=True),
                start=2,
        ):

            values = {}

            for index, header in enumerate(headers):
                values[header] = self._cell_value(row[index])

            values["row_no"] = excel_row_no

            # ------------------------------------------
            # Mandatory Validation
            # ------------------------------------------

            mandatory = {
                "Vendor": values["Vendor"],
                "Order Reference": values["Order Reference"],
                "Order Lines/Product": values["Order Lines/Product Template"],
                "Order Lines/Quantity": values["Order Lines/Quantity"],
                "Order Lines/Unit Price": values["Order Lines/Unit Price"],
            }

            for label, value in mandatory.items():
                if value in (False, None, ""):
                    raise ValidationError(
                        _(
                            "Row %s : '%s' is mandatory."
                        )
                        % (
                            excel_row_no,
                            label,
                        )
                    )

            order_ref = values["Order Reference"]

            if order_ref not in grouped_orders:
                grouped_orders[order_ref] = {
                    "header": values,
                    "lines": [],
                }

            grouped_orders[order_ref]["lines"].append(values)

        PurchaseOrder = self.env["purchase.order"]

        created_orders = PurchaseOrder.browse()

        for reference, data in grouped_orders.items():

            header = data["header"]

            order = PurchaseOrder.search(
                [
                    ("origin", "=", reference),
                    ("partner_id.name", "=", header["Vendor"]),
                ],
                limit=1,
            )

            # Skip if already confirmed/done
            if order and order.state in ("purchase", "done"):
                _logger.info(
                    "Purchase Order %s is already confirmed. Skipping import.",
                    reference,
                )
                continue

            # Create Purchase Order if not found
            if not order:
                order = self._create_purchase_order(header)

            # Create Purchase Order Lines
            for line in data["lines"]:
                self._create_purchase_order_line(order, line)

            # Confirm Purchase Order
            if order.state in ("draft", "sent"):
                order.button_confirm()
                for picking in order.picking_ids:
                    if picking.state not in ("done", "cancel"):
                        picking.action_assign()

                        for move in picking.move_ids_without_package:
                            move.quantity = move.product_uom_qty

                        picking.button_validate()
                for line in order.order_line:
                    _logger.info(
                        "Product=%s | Ordered=%s | Received=%s | To Invoice=%s | Invoice Policy=%s",
                        line.product_id.display_name,
                        line.product_qty,
                        line.qty_received,
                        line.qty_to_invoice,
                        line.product_id.purchase_method,
                    )

            # Create Vendor Bill
            f = Form(
                self.env["account.move"].with_context(
                    default_move_type="in_invoice",
                    default_is_approved=True
                )
            )

            f.partner_id = order.partner_id
            f.invoice_date = fields.Date.context_today(self)

            f.purchase_vendor_bill_id = self.env[
                "purchase.bill.union"
            ].browse(-order.id)

            bill = f.save()
            if bill.state == "draft":


                bill.action_post()

            # Register Bank Payment
            bank_amount = self._float(header.get("Bank"))

            if bank_amount > 0:

                journal = self.env["account.journal"].search(
                    [
                        ("type", "=", "bank"),
                    ],
                    limit=1,
                )

                if not journal:
                    raise ValidationError(_("No Bank Journal found."))

                payment_register = self.env[
                    "account.payment.register"
                ].with_context(
                    active_model="account.move",
                    active_ids=bill.ids,
                ).create({
                    "journal_id": journal.id,
                    "payment_date": fields.Date.context_today(self),
                    "amount": bill.amount_total,
                })

                payment_register.action_create_payments()

            created_orders |= order

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _(
                    "%s Purchase Orders imported successfully."
                ) % len(created_orders),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window_close",
                },
            },
        }
