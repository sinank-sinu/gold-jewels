# -*- coding: utf-8 -*-
import base64
import io
import logging
from datetime import datetime
from collections import defaultdict
import openpyxl
from odoo.exceptions import UserError
import re
import pytz

_logger = logging.getLogger(__name__)

class ImportLabelService:
    def __init__(self, env):
        self.env = env

    def process_import(self, file_base64):
        _logger.info("Starting Purchase Label Bulk Import...")
        try:
            file_content = base64.b64decode(file_base64)
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
                    
                key = (vendor_ref, date_str)
                grouped_data[key].append(row_dict)
                
            _logger.info(f"Found {len(grouped_data)} unique Purchase Orders.")
            
            count = 0
            # Process each group
            for (vendor_ref, date_str), lines in grouped_data.items():
                self._process_po_group(vendor_ref, date_str, lines)
                count += 1
                if count % 10 == 0:
                    self.env.cr.commit()
                    _logger.info(f"Processed {count} POs...")
                    
            self.env.cr.commit()
            _logger.info("Purchase Label Bulk Import Completed Successfully!")
            
        except Exception as e:
            _logger.error(f"Error during import: {str(e)}", exc_info=True)
            self.env.cr.rollback()

    def _process_po_group(self, vendor_ref, date_str, lines):
        if not lines:
            return
            
        # 0. Resolve Migration Company from Excel
        company_names = set(str(line.get('Company')).strip() for line in lines if line.get('Company'))
        if not company_names:
            raise UserError(f"No Company specified in Excel for Purchase Order {vendor_ref}")
        if len(company_names) > 1:
            raise UserError(f"Multiple companies found in Excel for Purchase Order {vendor_ref}: {company_names}. All rows in a PO must belong to the same company.")
            
        company_name = company_names.pop()
        current_company = self.env['res.company'].search([('name', '=', company_name)], limit=1)
        if not current_company:
            raise UserError(f"Company '{company_name}' from Excel not found in Odoo.")
            
        # 1. Resolve Vendor
        partner = self.env['res.partner'].search(['|', ('name', '=', vendor_ref), ('ref', '=', vendor_ref)], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({
                'name': vendor_ref,
                'supplier_rank': 1,
                'company_id': False,
            })
        elif partner.company_id:
            try:
                partner.company_id = False
            except Exception:
                pass
            
        # 2. Create PO
        po_vals = {
            'partner_id': partner.id,
            'date_order': date_str,
            'partner_ref': vendor_ref,
            'company_id': current_company.id,
        }
        
        excel_branch = lines[0].get('Branch') if lines else None
        if excel_branch:
            _logger.info(f"Excel branch value ignored: '{excel_branch}'")
            
        fixed_branch_name = excel_branch
        _logger.info(f"Using fixed Purchase Order branch: '{fixed_branch_name}'")
        _logger.info(f"Company: '{current_company.name}'")
        
        branch = self.env['res.branch'].search([
            ('name', '=', fixed_branch_name),
            ('company_id', '=', current_company.id)
        ], limit=1)
        
        if not branch:
            raise UserError(f"Branch '{fixed_branch_name}' not found for company '{current_company.name}'.")
            
        po_vals['branch_id'] = branch.id
        _logger.info(f"Purchase Order branch: '{fixed_branch_name}'")
                
        po = self.env['purchase.order'].create(po_vals)
        
        source_location = None
        dest_location = None
        
        # 3. Add PO Lines
        for line in lines:
            product = self._resolve_product(line, current_company)
            if not product:
                continue
                
            qty = float(line.get('Order Lines/Quantity') or line.get('Quantity') or 1.0)
            price = float(line.get('Order Lines/Unit Price') or line.get('Unit Price') or 0.0)
            weight = float(line.get('Weight') or line.get('Gross Weight') or line.get('Weight (g)') or line.get('Weight in grams') or 0.0)
            
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
                'taxes_id': [(5, 0, 0)],
            }
            if purity_id:
                po_line_vals['purity_id'] = purity_id
                
            self.env['purchase.order.line'].create(po_line_vals)
            
        if not po.order_line:
            po.unlink()
            return
            
        _logger.info("GST disabled for imported Purchase Order")
        for line in po.order_line:
            line.taxes_id = [(5, 0, 0)]
            _logger.info(f"Taxes cleared from Purchase Order Line: {line.product_id.name}")
            
        # 4. Confirm PO
        po.button_confirm()
        
        # Force the confirmation date and arrival date to the Excel bill date
        po.write({
            'date_approve': date_str,
            'date_planned': date_str,
        })
        
        # 5. Validate Receipt with correct Source and Destination Location (Excel)
        if po.picking_ids:
            # Force Source Location to always be the Vendor Location
            vendor_location_id = po.partner_id.property_stock_supplier.id
                    
            dst_loc = None
            if dest_location:
                dst_loc = self.env['stock.location'].search([('complete_name', '=', dest_location)], limit=1)
                if not dst_loc:
                    dst_loc = self.env['stock.location'].search([('name', '=', dest_location)], limit=1)
                
            for picking in po.picking_ids.filtered(lambda p: p.state not in ['done', 'cancel']):
                picking.location_id = vendor_location_id
                if dst_loc:
                    picking.location_dest_id = dst_loc.id
                    
                for move in picking.move_ids:
                    move.location_id = vendor_location_id
                    if dst_loc:
                        move.location_dest_id = dst_loc.id
                    for move_line in move.move_line_ids:
                        move_line.location_id = vendor_location_id
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
                
        # 6. Create Vendor Bill (Opening Balance)
        self._create_vendor_bill(po, date_str)

    def _create_vendor_bill(self, po, date_str):
        company_id = po.company_id.id or self.env.company.id
        
        # 1. Journals and Accounts
        journal = self.env['account.journal'].search([
            ('name', 'ilike', 'opening'),
            ('company_id', '=', company_id)
        ], limit=1)
        
        if not journal:
            raise UserError("Opening Balance journal not found for the current company.")
            
        stock_input_account = self.env['account.account'].search([
            ('name', 'ilike', 'stock input'),
            ('company_id', '=', company_id)
        ], limit=1)
        
        if not stock_input_account:
            raise UserError("Stock Input account not found for the current company.")
            
        opening_account = self.env['account.account'].search([
            ('name', 'ilike', 'opening purchase'),
            ('company_id', '=', company_id)
        ], limit=1)
        if not opening_account and journal and journal.default_account_id:
            opening_account = journal.default_account_id
            
        if not opening_account:
            raise UserError("Opening Balance account (Opening Purchase) not found.")

        # 2. Generate Invoice Values manually to inject Stock Input account
        from odoo.tools.float_utils import float_is_zero
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        
        invoice_vals = po.with_company(po.company_id)._prepare_invoice()
        
        invoice_vals['invoice_date'] = date_str
        invoice_vals['date'] = date_str
        invoice_vals['invoice_date_due'] = date_str
        invoice_vals['journal_id'] = journal.id
        invoice_vals['is_approved'] = True
            
        sequence = 10
        for line in po.order_line:
            if line.display_type == 'line_section':
                continue
            if not float_is_zero(line.qty_to_invoice, precision_digits=precision):
                line_vals = line._prepare_account_move_line()
                line_vals.update({'sequence': sequence})
                
                # INTERCEPT DEBIT ACCOUNT: Use Stock Input (100306)
                if not line.display_type:
                    line_vals['account_id'] = stock_input_account.id
                    line_vals['tax_ids'] = [(5, 0, 0)]
                    
                invoice_vals['invoice_line_ids'].append((0, 0, line_vals))
                sequence += 1
                
        # 3. Force the Vendor Bill to directly use the Opening Purchase account for its Payable/Credit line.
        original_payable = po.partner_id.property_account_payable_id
        
        if opening_account:
            # Temporarily set the vendor's payable account so Odoo natively generates the credit line with it
            po.partner_id.with_company(po.company_id).property_account_payable_id = opening_account.id
            
        try:
            # Create and Post the Vendor Bill
            bill = self.env['account.move'].with_company(po.company_id).create([invoice_vals])[0]
            
            # Ensure no taxes exist on the vendor bill before posting
            tax_lines = bill.line_ids.filtered(lambda l: l.tax_line_id or l.tax_repartition_line_id)
            if tax_lines:
                tax_lines.with_context(check_move_validity=False).unlink()
                
            _logger.info("Taxes cleared from Vendor Bill")
            _logger.info("No GST taxes applied during migration")
            
            bill.action_post()
        finally:
            # Restore the vendor's original payable account configuration
            if opening_account and original_payable:
                po.partner_id.with_company(po.company_id).property_account_payable_id = original_payable.id
                
        # 4. Create Reconciling Dummy Entry to mark the bill as PAID
        # The bill's payable line is Opening Purchase. We debit it to reconcile the bill (Paid),
        # and credit it to leave the balance correctly in Opening Purchase!
        payable_line = bill.line_ids.filtered(lambda l: l.account_id == opening_account and l.credit > 0)
        
        if payable_line and bill.amount_residual > 0:
            reconcile_vals = {
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': date_str,
                'ref': f"Opening Balance Payment for {po.name}",
                'company_id': po.company_id.id,
                'line_ids': [
                    (0, 0, {
                        'name': f'Clear Bill Payable for {po.name}',
                        'account_id': opening_account.id,
                        'partner_id': po.partner_id.id,
                        'debit': bill.amount_residual,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': f'Final Opening Balance Credit for {po.name}',
                        'account_id': opening_account.id,
                        'partner_id': po.partner_id.id,
                        'debit': 0.0,
                        'credit': bill.amount_residual,
                    })
                ]
            }
            reconcile_move = self.env['account.move'].with_company(po.company_id).create([reconcile_vals])[0]
            reconcile_move.action_post()
            
            # Reconcile the payable lines to fully close the vendor bill
            payment_line = reconcile_move.line_ids.filtered(lambda l: l.account_id == opening_account and l.debit > 0)
            if payment_line:
                (payable_line[0] + payment_line[0]).reconcile()
                
        # 5. Log the final generated items
        _logger.info(f"Vendor Bill {bill.name} created directly into Opening Purchase and marked as PAID successfully.")

    def _resolve_product(self, row, current_company):
        # Initialize caches on the instance if they don't exist
        if not hasattr(self, 'variant_cache'):
            self.variant_cache = {}
            self.template_cache = {}
            self.attribute_cache = {}
            self.attribute_value_cache = {}

        # Normalize attributes
        attrs = {
            'TYPE': str(row.get('TYPE') or '').strip().title(),
            'VARIETY': str(row.get('VARIETY') or '').strip().title(),
            'DESIGN': str(row.get('DESIGN') or row.get('DESIGN SIZE') or '').strip().title(),
            'SIZE': str(row.get('SIZE') or '').strip().title(),
            'STONE COLOUR': str(row.get('STONE COLOUR') or '').strip().title(),
            'METAL COLOUR': str(row.get('METAL COLOUR') or '').strip().title(),
        }
        
        # Treat 'FALSE', '' as None
        for k, v in attrs.items():
            if v.upper() in ('FALSE', '', 'NONE'):
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
                matched_templates.sort(key=lambda t: (0 if t.company_id and t.company_id.id == current_company.id else 1, t.id))
                template = matched_templates[0]
                
                _logger.info(f"Excel Company: {current_company.name} (ID: {current_company.id})")
                _logger.info(f"Purchase Order Company: {current_company.name} (ID: {current_company.id})")
                _logger.info(f"Selected Template ID: {template.id}")
                _logger.info(f"Template Company: {template.company_id.name if template.company_id else 'Shared'} (ID: {template.company_id.id if template.company_id else False})")

            else:
                raise UserError(f"Product Template '{template_name}' not found for company '{current_company.name}'. Import aborted.")
                
            assert template.exists(), "Product Template not found. Creation of new Product Templates is disabled."
            self.template_cache[template_cache_key] = template
            
        # Ensure the template is active
        if hasattr(template, 'active') and not template.active:
            raise UserError(f"Product Template '{template.name}' is archived. Unarchive it before importing.")

        def normalize_value(value):
            import unicodedata
            if not value or str(value).strip().lower() in ['false', 'none', '']:
                return "none"
            val_str = str(value)
            
            # Normalize Unicode
            val_str = unicodedata.normalize('NFKC', val_str)
            
            # Replace smart quotes with normal quotes
            val_str = val_str.replace('”', '"').replace('“', '"').replace('„', '"')
            val_str = val_str.replace('‘', "'").replace('’', "'")
            
            # Replace smart dashes with '-' and remove spaces around them
            val_str = re.sub(r'\s*[-\u2013\u2014]\s*', '-', val_str)
            
            # Remove spaces immediately before or after a double quote (")
            val_str = re.sub(r'\s*"\s*', '"', val_str)
            
            # Remove spaces immediately before or after a single quote (')
            val_str = re.sub(r"\s*'\s*", "'", val_str)
            
            # Collapse repeated spaces again after replacements
            return " ".join(val_str.strip().split()).casefold()

        # Build exact Product Template Attribute Values (PTAVs) for the variant
        ptav_ids = []
        for attr_name, attr_val in attrs.items():
            attribute = self.env['product.attribute'].search([('name', '=ilike', str(attr_name).strip())], limit=1)
            if not attribute:
                raise UserError(f"Product Attribute '{attr_name}' not found. Please ensure it exists.")
                
            norm_excel = normalize_value(attr_val)
            
            # Fetch all values belonging to the attribute and compare in Python
            available_values = attribute.value_ids
            matched_value = next(
                (
                    v for v in available_values
                    if normalize_value(v.name) == norm_excel
                ),
                False,
            )
            value = matched_value
            
            _logger.info(f"Excel: {repr(attr_val)} -> Normalized: {repr(norm_excel)} | Database Matched: {'YES' if matched_value else 'NO'}")
            
            if not value:
                available_diagnostics = [f"Raw: {repr(v.name)} -> Normalized: {repr(normalize_value(v.name))}" for v in available_values]
                _logger.error("--- ATTRIBUTE VALUE MISMATCH ---")
                _logger.error(f"Template ID: {template.id} | Name: {template.name} | Attribute: {attr_name}")
                _logger.error(f"Raw Excel Val: {repr(attr_val)}")
                _logger.error(f"Normalized Excel Val: {repr(norm_excel)}")
                _logger.error("Available Values in Database:")
                for diag in available_diagnostics:
                    _logger.error(diag)
                _logger.error("--------------------------------")
                
                raise UserError(
                    f"Product Attribute Value {repr(attr_val)} for Attribute '{attr_name}' not found. "
                    f"Normalized search was: {repr(norm_excel)}. Check logs for available values."
                )
                
            if hasattr(value, 'active') and not value.active:
                raise UserError(f"Product Attribute Value {repr(attr_val)} for Attribute '{attr_name}' is archived.")

            # Step 2: Verify product.template.attribute.line exists. If missing create it.
            ptal = template.attribute_line_ids.filtered(lambda l: l.attribute_id.id == attribute.id)
            if not ptal:
                _logger.info(f"Creating missing Attribute Line for '{attr_name}' on Template '{template.name}'")
                ptal = self.env['product.template.attribute.line'].create({
                    'product_tmpl_id': template.id,
                    'attribute_id': attribute.id,
                    'value_ids': [(4, value.id)]
                })
            
            if hasattr(ptal, 'active') and not ptal.active:
                 raise UserError(f"Attribute Line for '{attr_name}' on Template '{template.name}' is archived.")

            # Step 3: Verify the Excel value exists inside that template attribute line.
            if value.id not in ptal.value_ids.ids:
                _logger.info(f"Attaching existing value '{norm_excel}' to Attribute Line '{attr_name}' on Template '{template.name}'")
                ptal.write({'value_ids': [(4, value.id)]})

            # Step 4: From that attribute line, search the Product Template Attribute Value (PTAV).
            ptavs = self.env['product.template.attribute.value'].search([('attribute_line_id', '=', ptal.id), ('product_attribute_value_id', '=', value.id)])
            
            if not ptavs:
                # Fallback to flush in case Odoo ORM hasn't generated the PTAV record yet
                ptal.flush_recordset(['value_ids'])
                ptavs = self.env['product.template.attribute.value'].search([('attribute_line_id', '=', ptal.id), ('product_attribute_value_id', '=', value.id)])
                if not ptavs:
                    raise UserError(f"Failed to resolve PTAV for '{norm_excel}' on Attribute '{attr_name}' for Template '{template.name}' after attaching the value.")
            
            matched_ptav = ptavs[0]
            
            if hasattr(matched_ptav, 'ptav_active') and not matched_ptav.ptav_active:
                raise UserError(f"PTAV for '{norm_excel}' on Attribute '{attr_name}' for Template '{template.name}' is archived.")
                
            ptav_ids.append(matched_ptav.id)
            _logger.info(f"Template ID: {template.id} | Template Name: {template.name} | Attribute: {attr_name} | Excel Val: {attr_val} | Norm Val: {norm_excel} | Attr ID: {attribute.id} | PTAL ID: {ptal.id} | PTAV ID: {matched_ptav.id} | Value ID: {value.id}")
                
        # Check Variant Creation Modes
        creation_modes = {}
        for ptav_id in ptav_ids:
            ptav = self.env['product.template.attribute.value'].browse(ptav_id)
            attr_name = ptav.attribute_id.name
            create_mode = ptav.attribute_id.create_variant
            creation_modes[attr_name] = create_mode
            if create_mode == 'no_variant':
                _logger.warning(f"Attribute '{attr_name}' on Template '{template.name}' is configured as 'Never (No Variants)'. Odoo will not generate variants for this attribute.")

        # Find exact variant by checking if ptav_ids perfectly match the variant's product_template_attribute_value_ids
        exact_variant = None
        target_ptav_set = set(ptav_ids)
        
        count_before = len(template.product_variant_ids)
        
        for variant in template.product_variant_ids:
            if variant.company_id and variant.company_id.id != current_company.id:
                continue
                
            if set(variant.product_template_attribute_value_ids.ids) == target_ptav_set:
                exact_variant = variant
                break
                
        generation_triggered = False
        if not exact_variant:
            _logger.info("Exact variant not found. Triggering Odoo's standard variant generation...")
            generation_triggered = True
            
            # Combine the PTAVs for dynamic variant generation
            combination = self.env['product.template.attribute.value'].browse(ptav_ids)
            
            # Try dynamic generation first (this activates archived variants or creates new ones if dynamic)
            created_variant = template._create_product_variant(combination)
            if created_variant:
                _logger.info(f"Dynamic generation returned Variant ID: {created_variant.id}")
                
            # Also trigger standard generation just in case there are missing instantly created variants
            template._create_variant_ids()
            
            # Reload template to fetch newly created variants
            template.invalidate_recordset(['product_variant_ids'])
            
            # Search again after generation
            for variant in template.product_variant_ids:
                if variant.company_id and variant.company_id.id != current_company.id:
                    continue
                    
                if set(variant.product_template_attribute_value_ids.ids) == target_ptav_set:
                    exact_variant = variant
                    _logger.info(f"Newly generated/activated Variant ID: {exact_variant.id}")
                    break
                    
        if not exact_variant:
            count_after = len(template.product_variant_ids)
            ptav_names = [self.env['product.template.attribute.value'].browse(p).display_name for p in ptav_ids]
            
            _logger.error("--- VARIANT RESOLUTION DIAGNOSTICS ---")
            _logger.error(f"Template ID: {template.id}")
            _logger.error(f"Template Name: {template.name}")
            _logger.error(f"Company: {current_company.name} (ID: {current_company.id})")
            _logger.error(f"Attribute Creation Modes: {creation_modes}")
            _logger.error(f"Requested PTAV IDs: {ptav_ids}")
            _logger.error(f"Requested PTAV Names: {ptav_names}")
            _logger.error(f"Total variants on template: {count_after}")
            _logger.error(f"Variants before generation: {count_before} | After: {count_after}")
            _logger.error(f"Generation triggered: {generation_triggered}")
            
            for variant in template.product_variant_ids:
                v_ptav_ids = variant.product_template_attribute_value_ids.ids
                v_ptav_names = variant.product_template_attribute_value_ids.mapped('display_name')
                _logger.error(f"Existing Variant ID {variant.id}: PTAV IDs {v_ptav_ids} | PTAV Names {v_ptav_names}")
                
            _logger.error("--------------------------------------")
            
            missing_combination = ", ".join(ptav_names)
            error_msg = f"Product Variant not found for template '{template.name}'. The exact attribute combination [{missing_combination}] could not be resolved or generated. Check if an attribute is set to 'Never (No Variants)' or if the template configuration is incomplete."
            raise UserError(error_msg)
            
        _logger.info(f"Final Variant ID used: {exact_variant.id}")
        _logger.info(f"Variant Company: {exact_variant.company_id.name if exact_variant.company_id else 'Shared'} (ID: {exact_variant.company_id.id if exact_variant.company_id else False})")
                
        if exact_variant:
            self.variant_cache[cache_key] = exact_variant
            
        return exact_variant
