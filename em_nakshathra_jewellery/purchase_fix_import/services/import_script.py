# -*- coding: utf-8 -*-
import base64
import io
import logging
from datetime import datetime
from collections import defaultdict
import openpyxl
from odoo.exceptions import UserError
import re
from odoo.tests.common import Form

from odoo import _, fields, models
import pytz

_logger = logging.getLogger(__name__)


class ImportLabelService:
    def __init__(self, env):
        self.env = env


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

    def process_import(self, file_base64):
        _logger.info("Starting Purchase Label Bulk Import...")
        _logger.info("Upload started")

        try:
            file_content = base64.b64decode(file_base64)
            _logger.info("File size: %s bytes", len(file_content))

            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
            sheet = wb.active

            # Read Headers
            headers = [str(cell.value).strip() if cell.value else '' for cell in sheet[1]]
            _logger.info(f"Headers: {headers}")

            # Group rows by Purchase Order (Vendor) and Bill Date
            grouped_data = defaultdict(list)

            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                if not row[0] and not any(row):
                    continue  # Skip empty rows

                row_dict = dict(zip(headers, row))

                vendor_ref = row_dict.get('Purchase Order')
                bill_date = row_dict.get('Bill Date')

                if not vendor_ref:
                    continue

                if isinstance(bill_date, datetime):
                    date_str = bill_date.strftime('%Y-%m-%d')
                else:
                    date_str = str(bill_date).split(' ')[0] if bill_date else datetime.now().strftime('%Y-%m-%d')

                bill_ref = str(row_dict.get("Bill Reference") or "").strip()

                # Group only by Bill Reference
                key = bill_ref

                grouped_data[key].append(row_dict)

            _logger.info(f"Found {len(grouped_data)} unique Purchase Orders.")

            count = 0
            failed_records = []
            # Process each group
            for bill_ref, lines in grouped_data.items():

                vendor_name = str(lines[0].get("Purchase Order") or "").strip()

                bill_date = lines[0].get("Bill Date")

                if isinstance(bill_date, datetime):
                    date_str = bill_date.strftime("%Y-%m-%d")
                else:
                    date_str = (
                        str(bill_date).split(" ")[0]
                        if bill_date
                        else datetime.now().strftime("%Y-%m-%d")
                    )

                # self._process_po_group(vendor_name, bill_ref, date_str, lines)
                # count += 1
                # if count % 10 == 0:
                #     self.env.cr.commit()
                #     _logger.info(f"Processed {count} POs...")
                try:
                    self._process_po_group(vendor_name, bill_ref, date_str, lines)

                    count += 1

                    if count % 10 == 0:
                        self.env.cr.commit()
                        _logger.info(f"Processed {count} POs...")

                except Exception as e:
                    self.env.cr.rollback()

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

            _logger.info("Purchase Label Bulk Import Completed Successfully!")
            _logger.info("===== PROCESS IMPORT FINISHED =====")

        except Exception as e:
            _logger.error(f"Error during import: {str(e)}", exc_info=True)
            self.env.cr.rollback()

    def _process_po_group(self, vendor_name, bill_ref, date_str, lines):
        if not lines:
            return

        # 0. Resolve Migration Company from Excel
        company_names = set(str(line.get('Company')).strip() for line in lines if line.get('Company'))
        if not company_names:
            raise UserError(f"No Company specified in Excel for Purchase Order {bill_ref}")
        if len(company_names) > 1:
            raise UserError(
                f"Multiple companies found in Excel for Purchase Order {bill_ref}: {company_names}. All rows in a PO must belong to the same company.")

        company_name = company_names.pop()
        current_company = self.env['res.company'].search([('name', '=', company_name)], limit=1)
        if not current_company:
            raise UserError(f"Company '{company_name}' from Excel not found in Odoo.")


        # 1. Resolve Vendor
        partner = self.env['res.partner'].search(['|', ('name', '=', vendor_name), ('ref', '=', vendor_name)], limit=1)
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

        # --------------------------------------------------------------
        # Ensure vendor has the correct Creditors Payable account
        # --------------------------------------------------------------
        payable_account = self.env['account.account'].search([
            ('company_id', '=', current_company.id),
            ('account_type', '=', 'liability_payable'),
            ('name', 'ilike', 'creditor'),
        ], limit=1)

        # Fallback if 'creditor' isn't in the name, just find one that is NOT opening purchase
        if not payable_account:
            payable_account = self.env['account.account'].search([
                ('company_id', '=', current_company.id),
                ('account_type', '=', 'liability_payable'),
                ('name', 'not ilike', 'opening'),
            ], limit=1)

        if payable_account:
            partner.with_company(
                current_company
            ).property_account_payable_id = payable_account.id


        # 2. Find Existing PO
        po = self.env['purchase.order'].search([
            ('partner_ref', '=', bill_ref),
            ('company_id', '=', current_company.id)
        ], limit=1)

        if not po:
            _logger.error(f"Cannot find existing Purchase Order with Bill Reference '{bill_ref}' for company '{current_company.name}'.")
            return

        if len(po.order_line) != len(lines):
            raise UserError(f"Line count mismatch for PO {po.name}. Excel has {len(lines)} lines, but PO has {len(po.order_line)} lines. Cannot map lines safely.")

        # 3. Surgical Update of Product ID Across the System
        _logger.info(f"Starting surgical variant fix for PO: {po.name} (Ref: {bill_ref})")

        for excel_line, po_line in zip(lines, po.order_line):
            product = self._resolve_product(excel_line, current_company)
            if not product:
                continue

            old_product_id = po_line.product_id.id
            new_product_id = product.id

            if old_product_id == new_product_id:
                continue

            _logger.info(f"Updating PO {po.name} Line {po_line.id}: Product {old_product_id} -> {new_product_id}")

            # A. Update purchase_order_line
            self.env.cr.execute("UPDATE purchase_order_line SET product_id = %s WHERE id = %s", (new_product_id, po_line.id))

            # B. Update stock_move and stock_move_line
            self.env.cr.execute("UPDATE stock_move SET product_id = %s WHERE purchase_line_id = %s", (new_product_id, po_line.id))
            
            self.env.cr.execute("""
                UPDATE stock_move_line sml
                SET product_id = %s
                FROM stock_move sm
                WHERE sml.move_id = sm.id AND sm.purchase_line_id = %s
            """, (new_product_id, po_line.id))

            # C. Update stock_valuation_layer
            self.env.cr.execute("""
                UPDATE stock_valuation_layer svl
                SET product_id = %s
                FROM stock_move sm
                WHERE svl.stock_move_id = sm.id AND sm.purchase_line_id = %s
            """, (new_product_id, po_line.id))

            # D. Update account_move_line (Vendor Bill)
            self.env.cr.execute("""
                UPDATE account_move_line aml
                SET product_id = %s
                WHERE aml.purchase_line_id = %s
            """, (new_product_id, po_line.id))

            # E. Update stock_quant
            self.env.cr.execute("""
                SELECT sml.location_dest_id, sml.quantity
                FROM stock_move_line sml
                JOIN stock_move sm ON sml.move_id = sm.id
                WHERE sm.purchase_line_id = %s
            """, (po_line.id,))
            
            for row in self.env.cr.fetchall():
                loc_id = row[0]
                qty = row[1] or 0.0
                
                if qty <= 0:
                    continue
                    
                # Decrease old product stock
                self.env.cr.execute("""
                    UPDATE stock_quant SET quantity = quantity - %s 
                    WHERE product_id = %s AND location_id = %s
                """, (qty, old_product_id, loc_id))
                
                # Increase new product stock
                self.env.cr.execute("""
                    UPDATE stock_quant SET quantity = quantity + %s 
                    WHERE product_id = %s AND location_id = %s
                """, (qty, new_product_id, loc_id))
                
                if self.env.cr.rowcount == 0:
                    self.env.cr.execute("""
                        INSERT INTO stock_quant (product_id, location_id, quantity, in_date, company_id)
                        VALUES (%s, %s, %s, now(), %s)
                    """, (new_product_id, loc_id, qty, current_company.id))

        self.env.flush_all()
        self.env.invalidate_all()
        _logger.info(f"Successfully fixed variants for PO {po.name}!")

    def _resolve_product(self, row, current_company):
        _logger.info("ROW = %s", row)
        _logger.info("ROW KEYS = %s", list(row.keys()))
        # Initialize caches on the instance if they don't exist
        if not hasattr(self, 'variant_cache'):
            self.variant_cache = {}
            self.template_cache = {}
            self.attribute_cache = {}
            self.attribute_value_cache = {}

        # Normalize attributes
        _logger.info("ROW DATA = %s", row)

        for k, v in row.items():
            _logger.info("COLUMN [%s] = %r", k, v)

        # Normalize attributes
        def get_col(name):
            for k, v in row.items():
                if str(k).strip().upper() == name.upper():
                    return v
            return None

        # Normalize attributes
        attrs = {
            'TYPE': str(get_col('TYPE') or '').strip().title(),
            'VARIETY': str(get_col('VARIETY') or '').strip().title(),
            'DESIGN': str(get_col('DESIGN') or get_col('DESIGN SIZE') or '').strip().title(),
            'SIZE': str(get_col('SIZE') or '').strip().title(),
            'STONE COLOUR': str(get_col('STONE COLOUR') or '').strip().title(),
            'METAL COLOUR': str(get_col('METAL COLOUR') or '').strip().title(),
        }

        # Treat 'FALSE', '' as None
        for k, v in attrs.items():
            _logger.info("%r => %r", k, v)
            if v.upper() in ('FALSE', ''):
                attrs[k] = 'None'

        _logger.info(
            "Current company: %s (%s)",
            current_company.name,
            current_company.id
        )

        raw_name = str(row.get('Product') or '')
        template_name = re.sub(r'\s+', ' ', raw_name).strip()
        if not template_name:
            return None

        _logger.info(f"Excel Product Name: '{raw_name}' -> Normalized: '{template_name}'")
        _logger.info(f"Excel Company: '{current_company.name}' (ID: {current_company.id})")

        # Composite key for exact matching
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

        template_cache_key = (current_company.id, template_name.lower())

        # Find or create Template with Cache
        if template_cache_key in self.template_cache:
            template = self.template_cache[template_cache_key]
        else:
            TemplateModel = self.env['product.template'].with_context(active_test=False)

            # We use a broad ORM search (to handle JSONB translations safely) combined with
            # strict Python filtering to bypass all database casing/spacing quirks.
            first_word = template_name.split('(')[0].strip() if '(' in template_name else template_name

            domain = [
                ('name', 'ilike', first_word),
                ('company_id', 'in', [current_company.id, False])
            ]
            _logger.info(f"Broad Search Domain: {domain}")

            all_templates = TemplateModel.search(domain)

            # Filter in Python to ensure perfect normalization match
            matched_templates = []
            excel_name_norm = re.sub(r'\s+', '', template_name).upper()

            for t in all_templates:
                db_name_norm = re.sub(r'\s+', '', str(t.name or '')).upper()
                if db_name_norm == excel_name_norm:
                    matched_templates.append(t)

            if matched_templates:
                # Prioritize company-specific templates over shared templates, then by oldest ID
                matched_templates.sort(
                    key=lambda t: (0 if t.company_id and t.company_id.id == current_company.id else 1, t.id))
                template = matched_templates[0]

                _logger.info(f"Excel Company: {current_company.name} (ID: {current_company.id})")
                _logger.info(f"Purchase Order Company: {current_company.name} (ID: {current_company.id})")
                _logger.info(f"Selected Template ID: {template.id}")
                _logger.info(
                    f"Template Company: {template.company_id.name if template.company_id else 'Shared'} (ID: {template.company_id.id if template.company_id else False})")



            else:

                service_products = {
                    "ADD OR LESS",
                    "ROUND OFF",
                    "HALLMARKING EXPENSES",
                    "FREIGHT CHARGES",
                    "TRANSPORTATION CHARGE",
                    "CERTIFICATION CHARGE -18%"
                                    }

                if template_name.strip().upper() in service_products:

                    template = self.env["product.template"].search([
                        ("name", "=ilike", template_name),
                        ("company_id", "in", [current_company.id, False]),
                    ], limit=1)

                    # Create if it doesn't exist
                    if not template:
                        _logger.info(
                            "Creating Service Product '%s' for company '%s'",
                            template_name,
                            current_company.name,
                        )

                        template = self.env["product.template"].create({
                            "name": template_name,
                            "type": "service",
                            "purchase_ok": True,
                            "sale_ok": False,
                            "company_id": current_company.id,
                        })

                    # Return the only variant of the service product
                    variant = template.product_variant_id

                    self.template_cache[template_cache_key] = template
                    self.variant_cache[cache_key] = variant

                    return variant

                raise UserError(

                    f"Product Template '{template_name}' not found for company '{current_company.name}'. Import aborted."

                )
            assert template.exists(), "Product Template not found. Creation of new Product Templates is disabled."
            self.template_cache[template_cache_key] = template
        # Service products never have attributes or variants
        if template.type == "service":
            variant = template.product_variant_id
            self.variant_cache[cache_key] = variant
            return variant

        # ------------------------------------------------------------------
        # Resolve Variant EXACT MATCH
        # ------------------------------------------------------------------
        ptav_ids = []

        for attr_name, attr_val in attrs.items():

            # Find the attribute line on the template
            ptal = template.attribute_line_ids.filtered(
                lambda l: (l.attribute_id.name or "").strip().lower() ==
                          (attr_name or "").strip().lower()
            )[:1]

            if not ptal:
                raise UserError(
                    _("Attribute '%s' is not configured on template '%s'.")
                    % (attr_name, template.display_name)
                )

            # Find the existing attribute value (EXACT match)
            values = self.env["product.attribute.value"].search([
                ("attribute_id", "=", ptal.attribute_id.id),
            ])

            # value = values.filtered(
            #     lambda v: (v.name or "").strip().lower() ==
            #               (attr_val or "").strip().lower()
            # )[:1]
            def normalize_attr(val):
                val = str(val or "").strip().lower()

                # Normalize multiple spaces
                val = re.sub(r"\s+", " ", val)

                # Normalize hyphens
                val = re.sub(r"\s*-\s*", "-", val)

                # Normalize double quotes
                val = val.replace("“", '"').replace("”", '"')

                # Remove spaces before/after quotes
                val = re.sub(r'\s*"\s*', '"', val)

                return val

            value = values.filtered(
                lambda v: normalize_attr(v.name) == normalize_attr(attr_val)
            )[:1]

            if not value:
                _logger.info(
                    "Creating missing attribute value '%s' for attribute '%s'",
                    attr_val,
                    attr_name,
                )

                value = self.env["product.attribute.value"].create({
                    "name": str(attr_val).strip(),
                    "attribute_id": ptal.attribute_id.id,
                })

            # Configure the template to use this value if needed
            # Configure the template to use this value if needed
            if value not in ptal.value_ids:
                _logger.info(
                    "Configuring existing value '%s' on template '%s'",
                    value.name,
                    template.display_name,
                )

                ptal.write({
                    "value_ids": [(4, value.id)]
                })

                self.env.flush_all()
                self.env.invalidate_all()

            # Get the PTAV record
            ptav = self.env["product.template.attribute.value"].search([
                ("attribute_line_id", "=", ptal.id),
                ("product_attribute_value_id", "=", value.id),
            ], limit=1)

            if not ptav:
                raise UserError(
                    _("Unable to configure attribute '%s' value '%s'.")
                    % (attr_name, attr_val)
                )

            if not ptav:
                raise UserError(
                    _("Unable to configure attribute '%s' value '%s'.")
                    % (attr_name, attr_val)
                )

            ptav_ids.append(ptav.id)

        # ------------------------------------------------------------------
        # Exact Variant Match
        # ------------------------------------------------------------------
        target_ptav_set = set(ptav_ids)
        exact_variant = False

        for variant in template.product_variant_ids:

            if variant.company_id and variant.company_id != current_company:
                continue

            if set(variant.product_template_attribute_value_ids.ids) == target_ptav_set:
                exact_variant = variant
                break

        # ------------------------------------------------------------------
        # Create Variant if Missing
        # ------------------------------------------------------------------
        if not exact_variant:
            _logger.info(
                "Variant not found. Creating variant for %s",
                template.display_name,
            )

            exact_variant = self.env["product.product"].create({
                "product_tmpl_id": template.id,
                "product_template_attribute_value_ids": [(6, 0, ptav_ids)],
            })

            _logger.info(
                "Created Variant %s (%s)",
                exact_variant.display_name,
                exact_variant.id,
            )

        _logger.info(
            "Selected Variant %s (%s)",
            exact_variant.display_name,
            exact_variant.id,
        )

        self.variant_cache[cache_key] = exact_variant

        return exact_variant