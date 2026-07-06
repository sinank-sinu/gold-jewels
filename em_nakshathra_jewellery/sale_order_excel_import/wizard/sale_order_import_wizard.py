# -*- coding: utf-8 -*-

import base64
import io
import os
from datetime import datetime

from openpyxl import load_workbook
import xlrd

from odoo import models, fields, _
from odoo.exceptions import ValidationError


class SaleOrderImportWizard(models.TransientModel):
    _name = "sale.order.import.wizard"
    _description = "Sale Order Excel Import Wizard"

    def _to_float(self, value):
        if value in (None, False, ""):
            return 0.0

        try:
            return float(value)
        except Exception:
            return 0.0

    excel_file = fields.Binary(
        string="Excel File",
        required=True
    )

    file_name = fields.Char(
        string="Filename"
    )

    def action_import(self):
        """
        Main Import Method
        """
        self.ensure_one()

        if not self.excel_file:
            raise ValidationError(_("Please upload an Excel file."))

        extension = os.path.splitext(
            self.file_name or ""
        )[1].lower()

        file_data = base64.b64decode(self.excel_file)

        if extension == ".xlsx":
            rows = self._read_xlsx(file_data)

        elif extension == ".xls":
            rows = self._read_xls(file_data)

        else:
            raise ValidationError(
                _("Only .xls and .xlsx files are supported.")
            )

        self._process_rows(rows)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Import Completed"),
                "message": _("Sale Orders imported successfully."),
                "sticky": False,
                "type": "success",
            },
        }

    # XLSX Reader

    def _read_xlsx(self, file_data):

        workbook = load_workbook(
            filename=io.BytesIO(file_data),
            data_only=True
        )

        sheet = workbook.active

        headers = []

        for cell in sheet[1]:
            headers.append(
                str(cell.value).strip() if cell.value else ""
            )

        rows = []

        for row in sheet.iter_rows(min_row=2, values_only=True):

            values = {}

            for index, value in enumerate(row):
                key = headers[index]

                values[key] = value

            rows.append(values)

        return rows

    # XLS Reader

    def _read_xls(self, file_data):

        workbook = xlrd.open_workbook(
            file_contents=file_data
        )

        sheet = workbook.sheet_by_index(0)

        headers = []

        for col in range(sheet.ncols):
            headers.append(
                str(sheet.cell_value(0, col)).strip()
            )

        rows = []
        for row_no in range(1, sheet.nrows):

            row_values = sheet.row_values(row_no)

            # Skip completely empty rows
            if all(str(cell).strip() == "" for cell in row_values):
                continue

            values = {}

            for col in range(sheet.ncols):
                values[headers[col]] = sheet.cell_value(row_no, col)

            rows.append(values)

        return rows


    def _process_rows(self, rows):

        Partner = self.env['res.partner']
        User = self.env['res.users']
        Branch = self.env['res.branch']
        Purity = self.env['gold.purity']
        Product = self.env['product.product']
        SaleOrder = self.env['sale.order']

        errors = []

        # Always use this product
        advance_product = Product.search([
            ('name', '=', 'Advance Product')
        ], limit=1)

        if not advance_product:
            raise ValidationError(
                _("Product 'Advance Product' does not exist.")
            )

        for row_no, row in enumerate(rows, start=2):

            try:

            # Customer

                customer_name = (
                        row.get("Customer")
                        or row.get("Customer Name")
                        or ""
                )

                customer_name = str(customer_name).strip()
                if not customer_name:
                    continue

                # if not customer_name:
                #     raise ValidationError(
                #         _("Customer is empty.")
                #     )

                partner = Partner.search([
                    ('name', '=', customer_name)
                ], limit=1)

                if not partner:
                    partner = Partner.create({
                        'name': customer_name,
                        'customer_rank': 1,
                    })
                order_date = row.get("Order Date")

                if isinstance(order_date, str):
                    order_date = order_date.strip()
                    if order_date:
                        order_date = datetime.strptime(order_date, "%m/%d/%Y")
                elif not order_date:
                    order_date = False

                # ----------------------------------------
                # Salesperson
                # ----------------------------------------

                salesperson_name = (
                        row.get("Salesperson")
                        or ""
                )

                salesperson_name = str(
                    salesperson_name
                ).strip()

                user = False

                if salesperson_name:

                    user = User.search([
                        ('name', '=', salesperson_name)
                    ], limit=1)

                    if not user:
                        user = False
                    #     raise ValidationError(
                    #         _("Salesperson '%s' not found.")
                    #         % salesperson_name
                    #     )

                # ----------------------------------------
                # Branch
                # ----------------------------------------

                branch_name = (
                        row.get("Branch")
                        or ""
                )

                branch_name = str(branch_name).strip()

                if not branch_name:
                    raise ValidationError(
                        _("Branch is empty.")
                    )

                branch = Branch.search([
                    ('name', '=', branch_name)
                ], limit=1)

                if not branch:
                    branch = False
                    # raise ValidationError(
                    #     _("Branch '%s' not found.")
                    #     % branch_name
                    # )

                # ----------------------------------------
                # Purity
                # ----------------------------------------

                purity_name = (
                        row.get("Order Lines/Purity")
                        or row.get("Purity")
                        or ""
                )

                purity_name = str(
                    purity_name
                ).strip()

                if not purity_name:
                    raise ValidationError(
                        _("Purity is empty.")
                    )

                purity = Purity.search([
                    ('name', '=', purity_name)
                ], limit=1)

                if not purity:
                    raise ValidationError(
                        _("Purity '%s' not found.")
                        % purity_name
                    )

                # ----------------------------------------
                # Read Excel Values
                # ----------------------------------------

                origin = (
                        row.get("Order Reference")
                        or ""
                )

                gold_rate = float(
                    row.get("Order Lines/Gold Rate(g)")
                    or 0
                )

                quantity = float(
                    row.get("Order Lines/Quantity")
                    or 1
                )

                net_weight = float(
                    row.get("Order Lines/Net Weight (g)")
                    or 0
                )

                stone_weight = float(
                    row.get("Order Lines/Stone Weight (g)")
                    or 0
                )

                diamond_weight = float(
                    row.get("Order Lines/Diamond Weight (g)")
                    or 0
                )

                stone_rate = float(
                    row.get("Order Lines/Stone Amt")
                    or 0
                )

                diamond_rate = float(
                    row.get("Order Lines/Diamond Amt")
                    or 0
                )

                self._create_sale_order(
                    partner,
                    user,
                    order_date,
                    branch,
                    purity,
                    advance_product,
                    origin,
                    quantity,
                    gold_rate,
                    net_weight,
                    stone_weight,
                    diamond_weight,
                    stone_rate,
                    diamond_rate, row
                )

            except Exception as e:

                errors.append(
                    _("Row %s : %s") % (
                        row_no,
                        str(e)
                    )
                )

            if errors:
                raise ValidationError(
                    "\n".join(errors)
                )

    # Create Sale Order

    def _create_sale_order(
            self,
            partner,
            user,
            order_date,
            branch,
            purity,
            product,
            origin,
            quantity,
            gold_rate,
            net_weight,
            stone_weight,
            diamond_weight,
            stone_rate,
            diamond_rate,
            row
    ):

        SaleOrder = self.env["sale.order"]

        order = SaleOrder.create({
            "partner_id": partner.id,
            "date_order": order_date,
            "user_id": user.id if user else False,
            "branch_id": branch.id if branch else False,
            "origin": origin,
        })
        order.date_order = order_date

        self.env["sale.order.line"].create({
            "order_id": order.id,

            "product_id": product.id,
            "name": product.display_name,

            "product_uom_qty": quantity,
            "purity_id": purity.id,

            "gold_rate": gold_rate,
            "price_unit": gold_rate,

            "net_weight": net_weight,

            "sale_stone_weight": stone_weight,

            "sale_diamond_weight_gm": diamond_weight,

            "sale_stone_rate": stone_rate,

            "sale_diamond_rate": diamond_rate,
        })
        order.action_confirm()
        order.date_order = order_date

        invoices = order._create_invoices()


        for invoice in invoices:
            invoice.invoice_date = order.date_order.date()
            invoice.date = order.date_order.date()

            if invoice.state == "draft":
                invoice.action_post()

        self._create_excel_payments(order, invoices, row)

        return order

    def _create_excel_payments(self, order, invoices, row):
        payment_data = [
            ("Bank", "bank"),
            ("Cash", "cash"),
            ("UPI", "bank"),
            ("Card", "bank"),
        ]

        for column_name, journal_type in payment_data:

            amount = self._to_float(row.get(column_name))

            if amount <= 0:
                continue

            journal = self.env["account.journal"].search([
                ("type", "=", journal_type),
                ("company_id", "=", order.company_id.id),
            ], limit=1)

            if not journal:
                raise ValidationError(
                    _("No %s journal found.") % journal_type.capitalize()
                )

            payment = self.env["account.payment"].create({
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": order.partner_id.id,
                "amount": amount,
                "currency_id": order.currency_id.id,
                "journal_id": journal.id,
                "sale_id": order.id,
                "date": order.date_order.date() if order.date_order else fields.Date.today(),
                "ref": order.name,
            })

            payment.action_post()

            for invoice in invoices:

                receivable_lines = (
                        payment.move_id.line_ids +
                        invoice.line_ids
                ).filtered(
                    lambda line: (
                            line.account_id.account_type == 'asset_receivable'
                            and not line.reconciled
                    )
                )

                if receivable_lines:
                    receivable_lines.reconcile()
