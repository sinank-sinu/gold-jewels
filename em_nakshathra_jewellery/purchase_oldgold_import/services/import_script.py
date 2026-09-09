import base64
import io
import logging
import re

from datetime import datetime
from collections import defaultdict

import openpyxl

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ImportLabelService:

    def __init__(self, env):
        self.env = env

    # ============================================================
    # CHART OF ACCOUNTS
    # ============================================================

    def _ensure_chart_of_accounts(self, company):

        _logger.info(
            "Checking Chart of Accounts for company %s",
            company.name
        )

        account = self.env['account.account'].search([
            ('company_id', '=', company.id)
        ], limit=1)

        if account:
            return

        template = self.env['account.chart.template'].search([
            ('country_id', '=', company.country_id.id)
        ], limit=1)

        if not template:
            raise UserError(
                _("No Chart of Accounts template found for company '%s'.")
                % company.name
            )

        _logger.info(
            "Loading Chart of Accounts '%s' for company '%s'",
            template.name,
            company.name
        )

        template.try_loading(company)

        accounts = self.env['account.account'].search_count([
            ('company_id', '=', company.id)
        ])

        _logger.info(
            "Company %s has %s accounts after loading.",
            company.name,
            accounts
        )

    # ============================================================
    # TAX
    # ============================================================

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

    # ============================================================
    # IMPORT
    # ============================================================

    def process_import(self, file_base64):

        _logger.info("Starting Purchase Label Bulk Import...")
        _logger.info("Upload started")

        try:

            file_content = base64.b64decode(file_base64)

            wb = openpyxl.load_workbook(
                io.BytesIO(file_content),
                data_only=True
            )

            sheet = wb.active

            # ----------------------------------------------------
            # READ HEADERS
            # ----------------------------------------------------

            headers = [
                str(cell.value).strip() if cell.value else ''
                for cell in sheet[1]
            ]

            _logger.info("Headers: %s", headers)

            # ----------------------------------------------------
            # GROUP ROWS BY BILL REFERENCE
            # ----------------------------------------------------

            grouped_data = defaultdict(list)

            for row_idx, row in enumerate(
                    sheet.iter_rows(min_row=2, values_only=True),
                    start=2):

                if not row[0] and not any(row):
                    continue

                row_dict = dict(zip(headers, row))

                vendor_ref = row_dict.get('Purchase Order')
                bill_date = row_dict.get('Bill Date')

                if not vendor_ref:
                    continue

                if isinstance(bill_date, datetime):

                    date_str = bill_date.strftime('%Y-%m-%d')

                else:

                    date_str = (
                        str(bill_date).split(' ')[0]
                        if bill_date
                        else datetime.now().strftime('%Y-%m-%d')
                    )

                bill_ref = str(
                    row_dict.get("Bill Reference") or ""
                ).strip()

                grouped_data[bill_ref].append(row_dict)

            _logger.info(
                "Found %s unique Purchase Orders.",
                len(grouped_data)
            )

            count = 0
            failed_records = []

            # ----------------------------------------------------
            # PROCESS EACH BILL
            # ----------------------------------------------------

            for bill_ref, lines in grouped_data.items():

                vendor_name = str(
                    lines[0].get("Purchase Order") or ""
                ).strip()

                bill_date = lines[0].get("Bill Date")

                if isinstance(bill_date, datetime):

                    date_str = bill_date.strftime('%Y-%m-%d')

                else:

                    date_str = (
                        str(bill_date).split(" ")[0]
                        if bill_date
                        else datetime.now().strftime('%Y-%m-%d')
                    )

                try:

                    self._process_po_group(
                        vendor_name,
                        bill_ref,
                        date_str,
                        lines
                    )

                    count += 1

                    if count % 10 == 0:

                        self.env.cr.commit()

                        _logger.info(
                            "Processed %s POs...",
                            count
                        )

                except Exception as e:

                    self.env.cr.rollback()

                    _logger.exception(
                        "Failed processing Bill Reference %s",
                        bill_ref
                    )

                    failed_records.append(
                        f"Bill Reference: {bill_ref}\n"
                        f"Vendor: {vendor_name}\n"
                        f"Reason: {str(e)}"
                    )

                    continue

            self.env.cr.commit()

            if failed_records:

                raise UserError(
                    "Import completed with the following failures:\n\n"
                    + "\n\n".join(failed_records)
                )

            _logger.info(
                "Purchase Label Bulk Import Completed Successfully!"
            )

        except Exception as e:

            _logger.error(
                "Error during import: %s",
                str(e),
                exc_info=True
            )

            self.env.cr.rollback()

            raise

    # ============================================================
    # PROCESS PURCHASE ORDER
    # ============================================================

    def _process_po_group(
            self,
            vendor_name,
            bill_ref,
            date_str,
            lines):

        if not lines:
            return

        # ========================================================
        # 0. COMPANY
        # ========================================================

        company_names = set(
            str(line.get('Company')).strip()
            for line in lines
            if line.get('Company')
        )

        if not company_names:

            raise UserError(
                f"No Company specified in Excel for Purchase Order "
                f"{bill_ref}"
            )

        if len(company_names) > 1:

            raise UserError(
                f"Multiple companies found in Excel for Purchase Order "
                f"{bill_ref}: {company_names}. "
                f"All rows in a PO must belong to the same company."
            )

        company_name = company_names.pop()

        current_company = self.env['res.company'].search([
            ('name', '=', company_name)
        ], limit=1)

        if not current_company:

            raise UserError(
                f"Company '{company_name}' from Excel not found in Odoo."
            )

        # ========================================================
        # 1. VENDOR
        # ========================================================

        partner = self.env['res.partner'].search([
            '|',
            ('name', '=', vendor_name),
            ('ref', '=', vendor_name)
        ], limit=1)

        if not partner:

            partner = self.env['res.partner'].create({
                'name': vendor_name,
                'supplier_rank': 1,
                'company_id': False,
            })

        elif partner.company_id:

            try:
                partner.company_id = False
            except Exception:
                pass

        # ========================================================
        # PAYABLE ACCOUNT
        # ========================================================

        payable_account = self.env['account.account'].search([
            ('company_id', '=', current_company.id),
            ('account_type', '=', 'liability_payable'),
        ], limit=1)

        if not payable_account:

            raise UserError(
                "No Payable account found for company '%s'."
                % current_company.name
            )

        partner.with_company(
            current_company
        ).property_account_payable_id = payable_account.id

        # ========================================================
        # 2. CREATE PURCHASE ORDER
        # ========================================================

        po_vals = {
            'partner_id': partner.id,
            'date_order': date_str,
            'partner_ref': bill_ref,
            'company_id': current_company.id,
            'is_old_gold': True,
        }

        branch_name = lines[0].get('Branch') if lines else None

        if branch_name:
            branch = self.env['res.branch'].search([
                ('name', '=', str(branch_name).strip())
            ], limit=1)

            if branch:
                po_vals['branch_id'] = branch.id

        po = self.env['purchase.order'].create(po_vals)

        _logger.info(
            "Created OLD GOLD Purchase Order %s for Bill Reference %s",
            po.name,
            bill_ref
        )

        # ========================================================
        # LOCATIONS
        # ========================================================

        source_location = None
        dest_location = None

        # ========================================================
        # 3. PURCHASE ORDER LINES
        # ========================================================

        for line in lines:

            product = self._resolve_product(
                line,
                current_company
            )

            if not product:
                continue

            tax_name = str(
                line.get("Order Lines/Taxes") or ""
            ).strip()

            tax = False

            if tax_name in ["3% GST", "18% GST"]:

                tax = self.env["account.tax"].search([
                    ("name", "=", tax_name),
                    ("type_tax_use", "in", ["purchase", "none"]),
                    ("company_id", "=", current_company.id),
                ], limit=1)

            qty = float(
                line.get('Order Lines/Quantity')
                or line.get('Quantity')
                or 1.0
            )

            price = float(
                line.get('Order Lines/Unit Price')
                or line.get('Unit Price')
                or 0.0
            )

            weight = float(
                line.get('Weight')
                or line.get('Gross Weight')
                or line.get('Weight (g)')
                or line.get('Weight in grams')
                or 0.0
            )

            gold_rate_val = str(
                line.get("Fine Rate") or ""
            ).strip()

            try:

                gold_rate = float(gold_rate_val)

            except (ValueError, TypeError):

                gold_rate = 0.0

            # ----------------------------------------------------
            # PURITY
            # ----------------------------------------------------

            purity_id = False

            purity_name = line.get('Purity')

            if purity_name:

                purity = self.env['gold.purity'].search([
                    ('name', '=', str(purity_name).strip())
                ], limit=1)

                if purity:
                    purity_id = purity.id

            # ----------------------------------------------------
            # LOCATIONS
            # ----------------------------------------------------

            if not source_location and (
                    line.get('Source Location')
                    or line.get('Src Location')):

                source_location = str(
                    line.get('Source Location')
                    or line.get('Src Location')
                ).strip()

            if not dest_location and (
                    line.get('Destination Location')
                    or line.get('Dest Location')):

                dest_location = str(
                    line.get('Destination Location')
                    or line.get('Dest Location')
                ).strip()

            # ----------------------------------------------------
            # PO LINE
            # ----------------------------------------------------

            po_line_vals = {
                'order_id': po.id,
                'product_id': product.id,
                'name': product.name,
                'product_qty': qty,
                'price_unit': price,
                'gross_weight': weight,
                'product_uom': product.uom_id.id,
                'date_planned': date_str,
                'gold_rate': gold_rate,
                'taxes_id': (
                    [(6, 0, [tax.id])]
                    if tax
                    else [(5, 0, 0)]
                ),
            }

            if purity_id:
                po_line_vals['purity_id'] = purity_id

            self.env['purchase.order.line'].create(
                po_line_vals
            )

        # ========================================================
        # 4. CONFIRM PO
        # ========================================================

        po.button_confirm()

        po.write({
            'date_approve': date_str,
            'date_planned': date_str,
            'unfix': False,
        })

        # ========================================================
        # 5. VALIDATE RECEIPT
        # ========================================================

        if po.picking_ids:

            src_loc = None

            if source_location:

                src_loc = self.env['stock.location'].search([
                    ('complete_name', '=', source_location)
                ], limit=1)

                if not src_loc:

                    src_loc = self.env['stock.location'].search([
                        ('name', '=', source_location)
                    ], limit=1)

            dst_loc = None

            if dest_location:

                dst_loc = self.env['stock.location'].search([
                    ('complete_name', '=', dest_location)
                ], limit=1)

                if not dst_loc:

                    dst_loc = self.env['stock.location'].search([
                        ('name', '=', dest_location)
                    ], limit=1)

            for picking in po.picking_ids.filtered(
                    lambda p: p.state not in ['done', 'cancel']):

                if src_loc:
                    picking.location_id = src_loc.id

                if dst_loc:
                    picking.location_dest_id = dst_loc.id

                for move in picking.move_ids:

                    if src_loc:
                        move.location_id = src_loc.id

                    if dst_loc:
                        move.location_dest_id = dst_loc.id

                    for move_line in move.move_line_ids:

                        if src_loc:
                            move_line.location_id = src_loc.id

                        if dst_loc:
                            move_line.location_dest_id = dst_loc.id

                # ------------------------------------------------
                # SET QUANTITY
                # ------------------------------------------------

                for move in picking.move_ids:

                    move.quantity = move.product_uom_qty

                picking.scheduled_date = date_str

                picking.button_validate()

                picking.write({
                    'date_done': date_str
                })

                picking.move_ids.write({
                    'date': date_str
                })

                picking.move_line_ids.write({
                    'date': date_str
                })

        # ========================================================
        # 6. PURCHASE JOURNAL
        # ========================================================

        if po.branch_id:

            journal = self.env['account.journal'].search([
                ('type', '=', 'purchase'),
                ('company_id', '=', po.company_id.id),
                ('branch_id', '=', po.branch_id.id),
            ], limit=1)

            if not journal:

                code = (
                    "PUR%s" % po.branch_id.id
                )[:5].upper()

                while self.env['account.journal'].search([
                    ('code', '=', code),
                    ('company_id', '=', po.company_id.id)
                ], limit=1):

                    code = (
                        "P%s%s"
                        % (
                            po.branch_id.id,
                            len(code)
                        )
                    )[:5].upper()

                journal = self.env['account.journal'].create({
                    'name': '%s Purchase' % po.branch_id.name,
                    'code': code,
                    'type': 'purchase',
                    'company_id': po.company_id.id,
                    'branch_id': po.branch_id.id,
                })

        # ========================================================
        # 7. ENSURE ACCOUNTS
        # ========================================================

        self._ensure_chart_of_accounts(
            po.company_id
        )

        # ========================================================
        # 8. CREATE VENDOR BILL
        # ========================================================

        po.action_create_invoice()

        # --------------------------------------------------------
        # FIND CREATED BILL
        # --------------------------------------------------------

        bill = po.invoice_ids.filtered(
            lambda inv: inv.move_type == 'in_invoice'
        )[:1]

        if not bill:

            raise UserError(
                "Vendor bill was not created for Purchase Order %s."
                % po.name
            )



        # ========================================================
        # 10. POST BILL
        # ========================================================

        if bill.state == 'draft':

            bill.action_post()

        # ========================================================
        # 11. REGISTER PAYMENT
        # ========================================================

        self._register_old_gold_payment(
            bill,
            lines,
            current_company
        )

    # ============================================================
    # OLD GOLD PAYMENT
    # ============================================================

    def _register_old_gold_payment(
            self,
            bill,
            lines,
            company):

        """
        Register OLD GOLD payment(s) for one vendor bill.

        Payment information is taken from ALL Excel rows belonging
        to the same Bill Reference.

        Cases:
            Cash only -> one Cash payment
            Bank only -> one Bank payment
            Cash + Bank -> two payments against the same bill

        A small rounding difference between the Excel payment total
        and Odoo's bill residual is tolerated up to 0.10 and the
        final payment is reduced to Odoo's actual residual.
        """

        # ============================================================
        # VALIDATION
        # ============================================================

        if not bill:
            raise UserError(
                "Cannot register payment because vendor bill was not created."
            )

        if not isinstance(lines, list):
            raise UserError(
                "Payment processing expected a list of Excel rows "
                "but received '%s'."
                % type(lines).__name__
            )

        if not lines:
            raise UserError(
                "No Excel rows found for Bill '%s'."
                % bill.name
            )

        # ============================================================
        # POST BILL
        # ============================================================

        if bill.state == 'draft':
            bill.action_post()

        bill.invalidate_recordset([
            'amount_residual',
            'payment_state',
            'amount_total',
        ])

        if bill.payment_state == 'paid' or abs(bill.amount_residual) <= 0.0001:
            _logger.info(
                "Bill %s is already fully paid. Skipping payment.",
                bill.name,
            )
            return

        # ============================================================
        # HELPERS
        # ============================================================

        def to_float(value):
            if value in (None, '', False):
                return 0.0

            if isinstance(value, bool):
                return 0.0

            try:
                value = str(value).strip()
                value = value.replace(',', '')
                value = value.replace('₹', '')
                value = value.replace('$', '')
                return float(value)
            except (ValueError, TypeError):
                return 0.0

        def is_true(value):
            if value in (None, '', False):
                return False

            if isinstance(value, bool):
                return value

            value = str(value).strip().lower()
            return value in (
                'true',
                'yes',
                'y',
                '1',
                'cash',
                'bank',
            )

        # ============================================================
        # COLLECT PAYMENT DATA FROM ALL ROWS
        # ============================================================

        cash_amount = 0.0
        bank_amount = 0.0

        cash_found = False
        bank_found = False

        bank_journals = set()
        bank_references = set()

        for line in lines:

            if not isinstance(line, dict):
                raise UserError(
                    "Invalid Excel row for Bill '%s'. "
                    "Expected dictionary but received '%s'."
                    % (
                        bill.name,
                        type(line).__name__,
                    )
                )

            # --------------------------------------------------------
            # CASH
            # --------------------------------------------------------

            cash_value = line.get('Cash')

            if cash_value not in (None, '', False):

                if isinstance(cash_value, bool):
                    if cash_value:
                        cash_found = True
                else:
                    cash_text = str(cash_value).strip().lower()

                    if cash_text in (
                        'true',
                        'yes',
                        'y',
                        'cash',
                    ):
                        cash_found = True
                    else:
                        amount = to_float(cash_value)
                        if amount > 0:
                            cash_amount += amount
                            cash_found = True

            # --------------------------------------------------------
            # BANK AMOUNT
            # --------------------------------------------------------

            bank_amount_value = line.get('Bank Amount')

            if bank_amount_value not in (None, '', False):
                amount = to_float(bank_amount_value)

                if amount > 0:
                    bank_amount += amount
                    bank_found = True

            # --------------------------------------------------------
            # BANK
            # --------------------------------------------------------

            bank_value = line.get('Bank')

            if bank_value not in (None, '', False):

                if is_true(bank_value):
                    bank_found = True
                else:
                    amount = to_float(bank_value)

                    if amount > 0:
                        bank_amount += amount
                        bank_found = True

            # --------------------------------------------------------
            # BANK JOURNAL
            # --------------------------------------------------------

            bank_journal_value = line.get('Bank Journal')

            if bank_journal_value:
                bank_journals.add(
                    str(bank_journal_value).strip()
                )
                bank_found = True

            # --------------------------------------------------------
            # BANK REFERENCE
            # --------------------------------------------------------

            bank_reference_value = line.get('Bank Reference')

            if bank_reference_value:
                bank_references.add(
                    str(bank_reference_value).strip()
                )

        # ============================================================
        # LOG
        # ============================================================

        _logger.info("====================================================")
        _logger.info("OLD GOLD PAYMENT INFORMATION")
        _logger.info("Bill          : %s", bill.name)
        _logger.info("Cash Found    : %s", cash_found)
        _logger.info("Cash Amount   : %.2f", cash_amount)
        _logger.info("Bank Found    : %s", bank_found)
        _logger.info("Bank Amount   : %.2f", bank_amount)
        _logger.info("Bank Journals : %s", bank_journals)
        _logger.info("Bank Refs     : %s", bank_references)
        _logger.info("====================================================")

        if not cash_found and not bank_found:
            raise UserError(
                "No Cash or Bank payment information found "
                "in Excel for Bill '%s'."
                % bill.name
            )

        # ============================================================
        # PAYMENT DATE / REFERENCES
        # ============================================================

        payment_date = (
            bill.invoice_date
            or fields.Date.context_today(self.env.user)
        )

        default_reference = (
            bill.ref
            or bill.name
            or bill.partner_id.name
        )

        bank_reference = ', '.join(sorted(bank_references))
        if not bank_reference:
            bank_reference = default_reference

        # ============================================================
        # 1. CASH PAYMENT
        # ============================================================

        if cash_amount > 0:

            cash_journal = self.env['account.journal'].search([
                ('company_id', '=', company.id),
                ('type', '=', 'cash'),
            ], order='id', limit=1)

            if not cash_journal:
                raise UserError(
                    "No Cash journal found for company '%s'."
                    % company.name
                )

            bill.invalidate_recordset([
                'amount_residual',
                'payment_state',
            ])

            residual_before_cash = abs(bill.amount_residual)

            if residual_before_cash <= 0:
                raise UserError(
                    "Bill '%s' has no remaining amount "
                    "to register Cash payment."
                    % bill.name
                )

            if cash_amount > residual_before_cash + 0.10:
                raise UserError(
                    "Cash payment exceeds bill residual.\n\n"
                    "Bill: %s\n"
                    "Bill Residual: %.2f\n"
                    "Cash Amount: %.2f"
                    % (
                        bill.name,
                        residual_before_cash,
                        cash_amount,
                    )
                )

            # If the Cash amount is only slightly above Odoo's residual,
            # use Odoo's residual rather than failing on a rounding issue.
            if cash_amount > residual_before_cash:
                _logger.warning(
                    "Small Cash rounding difference for Bill %s: "
                    "Excel=%.2f Odoo=%.2f Difference=%.2f. "
                    "Using Odoo residual.",
                    bill.name,
                    cash_amount,
                    residual_before_cash,
                    cash_amount - residual_before_cash,
                )
                cash_amount = residual_before_cash

            _logger.info(
                "Creating CASH payment for Bill %s: %.2f",
                bill.name,
                cash_amount,
            )

            payment_register = self.env[
                'account.payment.register'
            ].with_context(
                active_model='account.move',
                active_ids=bill.ids,
            ).create({
                'journal_id': cash_journal.id,
                'amount': cash_amount,
                'payment_date': payment_date,
            })

            if 'communication' in payment_register._fields:
                payment_register.write({
                    'communication': default_reference,
                })
            elif 'payment_ref' in payment_register._fields:
                payment_register.write({
                    'payment_ref': default_reference,
                })

            payment_register.action_create_payments()

            bill.invalidate_recordset([
                'amount_residual',
                'payment_state',
            ])

            _logger.info(
                "CASH PAYMENT CREATED | Bill=%s | Journal=%s | "
                "Amount=%.2f | Remaining=%.2f",
                bill.name,
                cash_journal.name,
                cash_amount,
                abs(bill.amount_residual),
            )

        # ============================================================
        # 2. BANK PAYMENT
        # ============================================================

        if bank_amount > 0:

            bank_journal = False

            if len(bank_journals) == 1:

                journal_name = list(bank_journals)[0]

                bank_journal = self.env['account.journal'].search([
                    ('company_id', '=', company.id),
                    ('type', '=', 'bank'),
                    ('name', '=', journal_name),
                ], limit=1)

                if not bank_journal:
                    bank_journal = self.env['account.journal'].search([
                        ('company_id', '=', company.id),
                        ('type', '=', 'bank'),
                        ('code', '=', journal_name),
                    ], limit=1)

                if not bank_journal:
                    raise UserError(
                        "Bank Journal '%s' from Excel was not found "
                        "for company '%s'."
                        % (
                            journal_name,
                            company.name,
                        )
                    )

            elif len(bank_journals) > 1:

                raise UserError(
                    "Multiple Bank Journals found for Bill '%s'.\n\n%s"
                    % (
                        bill.name,
                        '\n'.join(sorted(bank_journals)),
                    )
                )

            else:

                bank_journal = self.env['account.journal'].search([
                    ('company_id', '=', company.id),
                    ('type', '=', 'bank'),
                ], order='id', limit=1)

            if not bank_journal:
                raise UserError(
                    "No Bank journal found for company '%s'."
                    % company.name
                )

            # --------------------------------------------------------
            # Refresh after Cash payment
            # --------------------------------------------------------

            bill.invalidate_recordset([
                'amount_residual',
                'payment_state',
            ])

            residual_before_bank = abs(bill.amount_residual)

            if residual_before_bank <= 0:
                raise UserError(
                    "Bill '%s' has no remaining amount "
                    "to register Bank payment."
                    % bill.name
                )

            difference = bank_amount - residual_before_bank

            # --------------------------------------------------------
            # Rounding tolerance
            # --------------------------------------------------------
            # Example:
            # Excel Bank = 629011.99
            # Odoo       = 629011.91
            # Difference =       0.08
            #
            # Treat small differences as rounding and pay Odoo's
            # actual residual so that the bill becomes fully paid.
            # --------------------------------------------------------

            if difference > 0:

                if difference <= 0.10:

                    _logger.warning(
                        "Small Bank rounding difference for Bill %s: "
                        "Excel Bank=%.2f, Odoo Residual=%.2f, "
                        "Difference=%.2f. "
                        "Using Odoo residual for final Bank payment.",
                        bill.name,
                        bank_amount,
                        residual_before_bank,
                        difference,
                    )

                    bank_amount = residual_before_bank

                else:

                    raise UserError(
                        "Bank payment exceeds remaining bill amount.\n\n"
                        "Bill: %s\n"
                        "Remaining Bill Amount: %.2f\n"
                        "Bank Amount from Excel: %.2f\n"
                        "Difference: %.2f"
                        % (
                            bill.name,
                            residual_before_bank,
                            bank_amount,
                            difference,
                        )
                    )

            # --------------------------------------------------------
            # Bank amount cannot be zero
            # --------------------------------------------------------

            if bank_amount <= 0:
                raise UserError(
                    "Bank payment amount is zero for Bill '%s'."
                    % bill.name
                )

            _logger.info(
                "Creating BANK payment for Bill %s: %.2f using journal %s",
                bill.name,
                bank_amount,
                bank_journal.name,
            )

            payment_register = self.env[
                'account.payment.register'
            ].with_context(
                active_model='account.move',
                active_ids=bill.ids,
            ).create({
                'journal_id': bank_journal.id,
                'amount': bank_amount,
                'payment_date': payment_date,
            })

            if 'communication' in payment_register._fields:
                payment_register.write({
                    'communication': bank_reference,
                })
            elif 'payment_ref' in payment_register._fields:
                payment_register.write({
                    'payment_ref': bank_reference,
                })

            payment_register.action_create_payments()

            bill.invalidate_recordset([
                'amount_residual',
                'payment_state',
            ])

            _logger.info(
                "BANK PAYMENT CREATED | Bill=%s | Journal=%s | "
                "Amount=%.2f | Remaining=%.2f",
                bill.name,
                bank_journal.name,
                bank_amount,
                abs(bill.amount_residual),
            )

        # ============================================================
        # FINAL STATUS
        # ============================================================

        bill.invalidate_recordset([
            'amount_residual',
            'payment_state',
        ])

        _logger.info(
            "OLD GOLD PAYMENT PROCESS COMPLETED | Bill=%s | "
            "Payment State=%s | Residual=%.2f",
            bill.name,
            bill.payment_state,
            abs(bill.amount_residual),
        )

    def _create_old_gold_payment(
            self,
            bill,
            journal,
            amount,
            payment_date,
            reference):

        if amount <= 0:
            return

        # ------------------------------------------------------------
        # Refresh bill after any previous payment
        # ------------------------------------------------------------

        bill.invalidate_recordset([
            'amount_residual',
            'payment_state',
        ])

        residual = abs(bill.amount_residual)

        if residual <= 0:
            _logger.info(
                "Bill %s has no remaining amount to pay.",
                bill.name
            )
            return

        # ------------------------------------------------------------
        # Never try to pay more than remaining residual
        # ------------------------------------------------------------

        amount = min(
            float(amount),
            residual
        )

        if amount <= 0:
            return

        _logger.info(
            "Creating OLD GOLD payment: "
            "Bill=%s Journal=%s Amount=%s Residual=%s",
            bill.name,
            journal.name,
            amount,
            residual,
        )

        # ------------------------------------------------------------
        # Register payment
        # ------------------------------------------------------------

        payment_register = self.env[
            'account.payment.register'
        ].with_context(
            active_model='account.move',
            active_ids=bill.ids,
        ).create({
            'journal_id': journal.id,
            'amount': amount,
            'payment_date': payment_date,
        })

        # ------------------------------------------------------------
        # Reference
        # ------------------------------------------------------------

        if 'communication' in payment_register._fields:

            payment_register.write({
                'communication': reference,
            })

        elif 'payment_ref' in payment_register._fields:

            payment_register.write({
                'payment_ref': reference,
            })

        # ------------------------------------------------------------
        # Create payment
        # ------------------------------------------------------------

        payment_register.action_create_payments()

        # ------------------------------------------------------------
        # Refresh after payment
        # ------------------------------------------------------------

        bill.invalidate_recordset([
            'amount_residual',
            'payment_state',
        ])

        _logger.info(
            "OLD GOLD PAYMENT CREATED: "
            "Bill=%s Journal=%s Amount=%s Remaining=%s",
            bill.name,
            journal.name,
            amount,
            bill.amount_residual,
        )

    # ============================================================
    # PRODUCT RESOLUTION
    # ============================================================

    def _resolve_product(
            self,
            row,
            current_company):

        _logger.info("ROW = %s", row)
        _logger.info("ROW KEYS = %s", list(row.keys()))

        # --------------------------------------------------------
        # CACHE
        # --------------------------------------------------------

        if not hasattr(self, 'variant_cache'):

            self.variant_cache = {}
            self.template_cache = {}
            self.attribute_cache = {}
            self.attribute_value_cache = {}

        # --------------------------------------------------------
        # GET COLUMN
        # --------------------------------------------------------

        def get_col(name):

            for k, v in row.items():

                if str(k).strip().upper() == name.upper():

                    return v

            return None

        # --------------------------------------------------------
        # ATTRIBUTES
        # --------------------------------------------------------

        attrs = {
            'TYPE': str(
                get_col('TYPE') or ''
            ).strip().title(),

            'VARIETY': str(
                get_col('VARIETY') or ''
            ).strip().title(),

            'DESIGN': str(
                get_col('DESIGN')
                or get_col('DESIGN SIZE')
                or ''
            ).strip().title(),

            'SIZE': str(
                get_col('SIZE') or ''
            ).strip().title(),

            'STONE COLOUR': str(
                get_col('STONE COLOUR') or ''
            ).strip().title(),

            'METAL COLOUR': str(
                get_col('METAL COLOUR') or ''
            ).strip().title(),
        }

        for k, v in attrs.items():

            if v.upper() in ('FALSE', ''):

                attrs[k] = 'None'

        # --------------------------------------------------------
        # PRODUCT NAME
        # --------------------------------------------------------

        raw_name = str(
            row.get('Product') or ''
        )

        template_name = re.sub(
            r'\s+',
            ' ',
            raw_name
        ).strip()

        if not template_name:

            return None

        # --------------------------------------------------------
        # CACHE KEY
        # --------------------------------------------------------

        cache_key = (
            current_company.id,
            template_name,
            attrs['TYPE'],
            attrs['VARIETY'],
            attrs['DESIGN'],
            attrs['SIZE'],
            attrs['STONE COLOUR'],
            attrs['METAL COLOUR']
        )

        if cache_key in self.variant_cache:

            return self.variant_cache[cache_key]

        template_cache_key = (
            current_company.id,
            template_name.lower()
        )

        # ========================================================
        # FIND TEMPLATE
        # ========================================================

        if template_cache_key in self.template_cache:

            template = self.template_cache[
                template_cache_key
            ]

        else:

            TemplateModel = self.env[
                'product.template'
            ].with_context(
                active_test=False
            )

            first_word = (
                template_name.split('(')[0].strip()
                if '(' in template_name
                else template_name
            )

            domain = [
                ('name', 'ilike', first_word),
                (
                    'company_id',
                    'in',
                    [current_company.id, False]
                )
            ]

            all_templates = TemplateModel.search(
                domain
            )

            matched_templates = []

            excel_name_norm = re.sub(
                r'\s+',
                '',
                template_name
            ).upper()

            for t in all_templates:

                db_name_norm = re.sub(
                    r'\s+',
                    '',
                    str(t.name or '')
                ).upper()

                if db_name_norm == excel_name_norm:

                    matched_templates.append(t)

            if matched_templates:

                matched_templates.sort(
                    key=lambda t: (
                        0
                        if t.company_id
                        and t.company_id.id
                        == current_company.id
                        else 1,
                        t.id
                    )
                )

                template = matched_templates[0]

            else:

                service_products = {
                    "OLD GOLD",
                    "18KTD OLD GOLD",

                }

                if template_name.strip().upper() in service_products:

                    template = self.env[
                        "product.template"
                    ].search([
                        (
                            "name",
                            "=ilike",
                            template_name
                        ),
                        (
                            "company_id",
                            "in",
                            [current_company.id, False]
                        ),
                    ], limit=1)

                    if not template:

                        template = self.env[
                            "product.template"
                        ].create({
                            "name": template_name,
                            "type": "service",
                            "purchase_ok": True,
                            "sale_ok": False,
                            "company_id": current_company.id,
                        })

                    variant = template.product_variant_id

                    self.template_cache[
                        template_cache_key
                    ] = template

                    self.variant_cache[
                        cache_key
                    ] = variant

                    return variant

                raise UserError(
                    "Product Template '%s' not found "
                    "for company '%s'. Import aborted."
                    % (
                        template_name,
                        current_company.name
                    )
                )

            assert template.exists()

            self.template_cache[
                template_cache_key
            ] = template

        # ========================================================
        # SERVICE PRODUCT
        # ========================================================

        if template.type == "service":

            variant = template.product_variant_id

            self.variant_cache[
                cache_key
            ] = variant

            return variant

        # ========================================================
        # RESOLVE ATTRIBUTES
        # ========================================================

        ptav_ids = []

        for attr_name, attr_val in attrs.items():

            ptal = template.attribute_line_ids.filtered(
                lambda l:
                (l.attribute_id.name or '').strip().lower()
                ==
                (attr_name or '').strip().lower()
            )[:1]

            if not ptal:

                raise UserError(
                    _(
                        "Attribute '%s' is not configured "
                        "on template '%s'."
                    )
                    % (
                        attr_name,
                        template.display_name
                    )
                )

            values = self.env[
                "product.attribute.value"
            ].search([
                (
                    "attribute_id",
                    "=",
                    ptal.attribute_id.id
                ),
            ])

            def normalize_attr(val):

                val = str(
                    val or ''
                ).strip().lower()

                val = re.sub(
                    r"\s+",
                    " ",
                    val
                )

                val = re.sub(
                    r"\s*-\s*",
                    "-",
                    val
                )

                val = val.replace(
                    "“",
                    '"'
                ).replace(
                    "”",
                    '"'
                )

                val = re.sub(
                    r'\s*"\s*',
                    '"',
                    val
                )

                return val

            value = values.filtered(
                lambda v:
                normalize_attr(v.name)
                ==
                normalize_attr(attr_val)
            )[:1]

            if not value:

                value = self.env[
                    "product.attribute.value"
                ].create({
                    "name": str(attr_val).strip(),
                    "attribute_id": ptal.attribute_id.id,
                })

            if value not in ptal.value_ids:

                ptal.write({
                    "value_ids": [
                        (4, value.id)
                    ]
                })

                self.env.flush_all()
                self.env.invalidate_all()

            ptav = self.env[
                "product.template.attribute.value"
            ].search([
                (
                    "attribute_line_id",
                    "=",
                    ptal.id
                ),
                (
                    "product_attribute_value_id",
                    "=",
                    value.id
                ),
            ], limit=1)

            if not ptav:

                raise UserError(
                    _(
                        "Unable to configure attribute "
                        "'%s' value '%s'."
                    )
                    % (
                        attr_name,
                        attr_val
                    )
                )

            ptav_ids.append(ptav.id)

        # ========================================================
        # EXACT VARIANT MATCH
        # ========================================================

        target_ptav_set = set(ptav_ids)

        exact_variant = False

        for variant in template.product_variant_ids:

            if (
                variant.company_id
                and variant.company_id != current_company
            ):
                continue

            if set(
                variant.product_template_attribute_value_ids.ids
            ) == target_ptav_set:

                exact_variant = variant
                break

        # ========================================================
        # CREATE VARIANT
        # ========================================================

        if not exact_variant:

            exact_variant = self.env[
                "product.product"
            ].create({
                "product_tmpl_id": template.id,
                "product_template_attribute_value_ids": [
                    (6, 0, ptav_ids)
                ],
            })

            _logger.info(
                "Created Variant %s (%s)",
                exact_variant.display_name,
                exact_variant.id
            )

        # ========================================================
        # CACHE
        # ========================================================

        self.variant_cache[
            cache_key
        ] = exact_variant

        return exact_variant