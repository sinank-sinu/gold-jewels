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
            
        fixed_branch_name = 'Head Office Main'
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
            
        # Build exact Product Template Attribute Values (PTAVs) for the variant
        ptav_ids = []
        for attr_name, attr_val in attrs.items():
            if not attr_val:
                continue
                
            # Get or create attribute
            if attr_name in self.attribute_cache:
                attribute = self.attribute_cache[attr_name]
            else:
                attribute = self.env['product.attribute'].search([('name', '=ilike', attr_name)], limit=1)
                if not attribute:
                    attribute = self.env['product.attribute'].create({'name': attr_name})
                self.attribute_cache[attr_name] = attribute
                
            # Get or create attribute value
            val_key = (attribute.id, attr_val)
            if val_key in self.attribute_value_cache:
                value = self.attribute_value_cache[val_key]
            else:
                value = self.env['product.attribute.value'].search([
                    ('attribute_id', '=', attribute.id),
                    ('name', '=ilike', attr_val)
                ], limit=1)
                if not value:
                    value = self.env['product.attribute.value'].create({
                        'attribute_id': attribute.id,
                        'name': attr_val
                    })
                self.attribute_value_cache[val_key] = value
                
            # Ensure the template has this attribute line
            ptal = template.attribute_line_ids.filtered(lambda l: l.attribute_id.id == attribute.id)
            if not ptal:
                ptal = self.env['product.template.attribute.line'].create({
                    'product_tmpl_id': template.id,
                    'attribute_id': attribute.id,
                    'value_ids': [(4, value.id)]
                })
            elif value.id not in ptal.value_ids.ids:
                ptal.write({'value_ids': [(4, value.id)]})
                
            # Search for the PTAV directly created by Odoo
            ptav = self.env['product.template.attribute.value'].search([
                ('attribute_line_id', '=', ptal.id),
                ('product_attribute_value_id', '=', value.id)
            ], limit=1)
            
            if ptav:
                ptav_ids.append(ptav.id)
                
        # Find exact variant by checking if ptav_ids perfectly match the variant's product_template_attribute_value_ids
        exact_variant = None
        for variant in template.product_variant_ids:
            if variant.company_id and variant.company_id.id != current_company.id:
                continue
                
            variant_ptav_ids = set(variant.product_template_attribute_value_ids.ids)
            if variant_ptav_ids == set(ptav_ids):
                exact_variant = variant
                break
                
        if not exact_variant:
            # Force create variant if it doesn't exist
            try:
                _logger.info(
                    "Using company %s (%s) for product variant creation",
                    current_company.name,
                    current_company.id
                )
                exact_variant = self.env['product.product'].create({
                    'product_tmpl_id': template.id,
                    'product_template_attribute_value_ids': [(6, 0, ptav_ids)],
                })
                _logger.info(
                    "Variant created: Variant ID %s under Template ID %s",
                    exact_variant.id, template.id
                )
            except Exception as e:
                _logger.error(f"Failed to create exact variant for {template_name} with attributes {attrs}: {e}")
                
        if exact_variant:
            _logger.info(f"Selected Variant ID: {exact_variant.id}")
            _logger.info(f"Variant Company: {exact_variant.company_id.name if exact_variant.company_id else 'Shared'} (ID: {exact_variant.company_id.id if exact_variant.company_id else False})")
                
        if exact_variant:
            self.variant_cache[cache_key] = exact_variant
            
        return exact_variant
