import base64
import io
import logging
from openpyxl import load_workbook
from odoo.exceptions import UserError
from datetime import datetime

_logger = logging.getLogger(__name__)

class ProductLabelImportService:
    def __init__(self, env):
        self.env = env(su=True)

    def process_import(self, file_base64):
        _logger.info("Starting Product Label Bulk Import via Python Script...")
        file_content = base64.b64decode(file_base64)
        
        # Using read_only=True significantly reduces openpyxl memory footprint
        wb = load_workbook(io.BytesIO(file_content), data_only=True, read_only=True)
        sheet = wb.active
        
        # Extract headers and handle duplicates for read_only mode
        header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
        raw_headers = [str(val).strip() if val else f"Col_{idx}" for idx, val in enumerate(header_row)]
        headers = []
        counts = {}
        for h in raw_headers:
            if h in counts:
                counts[h] += 1
                headers.append(f"{h}_{counts[h]}")
            else:
                counts[h] = 0
                headers.append(h)
                
        created = 0
        transferred = 0
        
        import odoo
        import gc
        
        # Safe psutil patch in case Odoo's process_limit memory tracker crashes
        try:
            import psutil
            if not hasattr(psutil.Process, '_cache'):
                setattr(psutil.Process, '_cache', property(lambda self: {}))
        except Exception:
            pass
        
        current_cr = self.env.registry.cursor()
        current_env = odoo.api.Environment(current_cr, self.env.uid, self.env.context)(su=True)
        original_env = self.env
        
        try:
            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                if not any(row):
                    continue
                    
                row_dict = dict(zip(headers, row))
                
                if current_cr.closed:
                    current_cr = self.env.registry.cursor()
                    current_env = odoo.api.Environment(current_cr, self.env.uid, self.env.context)(su=True)
                    
                self.env = current_env
                
                try:
                    with self.env.cr.savepoint():
                        _logger.info(f"Processing row {row_idx}...")
                        label = self._process_row(row_dict, row_idx)
                        
                        # Extract and parse date from excel row (Bill Date or Date)
                        def get_local_val(key_name):
                            for k in row_dict.keys():
                                if str(k).strip().lower() == key_name.lower():
                                    return row_dict[k]
                            return None

                        raw_date = get_local_val('bill date') or get_local_val('date')
                        excel_date = None
                        if raw_date:
                            if hasattr(raw_date, 'strftime'):
                                excel_date = raw_date
                            elif isinstance(raw_date, str):
                                try:
                                    from dateutil import parser
                                    excel_date = parser.parse(raw_date)
                                except Exception:
                                    pass
                        
                        # Perform Transfer immediately
                        company = label.branch_id.company_id or label.product_id.company_id
                        if company:
                            label = label.with_company(company)
                        label.action_stock_in()
                        
                        picking = label.picking_id
                        if picking and excel_date:
                            formatted_date = excel_date.strftime('%Y-%m-%d %H:%M:%S')
                            try:
                                # Flush pending ORM updates to the database to prevent overwriting our SQL
                                picking.flush_recordset()
                                picking.move_ids.flush_recordset()
                                picking.move_line_ids.flush_recordset()

                                # Use raw SQL to reliably bypass any ORM restrictions on done pickings
                                self.env.cr.execute(
                                    "UPDATE stock_picking SET scheduled_date=%s, date_done=%s, date=%s WHERE id=%s",
                                    (formatted_date, formatted_date, formatted_date, picking.id)
                                )
                                self.env.cr.execute(
                                    "UPDATE stock_move SET date=%s WHERE picking_id=%s",
                                    (formatted_date, picking.id)
                                )
                                self.env.cr.execute(
                                    "UPDATE stock_move_line SET date=%s WHERE picking_id=%s",
                                    (formatted_date, picking.id)
                                )

                                # Invalidate cache so the ORM loads the newly updated SQL values
                                picking.invalidate_recordset()
                                picking.move_ids.invalidate_recordset()
                                picking.move_line_ids.invalidate_recordset()
                            except Exception as date_e:
                                _logger.warning(f"Could not apply excel date {formatted_date} to picking {picking.name}: {date_e}")
                                
                        transferred += 1
                        created += 1
                        _logger.info(f"Row {row_idx} imported and transferred successfully as Label {label.name}.")
                except Exception as e:
                    _logger.error(f"Error on row {row_idx}: {e}")
                    
                if created > 0 and created % 100 == 0:
                    current_cr.commit()
                    # Close and recreate cursor to aggressively free Odoo ORM cache
                    current_cr.close()
                    current_cr = self.env.registry.cursor()
                    current_env = odoo.api.Environment(current_cr, self.env.uid, self.env.context)(su=True)
                    self.env = current_env
                    gc.collect()
                    _logger.info(f"Memory Checkpoint: Batch committed at row {row_idx}. ORM cache cleared.")
                    
            current_cr.commit()
            
        finally:
            if not current_cr.closed:
                current_cr.close()
            self.env = original_env
                
        return {'created': created, 'transferred': transferred}

    def _process_row(self, row, row_idx):
        # Helper to get row value case-insensitively
        def get_val(key_name):
            for k in row.keys():
                if str(k).strip().lower() == key_name.lower():
                    return row[k]
            return None
            
        company_name = str(get_val('Company') or '').strip()
        if not company_name:
            raise UserError(f"Company column is missing or empty on row {row_idx}.")
            
        excel_company = self.env['res.company'].search([('name', '=ilike', company_name)], limit=1)
        if not excel_company:
            raise UserError(f"Company '{company_name}' not found in Odoo for row {row_idx}.")
            
        _logger.info(f"Row {row_idx}: Using Excel Company: '{excel_company.name}' (ID: {excel_company.id})")

        # 1. Product Template & Variant matching
        product_name = str(get_val('Product') or '').strip()
        if not product_name:
            raise UserError(f"Product column is missing on row {row_idx}.")
            
        try:
            variant = self._resolve_product_variant(row, product_name, get_val, excel_company)
            if variant is None:
                raise Exception("_resolve_product_variant returned explicitly None!")
            if variant.company_id and variant.company_id.id != excel_company.id:
                raise UserError(f"Product Variant {variant.name} belongs to company {variant.company_id.name}, but Excel row specifies {excel_company.name}.")
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            _logger.error(f"EXCEPTION TRACE: {tb}")
            raise e
        
        # 2. Find Branch
        branch_name = str(get_val('Branch') or '').strip()
        branch = False
        if branch_name:
            branch = self.env['res.branch'].search([('name', '=ilike', branch_name), ('company_id', '=', excel_company.id)], limit=1)
            if not branch:
                branch = self.env['res.branch'].create({'name': branch_name, 'company_id': excel_company.id})
                
        # 3. Find Source Location
        src_loc_name = str(get_val('Source Location') or '').strip()
        src_loc = False
        if src_loc_name:
            src_loc = self.env['stock.location'].search([
                '|', ('complete_name', '=ilike', src_loc_name), ('name', '=ilike', src_loc_name),
                ('company_id', 'in', [excel_company.id, False])
            ], limit=1)
            if not src_loc:
                src_loc = self.env['stock.location'].create({
                    'name': src_loc_name, 
                    'usage': 'internal',
                    'company_id': excel_company.id
                })
            elif src_loc.company_id and src_loc.company_id.id != excel_company.id:
                raise UserError(f"Source Location '{src_loc_name}' belongs to {src_loc.company_id.name}, expected {excel_company.name}")
                
        # 4. Find Destination Location
        dest_loc_name = str(get_val('Destination Location') or '').strip()
        dest_loc = False
        if dest_loc_name:
            dest_loc = self.env['stock.location'].search([
                '|', ('complete_name', '=ilike', dest_loc_name), ('name', '=ilike', dest_loc_name),
                ('company_id', 'in', [excel_company.id, False])
            ], limit=1)
            if not dest_loc:
                dest_loc = self.env['stock.location'].create({
                    'name': dest_loc_name,
                    'usage': 'internal',
                    'branch_id': branch.id if branch else False,
                    'company_id': excel_company.id
                })
            elif dest_loc.company_id and dest_loc.company_id.id != excel_company.id:
                raise UserError(f"Destination Location '{dest_loc_name}' belongs to {dest_loc.company_id.name}, expected {excel_company.name}")
                
        # 5. Find Purchase Order
        po_name = str(get_val('Choose Purchase Order') or get_val('Purchase Order') or '').strip()
        po = False
        if po_name:
            po = self.env['purchase.order'].search([
                ('name', '=ilike', po_name),
                ('company_id', '=', excel_company.id)
            ], limit=1)
            
        # Purity
        purity_name = str(get_val('Purity') or '').strip()
        purity = False
        if purity_name:
            purity = self.env['gold.purity'].search([('name', '=ilike', purity_name)], limit=1)
            if not purity:
                purity = self.env['gold.purity'].create({'name': purity_name})

        # Making charge type mapping
        sale_mc_type_raw = str(get_val('Sale Making Charge Type') or '').strip()
        sale_mc_type = self._map_mc_type(sale_mc_type_raw)
            
        purch_mc_type_raw = str(get_val('Purchase Making Charge Type') or '').strip()
        purch_mc_type = self._map_mc_type(purch_mc_type_raw)
        
        _logger.info(f"Row {row_idx}: Excel Purchase Making Charge Type = '{purch_mc_type_raw}' -> Normalized Odoo Value = '{purch_mc_type}'")

        # Helper to convert to float
        def get_float(col):
            try:
                val = get_val(col)
                if val is None or str(val).strip() == '':
                    return 0.0
                return float(str(val).replace(',', ''))
            except:
                return 0.0

        label_name = str(get_val('Label Name') or '').strip()
        
        # 6. Normalize Barcode
        raw_barcode = get_val('Barcode')
        _logger.info(f"Excel Barcode: {raw_barcode}")
        
        normalized_barcode = False
        if raw_barcode is not None and str(raw_barcode).strip():
            if isinstance(raw_barcode, float) and raw_barcode.is_integer():
                normalized_barcode = str(int(raw_barcode))
            elif isinstance(raw_barcode, str) and raw_barcode.endswith('.0'):
                normalized_barcode = raw_barcode[:-2]
            else:
                normalized_barcode = str(raw_barcode).strip()
                
        _logger.info(f"Normalized Barcode: {normalized_barcode}")
        _logger.info(f"Creating Product Label with Barcode: {normalized_barcode}")

        # Parse Bill Date to correctly offset the age_import value
        excel_age = int(get_float('Age (Days)'))
        age_import_val = excel_age
        
        raw_bill_date = get_val('Bill Date') or get_val('Date')
        parsed_date = None
        if raw_bill_date:
            if hasattr(raw_bill_date, 'strftime'):
                parsed_date = raw_bill_date
            elif isinstance(raw_bill_date, str):
                try:
                    from dateutil import parser
                    parsed_date = parser.parse(raw_bill_date)
                except Exception:
                    pass
                    
        if parsed_date:
            from odoo import fields
            today = fields.Date.today()
            parsed_date_only = parsed_date.date() if hasattr(parsed_date, 'date') else parsed_date
            # By subtracting the days since bill_date, Odoo will calculate the exact excel_age for today
            days_diff = (today - parsed_date_only).days
            age_import_val = excel_age - days_diff

        excel_pmc_value = get_float('Purchase Making Charge')
        excel_pmc_amount = get_float('Purchase Making Charge Amount')
        
        # Odoo's purchase_making_charge_amount is a computed field.
        # If type is 'amount', the compute method strictly reads from purchase_making_charge_value.
        # We must feed the excel amount into the value field to drive the computation correctly.
        final_pmc_value = excel_pmc_amount if purch_mc_type == 'amount' and excel_pmc_amount else excel_pmc_value
        
        _logger.info(f"Row {row_idx}: Excel Purchase Making Charge = {excel_pmc_value}")
        _logger.info(f"Row {row_idx}: Excel Purchase Making Charge Amount = {excel_pmc_amount}")
        _logger.info(f"Row {row_idx}: Source field 'purchase_making_charge_value' set to {final_pmc_value} to drive computation.")

        vals = {
            'label_name': label_name,
            'name': label_name or 'New',
            'product_id': variant.id,
            'product_tmpl_id': variant.product_tmpl_id.id,
            'branch_id': branch.id if branch else False,
            'company_id': excel_company.id,
            'source_location_id': src_loc.id if src_loc else False,
            'branch_location_id': dest_loc.id if dest_loc else False,
            'purchase_id': po.id if po else False,
            
            'barcode': normalized_barcode,
            'age_import': age_import_val,
            'tag_weight': get_float('Tag Weight (g)'),
            'purity_id': purity.id if purity else False,
            'sale_purity_id': purity.id if purity else False,
            
            'sale_gross_weight': get_float('Sale Gross Weight (g)'),
            'sale_stone_weight': get_float('Sale Stone Weight (g)'),
            'sale_stone_weight_ct': get_float('Sale Stone Weight (ct)'),
            'sale_diamond_weight_gm': get_float('Diamond Weight (g)'),
            'sale_diamond_weight_ct': get_float('Diamond Weight (ct)'),
            
            'sale_making_charge_type': sale_mc_type,
            'sale_making_charge_value': get_float('Sale Making Charge Max'),
            'sale_making_charge_min': get_float('Sale Making Charge Min'),
            'sale_stone_rate': get_float('Sale Stone Amount'),
            'sale_diamond_rate': get_float('Sale Diamond Amount'),
            
            'purchase_price_per_gram': get_float('Purchase fine Rate / gram'),
            'others': get_float('Others'),
            'other_weight_g': get_float('Other Weight (g)'),
            
            'purchase_gross_weight': get_float('Purchase Gross Amount (g)'),
            'purchase_stone_weight': get_float('Purchase Stone Weight (g)_1') if get_val('Purchase Stone Weight (g)_1') is not None else get_float('Purchase Stone Weight (g)'),
            'purchase_stone_weight_ct': get_float('Purchase Stone Weight (ct)_1') if get_val('Purchase Stone Weight (ct)_1') is not None else get_float('Purchase Stone Weight (ct)'),
            'purchase_diamond_weight_gm': get_float('Diamond Weight (g)_1') if get_val('Diamond Weight (g)_1') is not None else get_float('Diamond Weight (g)'),
            'purchase_diamond_weight_ct': get_float('Diamond Weight (ct)_1') if get_val('Diamond Weight (ct)_1') is not None else get_float('Diamond Weight (ct)'),
            
            'purchase_making_charge_type': purch_mc_type,
            'purchase_making_charge_value': final_pmc_value,
            
            'purchase_stone_rate': get_float('Purchase Stone Amount'),
            'purchase_diamond_rate': get_float('Purchase Diamond Amount'),
            
            'active': True,
        }
            
        label = self.env['product.label'].create(vals)
        _logger.info(f"Row {row_idx}: Final Product Label created with purchase_making_charge_value = {label.purchase_making_charge_value}, purchase_making_charge_amount = {label.purchase_making_charge_amount}")
        
        # Force product_tmpl_id via write to ensure it doesn't get cleared by any internal onchange
        write_vals = {}
        if variant.product_tmpl_id:
            write_vals['product_tmpl_id'] = variant.product_tmpl_id.id
            write_vals['product_id'] = variant.id
            
        # Ensure barcode wasn't overwritten by any automatic generation during create
        if normalized_barcode and label.barcode != normalized_barcode:
            write_vals['barcode'] = normalized_barcode
            
        if write_vals:
            label.write(write_vals)
            
        if parsed_date:
            try:
                formatted_create_date = parsed_date.strftime('%Y-%m-%d %H:%M:%S')
                self.env.cr.execute(
                    "UPDATE product_label SET create_date=%s WHERE id=%s",
                    (formatted_create_date, label.id)
                )
            except Exception as e:
                _logger.warning(f"Could not update create_date for label {label.id}: {e}")
            
        _logger.info(f"Final Product Label Barcode: {label.barcode}")
            
        return label

    def _map_mc_type(self, raw_val):
        val = str(raw_val).strip().lower()
        if 'rate' in val or 'per gram' in val:
            return 'rate_per_gram'
        elif 'percent' in val or '%' in val:
            return 'percent'
        elif 'amount' in val:
            return 'amount'
        return 'percent'

    def _resolve_product_variant(self, row, product_name, get_val_func, fixed_company):
        import re
        
        # Normalize product name
        norm_product_name = re.sub(r'\s+', ' ', str(product_name)).strip()
        _logger.info(f"Finding Product Template: Original '{product_name}' -> Normalized '{norm_product_name}'")
        
        # Search Product Template using broad search then python strict matching
        first_word = norm_product_name.split('(')[0].strip() if '(' in norm_product_name else norm_product_name
        domain = [
            ('name', 'ilike', first_word),
            ('company_id', 'in', [fixed_company.id, False])
        ]
        
        TemplateModel = self.env['product.template'].with_context(active_test=False).with_company(fixed_company)
        all_templates = TemplateModel.search(domain)
        
        matched_templates = []
        excel_name_no_spaces = re.sub(r'\s+', '', norm_product_name).upper()
        
        for t in all_templates:
            db_name_no_spaces = re.sub(r'\s+', '', str(t.name or '')).upper()
            if db_name_no_spaces == excel_name_no_spaces:
                matched_templates.append(t)
                
        if matched_templates:
            # Prioritize company-specific templates over shared templates, then by oldest ID
            matched_templates.sort(key=lambda t: (0 if t.company_id and t.company_id.id == fixed_company.id else 1, t.id))
            template = matched_templates[0]
            _logger.info(f"Found existing Product Template: {template.name} (ID: {template.id}) for Company {template.company_id.name if template.company_id else 'Shared'}")
        else:
            _logger.error(f"Excel Product Name: '{product_name}'")
            _logger.error(f"Normalized Name: '{norm_product_name}'")
            _logger.error(f"Fixed Company: '{fixed_company.name}'")
            _logger.error(f"Company ID: {fixed_company.id}")
            _logger.error(f"Search Domain: {domain}")
            raise UserError(f"Product Template '{norm_product_name}' not found for company '{fixed_company.name}'. Please ensure it is created before importing.")

        def clean_val(key):
            val = get_val_func(key)
            if val is None:
                return None
            return str(val).strip().title()

        attrs = {
            'TYPE': clean_val('TYPE'),
            'VARIETY': clean_val('VARIETY'),
            'DESIGN': clean_val('DESIGN'),
            'SIZE': clean_val('SIZE'),
            'STONE COLOUR': clean_val('STONE COLOUR'),
            'METAL COLOUR': clean_val('METAL COLOUR'),
        }

        exact_variant = self._get_existing_product_variant(template, attrs, fixed_company)
        return exact_variant

    def _get_existing_product_variant(self, template, attrs, fixed_company):
        import re
        import unicodedata
        from odoo.exceptions import UserError
        
        # Ensure the template is active
        if hasattr(template, 'active') and not template.active:
            raise UserError(f"Product Template '{template.name}' is archived. Unarchive it before importing.")

        def normalize_value(value):
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
            if variant.company_id and variant.company_id.id != fixed_company.id:
                continue
                
            if set(variant.product_template_attribute_value_ids.ids) == target_ptav_set:
                exact_variant = variant
                break
                
        generation_triggered = False
        if not exact_variant:
            _logger.info(f"Found Product Template:\n{template.name} ID:{template.id}\n\nSearching Variant:\n" + "\n".join([f"{k}:{v}" for k, v in attrs.items()]))
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
                if variant.company_id and variant.company_id.id != fixed_company.id:
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
            _logger.error(f"Company: {fixed_company.name} (ID: {fixed_company.id})")
            _logger.error(f"Attribute Creation Modes: {creation_modes}")
            _logger.error(f"Requested PTAV IDs: {ptav_ids}")
            _logger.error(f"Requested PTAV Names: {ptav_names}")
            _logger.error(f"Total variants on template: {count_after}")
            _logger.error(f"Variants before generation: {count_before} | After: {count_after}")
            _logger.error(f"Generation triggered: {generation_triggered}")
            
            _logger.error("Available Variants:")
            for variant in template.product_variant_ids:
                v_ptav_ids = variant.product_template_attribute_value_ids.ids
                v_ptav_names = variant.product_template_attribute_value_ids.mapped('display_name')
                _logger.error(f"Variant ID: {variant.id}\nAttributes: {v_ptav_names}")
                
            _logger.error("--------------------------------------")
            
            missing_combination = ", ".join(ptav_names)
            error_msg = f"Product Variant not found for template '{template.name}'. Attribute combination [{missing_combination}] does not exist."
            raise UserError(error_msg)
            
        _logger.info(f"Matched Variant:\n{template.name} - {' - '.join(exact_variant.product_template_attribute_value_ids.mapped('name'))}")
                
        return exact_variant
