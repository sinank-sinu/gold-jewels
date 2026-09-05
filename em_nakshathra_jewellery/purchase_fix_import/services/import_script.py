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

            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True, read_only=True)
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


        # 2. Create PO
        po_vals = {
            'partner_id': partner.id,
            'date_order': date_str,
            'partner_ref': bill_ref,
            'company_id': current_company.id,
        }
        branch_name = lines[0].get('Branch') if lines else None
        if branch_name:
            branch = self.env['res.branch'].search([('name', '=', str(branch_name).strip())], limit=1)
            if branch:
                po_vals['branch_id'] = branch.id

        po = self.env['purchase.order'].create(po_vals)
        print(po)
        print(po.name)

        source_location = None
        dest_location = None

        # 3. Add PO Lines
        for line in lines:
            product = self._resolve_product(line, current_company)
            if not product:
                continue
            import re

            tax_name = str(line.get("Order Lines/Taxes") or "").strip()

            tax = False

            if tax_name == "3% GST":
                tax = self.env["account.tax"].search([
                    ("name", "=", tax_name),
                    ("type_tax_use", "in", ["purchase", "none"]),('company_id','=',current_company.id)
                ], limit=1)

                tax = self.env["account.tax"].browse(tax.id)
            elif tax_name == "18% GST":
                tax = self.env["account.tax"].search([
                    ("name", "=", tax_name),
                    ("type_tax_use", "in", ["purchase", "none"]), ('company_id', '=', current_company.id)
                ], limit=1)

                tax = self.env["account.tax"].browse(tax.id)
                print("tax 18 % found")

            # if not tax:
            #     raise UserError(
            #         _("Purchase Tax '%s' not found for company '%s'.")
            #         % (tax_name, current_company.name)
            #     )

            qty = float(line.get('Order Lines/Quantity') or line.get('Quantity') or 1.0)
            price = float(line.get('Order Lines/Unit Price') or line.get('Unit Price') or 0.0)
            weight = float(line.get('Weight') or line.get('Gross Weight') or line.get('Weight (g)') or line.get(
                'Weight in grams') or 0.0)
            # gold_rate_val = str(line.get("Fine Rate") or "").strip()

            try:
                gold_rate = float()
            except (ValueError, TypeError):
                gold_rate = 0.0

            purity_id = False
            purity_name = line.get('Purity')
            if purity_name:
                purity = self.env['gold.purity'].search([('name', '=', str(purity_name).strip())], limit=1)
                if purity:
                    purity_id = purity.id
            _logger.info(
                "Product: %s (%s), Company: %s (%s)",
                product.display_name,
                product.id,
                product.company_id.name if product.company_id else "Shared",
                product.company_id.id if product.company_id else None
            )

            if product.company_id and product.company_id.id != po.company_id.id:
                raise UserError(
                    f"Product {product.display_name} belongs to company {product.company_id.name}, "
                    f"but Purchase Order {po.name} belongs to company {po.company_id.name}."
                )

            if not source_location and (line.get('Source Location') or line.get('Src Location')):
                source_location = str(line.get('Source Location') or line.get('Src Location')).strip()
            if not dest_location and (line.get('Destination Location') or line.get('Dest Location')):
                dest_location = str(line.get('Destination Location') or line.get('Dest Location')).strip()

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
                'taxes_id': [(6, 0, [tax.id])] if tax else [(5, 0, 0)],
            }
            if purity_id:
                po_line_vals['purity_id'] = purity_id

            self.env['purchase.order.line'].create(po_line_vals)

        # if not po.order_line:
        #     po.unlink()
        #     return

        # 4. Confirm PO
        po.button_confirm()
        print(po)
        print(po.name)
        print(po.company_id.name)

        # Force the confirmation date and arrival date to the Excel bill date
        po.write({
            'date_approve': date_str,
            'date_planned': date_str,
            'unfix': False
        })

        # 5. Validate Receipt with correct Source and Destination Location (Excel)
        if po.picking_ids:
            src_loc = None
            if source_location:
                src_loc = self.env['stock.location'].search([('complete_name', '=', source_location)], limit=1)
                if not src_loc:
                    src_loc = self.env['stock.location'].search([('name', '=', source_location)], limit=1)

            dst_loc = None
            if dest_location:
                dst_loc = self.env['stock.location'].search([('complete_name', '=', source_location)], limit=1)
                if not dst_loc:
                    dst_loc = self.env['stock.location'].search([('name', '=', source_location)], limit=1)

            for picking in po.picking_ids.filtered(lambda p: p.state not in ['done', 'cancel']):
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

                # Auto-validate receipt
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty

                picking.scheduled_date = date_str
                picking.button_validate()

                # Force the picking date to the Excel bill date
                picking.write({'date_done': date_str})
                picking.move_ids.write({'date': date_str})
                picking.move_line_ids.write({'date': date_str})

        po.action_create_invoice()
        
        for bill in po.invoice_ids:
            bill.write({
                'invoice_date': date_str,
                'date': date_str,
                'invoice_date_due': date_str,
            })
            
        self.env.flush_all()
        self.env.invalidate_all()

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
        # Service products and vault products never have attributes or variants
        if template.type == "service" or "VAULT" in template.name.upper() or not template.attribute_line_ids:
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