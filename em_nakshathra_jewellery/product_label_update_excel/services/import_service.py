import base64
import io
import logging

from openpyxl import load_workbook
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductLabelImportService:

    def __init__(self, env):
        self.env = env(su=True)

    def process_import(self, file_base64):
        """
        UPDATE EXISTING PRODUCT LABELS ONLY.

        Label matching is ONLY based on:

            1. Company
            2. Barcode
            3. Label Name

        No verification is done for:

            - Product
            - Product Template
            - Purity
            - Branch
            - Source Location
            - Destination Location
            - Purchase Order
            - Sale Order
            - Weights
            - Stock
            - Any other label field

        Only purchase charge fields are updated.
        """

        updated = 0
        failed_labels = []

        _logger.info("=" * 100)
        _logger.info("PRODUCT LABEL PURCHASE CHARGE UPDATE STARTED")
        _logger.info("=" * 100)

        # ---------------------------------------------------------
        # DECODE EXCEL FILE
        # ---------------------------------------------------------

        try:
            file_content = base64.b64decode(file_base64)
        except Exception as e:
            raise UserError(
                f"Could not decode uploaded Excel file: {e}"
            )

        try:
            wb = load_workbook(
                io.BytesIO(file_content),
                data_only=True,
                read_only=True,
            )
        except Exception as e:
            raise UserError(
                f"Could not open Excel file: {e}"
            )

        sheet = wb.active

        # ---------------------------------------------------------
        # READ EXCEL HEADERS
        # ---------------------------------------------------------

        header_row = next(
            sheet.iter_rows(
                min_row=1,
                max_row=1,
                values_only=True,
            )
        )

        raw_headers = [
            str(value).strip() if value is not None else f"Col_{idx}"
            for idx, value in enumerate(header_row)
        ]

        # Handle duplicate Excel headers.
        headers = []
        counts = {}

        for header in raw_headers:

            if header in counts:
                counts[header] += 1
                headers.append(
                    f"{header}_{counts[header]}"
                )

            else:
                counts[header] = 0
                headers.append(header)

        # ---------------------------------------------------------
        # HELPER: GET EXCEL VALUE
        # ---------------------------------------------------------

        def get_val(row_dict, column_name):

            for key, value in row_dict.items():

                if str(key).strip().lower() == column_name.lower():
                    return value

            return None

        # ---------------------------------------------------------
        # HELPER: CONVERT VALUE TO FLOAT
        # ---------------------------------------------------------

        def get_float(row_dict, column_name):

            value = get_val(
                row_dict,
                column_name,
            )

            if value is None:
                return 0.0

            if str(value).strip() == "":
                return 0.0

            try:

                return float(
                    str(value)
                    .replace(",", "")
                    .strip()
                )

            except (TypeError, ValueError):

                raise UserError(
                    f"Invalid numeric value '{value}' "
                    f"in column '{column_name}'."
                )

        # ---------------------------------------------------------
        # HELPER: NORMALIZE BARCODE
        # ---------------------------------------------------------

        def normalize_barcode(value):

            if value is None:
                return ""

            # Excel numeric barcode:
            # 12345.0 -> 12345
            if isinstance(value, float):

                if value.is_integer():
                    return str(int(value))

            value = str(value).strip()

            # String barcode:
            # "12345.0" -> "12345"
            if value.endswith(".0"):
                value = value[:-2]

            return value

        # ---------------------------------------------------------
        # PROCESS EACH EXCEL ROW
        # ---------------------------------------------------------

        try:

            for row_idx, row in enumerate(
                sheet.iter_rows(
                    min_row=2,
                    values_only=True,
                ),
                start=2,
            ):

                # Skip completely empty rows.
                if not any(row):
                    continue

                row_dict = dict(
                    zip(headers, row)
                )

                company_name = ""
                label_name = ""
                barcode = ""

                try:

                    with self.env.cr.savepoint():

                        # =================================================
                        # 1. COMPANY
                        # =================================================

                        company_name = str(
                            get_val(
                                row_dict,
                                "Company",
                            ) or ""
                        ).strip()

                        if not company_name:

                            raise UserError(
                                f"Company is empty on row "
                                f"{row_idx}."
                            )

                        company = self.env[
                            "res.company"
                        ].search(
                            [
                                (
                                    "name",
                                    "=ilike",
                                    company_name,
                                )
                            ],
                            limit=1,
                        )

                        if not company:

                            raise UserError(
                                f"Company '{company_name}' "
                                f"was not found in Odoo "
                                f"on row {row_idx}."
                            )

                        _logger.info(
                            "Row %s: Company matched: "
                            "%s (ID: %s)",
                            row_idx,
                            company.name,
                            company.id,
                        )

                        # =================================================
                        # 2. LABEL NAME
                        # =================================================

                        label_name = str(
                            get_val(
                                row_dict,
                                "Label Name",
                            ) or ""
                        ).strip()

                        if not label_name:

                            raise UserError(
                                f"Label Name is empty "
                                f"on row {row_idx}."
                            )

                        # =================================================
                        # 3. BARCODE
                        # =================================================

                        barcode = normalize_barcode(
                            get_val(
                                row_dict,
                                "Barcode",
                            )
                        )

                        if not barcode:

                            raise UserError(
                                f"Barcode is empty on row "
                                f"{row_idx}."
                            )

                        _logger.info(
                            "Row %s: Searching existing "
                            "label | Company=%s | "
                            "Barcode=%s | Label Name=%s",
                            row_idx,
                            company.name,
                            barcode,
                            label_name,
                        )

                        # =================================================
                        # 4. FIND EXISTING LABEL
                        #
                        # ONLY THREE CONDITIONS:
                        #
                        # company_id
                        # barcode
                        # label_name
                        #
                        # NOTHING ELSE.
                        # =================================================

                        labels = self.env["product.label"].with_context(
                            active_test=False
                        ).search([
                            ("company_id", "=", company.id),
                            ("barcode", "=", barcode),
                            ("label_name", "=", label_name),
                        ])

                        # -------------------------------------------------
                        # LABEL NOT FOUND
                        # -------------------------------------------------

                        if not labels:

                            raise UserError(
                                "Existing label not found.\n\n"
                                f"Company     : {company.name}\n"
                                f"Barcode     : {barcode}\n"
                                f"Label Name  : {label_name}"
                            )

                        # -------------------------------------------------
                        # DUPLICATE LABEL
                        # -------------------------------------------------

                        if len(labels) > 1:

                            raise UserError(
                                "Multiple existing labels found.\n\n"
                                f"Company     : {company.name}\n"
                                f"Barcode     : {barcode}\n"
                                f"Label Name  : {label_name}\n\n"
                                "Update skipped to prevent "
                                "updating the wrong label."
                            )

                        label = labels[0]

                        _logger.info(
                            "Row %s: Existing label found "
                            "| ID=%s | Name=%s | Barcode=%s",
                            row_idx,
                            label.id,
                            label.label_name,
                            label.barcode,
                        )

                        # =================================================
                        # 5. PURCHASE MAKING CHARGE
                        # =================================================

                        purchase_mc_type_raw = str(
                            get_val(
                                row_dict,
                                "Purchase Making Charge Type",
                            ) or ""
                        ).strip()

                        purchase_mc_type = (
                            self._map_mc_type(
                                purchase_mc_type_raw
                            )
                        )

                        # Purchase Making Charge
                        purchase_mc_value = get_float(
                            row_dict,
                            "Purchase Making Charge",
                        )

                        # Purchase Making Charge Amount
                        purchase_mc_amount = get_float(
                            row_dict,
                            "Purchase Making Charge Amount",
                        )

                        # Purchase Stone Amount
                        purchase_stone_amount = get_float(
                            row_dict,
                            "Purchase Stone Amount",
                        )

                        # Purchase Diamond Amount
                        purchase_diamond_amount = get_float(
                            row_dict,
                            "Purchase Diamond Amount",
                        )

                        _logger.info(
                            "Row %s: Excel values | "
                            "PMC Type=%s | "
                            "PMC=%s | "
                            "PMC Amount=%s | "
                            "Stone=%s | "
                            "Diamond=%s",
                            row_idx,
                            purchase_mc_type,
                            purchase_mc_value,
                            purchase_mc_amount,
                            purchase_stone_amount,
                            purchase_diamond_amount,
                        )

                        # =================================================
                        # 6. DETERMINE PURCHASE MAKING CHARGE VALUE
                        # =================================================

                        if (
                            purchase_mc_type == "amount"
                            and purchase_mc_amount
                        ):

                            final_pmc_value = (
                                purchase_mc_amount
                            )

                        else:

                            final_pmc_value = (
                                purchase_mc_value
                            )

                        # =================================================
                        # 7. UPDATE ONLY PURCHASE FIELDS
                        # =================================================
                        #
                        # IMPORTANT:
                        #
                        # We intentionally DO NOT write:
                        #
                        # product_id
                        # product_tmpl_id
                        # company_id
                        # branch_id
                        # source_location_id
                        # branch_location_id
                        # purchase_id
                        # barcode
                        # label_name
                        # purity_id
                        # weights
                        # sale fields
                        # stock fields
                        #
                        # ONLY these purchase fields are changed.
                        # =================================================

                        label.write({

                            "purchase_making_charge_value":
                                final_pmc_value,

                            "purchase_stone_rate":
                                purchase_stone_amount,

                            "purchase_diamond_rate":
                                purchase_diamond_amount,

                        })

                        # =================================================
                        # 8. RECOMPUTE PURCHASE MAKING CHARGE AMOUNT
                        # =================================================
                        #
                        # According to your existing import code,
                        # purchase_making_charge_amount is computed.
                        #
                        # Therefore we update the source field
                        # purchase_making_charge_value and let Odoo
                        # calculate purchase_making_charge_amount.
                        # =================================================

                        label.invalidate_recordset(
                            [
                                "purchase_making_charge_amount",
                            ]
                        )

                        # Force reading the computed value.
                        computed_amount = (
                            label.purchase_making_charge_amount
                        )

                        # =================================================
                        # 9. LOG RESULT
                        # =================================================

                        _logger.info(
                            "LABEL UPDATED SUCCESSFULLY"
                        )

                        _logger.info(
                            "Label ID              : %s",
                            label.id,
                        )

                        _logger.info(
                            "Company               : %s",
                            company.name,
                        )

                        _logger.info(
                            "Barcode               : %s",
                            barcode,
                        )

                        _logger.info(
                            "Label Name            : %s",
                            label_name,
                        )

                        _logger.info(
                            "Purchase MC Value     : %s",
                            label.purchase_making_charge_value,
                        )

                        _logger.info(
                            "Purchase MC Amount    : %s",
                            computed_amount,
                        )

                        _logger.info(
                            "Purchase Stone Amount : %s",
                            label.purchase_stone_rate,
                        )

                        _logger.info(
                            "Purchase Diamond Amount: %s",
                            label.purchase_diamond_rate,
                        )

                        updated += 1

                except Exception as e:

                    failed_labels.append({

                        "row": row_idx,

                        "company": company_name,

                        "barcode": barcode,

                        "label": label_name,

                        "reason": str(e),

                    })

                    _logger.error(
                        "FAILED ROW %s | "
                        "Company=%s | "
                        "Barcode=%s | "
                        "Label=%s | "
                        "Reason=%s",
                        row_idx,
                        company_name,
                        barcode,
                        label_name,
                        e,
                    )

        finally:

            wb.close()

        # =============================================================
        # FINAL LOG
        # =============================================================

        _logger.info("=" * 100)

        _logger.info(
            "PRODUCT LABEL PURCHASE CHARGE UPDATE COMPLETED"
        )

        _logger.info(
            "Updated Records : %s",
            updated,
        )

        _logger.info(
            "Failed Records  : %s",
            len(failed_labels),
        )

        _logger.info("=" * 100)

        # Log failed rows.
        if failed_labels:

            _logger.info(
                "FAILED RECORD DETAILS:"
            )

            for rec in failed_labels:

                _logger.info(
                    "Row=%s | Company=%s | "
                    "Barcode=%s | Label=%s | Reason=%s",
                    rec["row"],
                    rec["company"],
                    rec["barcode"],
                    rec["label"],
                    rec["reason"],
                )

        return {
            "updated": updated,
            "failed": len(failed_labels),
            "total_processed": (
                updated + len(failed_labels)
            ),
            "failed_labels": failed_labels,
        }

    def _map_mc_type(self, raw_val):

        val = str(
            raw_val or ""
        ).strip().lower()

        if (
            "rate" in val
            or "per gram" in val
        ):
            return "rate_per_gram"

        elif (
            "percent" in val
            or "%" in val
        ):
            return "percent"

        elif "amount" in val:
            return "amount"

        return "percent"