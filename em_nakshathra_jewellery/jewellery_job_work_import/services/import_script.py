# -*- coding: utf-8 -*-
import base64
import io
import logging
import re
from datetime import datetime, date
from collections import defaultdict
import openpyxl
from odoo.exceptions import UserError
from odoo import _

_logger = logging.getLogger(__name__)

class JobWorkImportService:
    def __init__(self, env):
        self.env = env
        self.stats = {
            'jobs_created': 0,
            'lines_created': 0,
            'issues_created': 0,
            'receives_created': 0,
            'bills_created': 0
        }
        self.variant_cache = {}
        self.template_cache = {}
        self.attribute_cache = {}
        self.attribute_value_cache = {}
        self.purity_cache = {}
        self.partner_cache = {}

    def safe_int(self, val, default=1):
        if val in (None, "", False):
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def safe_float(self, val, default=0.0):
        if val in (None, "", False):
            return default
        try:
            f = float(val)
            import math
            if math.isnan(f):
                return default
            return f
        except (ValueError, TypeError):
            return default

    def _normalize_header(self, h):
        if not h:
            return ""
        s = str(h).replace('\r', ' ').replace('\n', ' ').strip()
        s = re.sub(r'\s*/\s*', '/', s)
        s = re.sub(r'\s+', ' ', s)
        return s.lower()

    def is_mc_missing(self, val):
        if val is None or val is False:
            return True
        if isinstance(val, (int, float)):
            import math
            return math.isnan(val)
        if isinstance(val, str):
            v = val.strip().lower()
            if v in ('', 'none', 'null', 'nan', 'false'):
                return True
            try:
                f = float(v.replace(',', ''))
                import math
                return math.isnan(f)
            except (ValueError, TypeError):
                return True
        try:
            f = float(val)
            import math
            return math.isnan(f)
        except (ValueError, TypeError):
            return True

    def parse_mc_value(self, val):
        if self.is_mc_missing(val):
            return None
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val).strip().replace(',', ''))
        except (ValueError, TypeError):
            return None

    def safe_date(self, value):
        if not value:
            return date.today()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        value = str(value).strip()
        formats = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d")
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except Exception:
                pass
        return date.today()

    def get_or_create_partner(self, name, company):
        if not name or name in (None, "", False):
            return False
        name_clean = str(name).strip()
        key = (name_clean, company.id)
        if key in self.partner_cache:
            return self.partner_cache[key]
            
        partner = self.env['res.partner'].search([('name', '=', name_clean)], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({
                'name': name_clean,
                'is_job_worker': True,
                'company_id': False, # Shared
            })
            _logger.info(f"Created Job Worker Partner: '{name_clean}'")
        else:
            if not partner.is_job_worker:
                partner.write({'is_job_worker': True})
                
        self.partner_cache[key] = partner
        return partner

    def get_or_create_purity(self, name):
        if not name or name in (None, "", False):
            return False
        name_clean = str(name).strip().upper()
        if name_clean in self.purity_cache:
            return self.purity_cache[name_clean]
            
        purity = self.env['gold.purity'].search([('name', '=ilike', name_clean)], limit=1)
        if not purity:
            pct = 100.0
            if '22' in name_clean:
                pct = 91.6
            elif '18' in name_clean:
                pct = 75.0
            elif '24' in name_clean:
                pct = 99.9
            elif '92' in name_clean:
                pct = 92.0
            elif '99' in name_clean:
                pct = 99.0
            elif 'SILVER' in name_clean or 'SLV' in name_clean:
                pct = 99.0
                
            purity = self.env['gold.purity'].create({
                'name': name_clean,
                'percentage': pct
            })
            _logger.info(f"Created Purity: '{name_clean}' ({pct}%)")
            
        self.purity_cache[name_clean] = purity
        return purity

    def _resolve_product(self, raw_name, attrs, current_company, context_info):
        context_info['stage'] = "[3] Finding product template"
        template_name = re.sub(r'\s+', ' ', str(raw_name or '')).strip()
        if not template_name:
            return None
            
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
            context_info['stage'] = "[5] Resolving product variant"
            return self.variant_cache[cache_key]
            
        template_cache_key = (current_company.id, template_name.lower())
        
        if template_cache_key in self.template_cache:
            template = self.template_cache[template_cache_key]
        else:
            TemplateModel = self.env['product.template'].with_context(active_test=False)
            first_word = template_name.split('(')[0].strip() if '(' in template_name else template_name
            
            domain = [
                ('name', 'ilike', first_word),
                ('company_id', 'in', [current_company.id, False])
            ]
            all_templates = TemplateModel.search(domain)
            
            matched_templates = []
            excel_name_norm = re.sub(r'\s+', '', template_name).upper()
            
            for t in all_templates:
                db_name_norm = re.sub(r'\s+', '', str(t.name or '')).upper()
                if db_name_norm == excel_name_norm:
                    matched_templates.append(t)
                    
            if matched_templates:
                matched_templates.sort(key=lambda t: (0 if t.company_id and t.company_id.id == current_company.id else 1, t.id))
                template = matched_templates[0]
            else:
                raise UserError(f"Product Template '{template_name}' not found for company '{current_company.name}'.")
                
            self.template_cache[template_cache_key] = template

        # Check if the product template has configured attribute lines with values
        has_attribute_values = bool(template.attribute_line_ids and any(line.value_ids for line in template.attribute_line_ids))

        if not has_attribute_values:
            # CASE B: Product Template has no configured attribute values
            context_info['stage'] = "[5] Resolving product variant"

            variants = self.env['product.product'].with_context(active_test=False).search([
                ('product_tmpl_id', '=', template.id),
                ('company_id', 'in', [current_company.id, False])
            ])

            if len(variants) > 1:
                variant_ids_str = ", ".join(str(v.id) for v in variants)
                error_msg = (
                    f"Multiple product variants found for Product Template '{template.name}' "
                    f"which has no configured attributes. Variant IDs: [{variant_ids_str}]."
                )
                _logger.error(error_msg)
                raise UserError(error_msg)
            elif len(variants) == 1:
                existing_variant = variants[0]
            else:
                existing_variant = template.product_variant_id
                if not existing_variant:
                    template._create_variant_ids()
                    existing_variant = template.product_variant_id or template.product_variant_ids[:1]

            if not existing_variant:
                raise UserError(f"No existing Product Variant found for Product Template '{template.name}' with no configured attributes.")

            if not existing_variant.active:
                existing_variant.active = True

            variant_name = existing_variant.display_name or existing_variant.name or template.name
            _logger.info(
                f"Product Template: {template.name}\n"
                f"Has configurable attributes: False\n"
                f"Existing Product Variant ID: {existing_variant.id}\n"
                f"Existing Product Variant Name: {variant_name}\n"
                f"Using existing single/default variant for Receive Voucher validation."
            )
            self.variant_cache[cache_key] = existing_variant
            return existing_variant

        # CASE A: Product Template has configured attribute values
        context_info['stage'] = "[4] Resolving six attribute values"
        def normalize_value(value):
            import unicodedata
            if not value or str(value).strip().lower() in ['false', 'none', '']:
                return "none"
            val_str = str(value)
            val_str = unicodedata.normalize('NFKC', val_str)
            val_str = val_str.replace('”', '"').replace('“', '"').replace('„', '"')
            val_str = val_str.replace('‘', "'").replace('’', "'")
            val_str = re.sub(r'\s*[-\u2013\u2014]\s*', '-', val_str)
            val_str = re.sub(r'\s*"\s*', '"', val_str)
            val_str = re.sub(r"\s*'\s*", "'", val_str)
            return " ".join(val_str.strip().split()).casefold()

        ptav_ids = []
        for attr_name, attr_val in attrs.items():
            attribute = self.env['product.attribute'].search([('name', '=ilike', str(attr_name).strip())], limit=1)
            if not attribute:
                raise UserError(f"Product Attribute '{attr_name}' not found. Please ensure it exists.")
                
            norm_excel = normalize_value(attr_val)
            
            available_values = attribute.value_ids
            matched_value = next(
                (v for v in available_values if normalize_value(v.name) == norm_excel),
                False,
            )
            
            if not matched_value:
                raise UserError(f"Product Attribute Value {repr(attr_val)} for Attribute '{attr_name}' not found. (Normalized search was: {repr(norm_excel)})")
                
            ptal = template.attribute_line_ids.filtered(lambda l: l.attribute_id.id == attribute.id)
            if not ptal:
                ptal = self.env['product.template.attribute.line'].create({
                    'product_tmpl_id': template.id,
                    'attribute_id': attribute.id,
                    'value_ids': [(4, matched_value.id)]
                })
            elif matched_value.id not in ptal.value_ids.ids:
                ptal.write({'value_ids': [(4, matched_value.id)]})
                
            ptav = self.env['product.template.attribute.value'].search([
                ('attribute_line_id', '=', ptal.id),
                ('product_attribute_value_id', '=', matched_value.id)
            ], limit=1)
            
            if not ptav:
                self.env.flush_all()
                ptav = self.env['product.template.attribute.value'].search([
                    ('attribute_line_id', '=', ptal.id),
                    ('product_attribute_value_id', '=', matched_value.id)
                ], limit=1)
                
            if not ptav:
                raise UserError(f"Failed to resolve PTAV for '{norm_excel}' on Attribute '{attr_name}' for Template '{template.name}'.")
                
            ptav_ids.append(ptav.id)
            
        context_info['stage'] = "[5] Resolving product variant"
        exact_variant = None
        target_ptav_set = set(ptav_ids)
        target_ptavs = self.env['product.template.attribute.value'].browse(ptav_ids)
        
        for variant in template.with_context(active_test=False).product_variant_ids:
            if variant.company_id and variant.company_id.id not in [current_company.id, False]:
                continue
            if set(variant.product_template_attribute_value_ids.ids) == target_ptav_set:
                exact_variant = variant
                if not exact_variant.active:
                    exact_variant.active = True
                break
                
        if not exact_variant:
            # Trigger standard generation mechanisms
            template._create_variant_ids()
            exact_variant = template._create_product_variant(target_ptavs)
            
            # Re-fetch just in case _create_product_variant returns empty for some configs
            if not exact_variant or not exact_variant.id:
                template.invalidate_recordset(['product_variant_ids'])
                for variant in template.with_context(active_test=False).product_variant_ids:
                    if variant.company_id and variant.company_id.id not in [current_company.id, False]:
                        continue
                    if set(variant.product_template_attribute_value_ids.ids) == target_ptav_set:
                        exact_variant = variant
                        if not exact_variant.active:
                            exact_variant.active = True
                        break

        if not exact_variant or not exact_variant.id:
            raise UserError("No matching existing Product Variant was found, and the system failed to generate one. Check attribute combinations.")
            
        self.variant_cache[cache_key] = exact_variant
        return exact_variant

    def _normalize_excel_text(self, value):
        import math
        if value is None:
            return ""
        if isinstance(value, float) and math.isnan(value):
            return ""
        val_str = str(value).strip()
        if val_str.lower() == 'nan':
            return ""
        if val_str.lower() == 'false':
            return ""
        # IMPORTANT: Do not convert the string "None" to an empty string,
        # because it is a valid attribute value for Jewellery.
        return val_str

    def process_import(self, file_base64, task_id):
        _logger.info("Starting Jewellery Job Work Bulk Import...")
        try:
            file_content = base64.b64decode(file_base64)
            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True, read_only=True)
            sheet = wb.active
            
            _logger.info(f"Workbook Sheets: {wb.sheetnames}")
            _logger.info(f"Selected Sheet: {sheet.title}")
            
            header_row_idx = -1
            raw_headers = []
            
            for i, row in enumerate(sheet.iter_rows(values_only=True)):
                row_vals = [self._normalize_excel_text(c) for c in row]
                # Try to find a row containing 'Company'
                if any(self._normalize_header(c) == "company" or c.lower() == "company" for c in row_vals):
                    header_row_idx = i
                    raw_headers = [c if c is not None else "" for c in row]
                    break
                    
            if header_row_idx == -1:
                raise UserError("Could not find the header row containing 'Company'.")
                
            _logger.info(f"Detected Header Row Index: {header_row_idx}")
            
            # Dynamic resolution of Purchase Making Charge column
            mc_norm_target = "job work line/purchase making charge"
            mc_matches = [idx for idx, h in enumerate(raw_headers) if self._normalize_header(h) == mc_norm_target]
            if len(mc_matches) > 1:
                error_msg = "Duplicate header error: 'Job Work Line/Purchase Making Charge' appears multiple times in the Excel header row."
                self.env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', error_msg)
                raise UserError(error_msg)
            
            if len(mc_matches) == 1:
                mc_col_idx = mc_matches[0]
                mc_header_name = str(raw_headers[mc_col_idx]).strip()
            else:
                mc_col_idx = None
                mc_header_name = "Job Work Line/Purchase Making Charge"

            _logger.info("==================================================")
            _logger.info("Detected Excel Headers:")
            for col_idx, raw_h in enumerate(raw_headers):
                _logger.info(f"{col_idx} -> {raw_h}")
            if mc_col_idx is not None:
                _logger.info(f"{mc_col_idx} -> {mc_header_name}")
            else:
                _logger.info("Warning: 'Job Work Line/Purchase Making Charge' column not detected in Excel headers.")
            _logger.info("==================================================")
            
            header_map = {}
            norm_header_map = {}
            for col_idx, h in enumerate(raw_headers):
                if h:
                    norm_h = self._normalize_header(h)
                    if norm_h not in norm_header_map:
                        norm_header_map[norm_h] = col_idx
                    compact_norm = re.sub(r'\s+', '', str(h))
                    if compact_norm not in header_map:
                        header_map[compact_norm] = col_idx
                    _logger.info(f"Detected Header: Column {col_idx + 1} (Index {col_idx}) = {h}")
                    
            # Check required columns
            required_cols = [
                ('job work number', 'Job Work Number', 'JobWorkNumber'),
                ('job worker', 'Job Worker', 'JobWorker'),
                ('order date', 'Order Date', 'OrderDate'),
                ('branch', 'Branch', 'Branch'),
                ('company', 'Company', 'Company'),
                ('type', 'Type', 'Type'),
                ('variety', 'Variety', 'Variety'),
                ('design', 'Design', 'Design'),
                ('size', 'Size', 'Size'),
                ('stone colour', 'Stone Colour', 'StoneColour'),
                ('metal colour', 'Metal Colour', 'MetalColour'),
                ('job work line/product template', 'Job Work Line/Product Template', 'JobWorkLine/ProductTemplate'),
                ('job work line/quantity', 'Job Work Line/ Quantity', 'JobWorkLine/Quantity'),
                ('receive voucher/job type selection', 'Receive Voucher/Job Type Selection', 'ReceiveVoucher/JobTypeSelection'),
            ]
            missing = [original for norm, original, compact in required_cols if norm not in norm_header_map and compact not in header_map]
            if missing:
                error_msg = f"Missing Excel Header: {', '.join(missing)}"
                self.env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', error_msg)
                raise UserError(error_msg)
                
            # Align rows with headers
            grouped_data = defaultdict(list)
            
            # Start reading from the row AFTER the header row
            for offset, row in enumerate(sheet.iter_rows(min_row=header_row_idx + 2, values_only=True)):
                real_row_idx = header_row_idx + 2 + offset
                if not any(c not in (None, "", False) for c in row):
                    continue
                    
                row_dict = {}
                for compact_norm, col_idx in header_map.items():
                    if col_idx < len(row):
                        row_dict[compact_norm] = row[col_idx]
                    else:
                        row_dict[compact_norm] = None

                for norm_h, col_idx in norm_header_map.items():
                    if col_idx < len(row):
                        row_dict[norm_h] = row[col_idx]
                    else:
                        row_dict[norm_h] = None

                # Specific dynamic resolution of Purchase Making Charge
                if mc_col_idx is not None and mc_col_idx < len(row):
                    row_dict['JobWorkLine/PurchaseMakingCharge'] = row[mc_col_idx]
                    row_dict['_raw_mc'] = row[mc_col_idx]
                else:
                    row_dict['JobWorkLine/PurchaseMakingCharge'] = None
                    row_dict['_raw_mc'] = None

                row_dict['_mc_col_idx'] = mc_col_idx
                row_dict['_mc_header_name'] = mc_header_name
                row_dict['_row_idx'] = real_row_idx

                jw_num = str(row_dict.get('JobWorkNumber') or row_dict.get('job work number') or '').strip()
                if not jw_num or jw_num.endswith('Total'):
                    continue
                grouped_data[jw_num].append(row_dict)
                
            _logger.info(f"Found {len(grouped_data)} unique Job Work Numbers in Excel.")
            
            # 1. PRE-FLIGHT VALIDATION: Check Odoo database for any duplicate Job Work Numbers
            all_jw_numbers = list(grouped_data.keys())
            existing_jws = self.env['jewellery.job.work'].search([('name', 'in', all_jw_numbers)])
            if existing_jws:
                duplicate_names = [jw.name for jw in existing_jws]
                _logger.info(f"Found existing Job Works. Updating their dates and aborting import: {', '.join(duplicate_names)}")
                
                for dup_name in duplicate_names:
                    if dup_name in grouped_data:
                        # Extract the correct order date from Excel for this duplicate
                        dup_lines = grouped_data[dup_name]
                        if dup_lines:
                            dup_first_line = dup_lines[0]
                            dup_order_date = self.safe_date(dup_first_line.get('OrderDate') if dup_first_line.get('OrderDate') is not None else dup_first_line.get('order date'))
                            
                            existing_jw = self.env['jewellery.job.work'].search([('name', '=', dup_name)], limit=1)
                            if existing_jw and dup_order_date:
                                # 1. Update Job Work date via SQL to bypass readonly state
                                self.env.cr.execute(
                                    "UPDATE jewellery_job_work SET order_date=%s WHERE id=%s",
                                    (dup_order_date, existing_jw.id)
                                )
                                existing_jw.invalidate_recordset(['order_date'])
                                
                                # 2. Update Issue Voucher date
                                issues = self.env['jewellery.issue.voucher'].search([('job_work_id', '=', existing_jw.id)])
                                for issue in issues:
                                    self.env.cr.execute(
                                        "UPDATE jewellery_issue_voucher SET order_date=%s WHERE id=%s",
                                        (dup_order_date, issue.id)
                                    )
                                    issue.invalidate_recordset(['order_date'])
                                    
                                # 3. Update Receive Voucher date and Stock Moves
                                receives = self.env['jewellery.receive.voucher'].search([('job_work_id', '=', existing_jw.id)])
                                for receive in receives:
                                    self.env.cr.execute(
                                        "UPDATE jewellery_receive_voucher SET order_date=%s WHERE id=%s",
                                        (dup_order_date, receive.id)
                                    )
                                    receive.invalidate_recordset(['order_date'])
                                    
                                    picking = receive.picking_id
                                    if picking:
                                        formatted_date = dup_order_date.strftime('%Y-%m-%d 12:00:00')
                                        try:
                                            picking.flush_recordset()
                                            picking.move_ids.flush_recordset()
                                            picking.move_line_ids.flush_recordset()
                                            
                                            self.env.cr.execute(
                                                "UPDATE stock_picking SET scheduled_date=%s, date_done=%s, date=%s WHERE id=%s",
                                                (formatted_date, formatted_date, formatted_date, picking.id)
                                            )
                                            self.env.cr.execute(
                                                "UPDATE stock_move SET date=%s, date_deadline=%s WHERE picking_id=%s",
                                                (formatted_date, formatted_date, picking.id)
                                            )
                                            self.env.cr.execute(
                                                "UPDATE stock_move_line SET date=%s WHERE picking_id=%s",
                                                (formatted_date, picking.id)
                                            )
                                            
                                            picking.invalidate_recordset()
                                            picking.move_ids.invalidate_recordset()
                                            picking.move_line_ids.invalidate_recordset()
                                        except Exception as date_e:
                                            _logger.warning(f"Could not apply excel date {formatted_date} to existing picking {picking.name}: {date_e}")

                # Commit the date updates so they are saved to the database permanently
                self.env.cr.commit()
                
                # Now raise the error to completely abort the import and prevent any new records from being created
                error_msg = f"DUPLICATION ERROR: The following Job Work numbers already exist in Odoo: {', '.join(duplicate_names)}. Their dates have been updated, but the import of any new records is aborted."
                self.env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', error_msg)
                raise UserError(error_msg)
                
            # 2. Phase 2: Process Job Works
            total_jws = len(grouped_data)
            count = 0
            
            stage = "Initializing"
            current_row_idx = "Unknown"
            current_jw = "Unknown"
            current_template = "Unknown"
            current_attrs = {}
            
            try:
                for jw_num, lines in grouped_data.items():
                    current_jw = jw_num
                    first_line = lines[0]
                    current_row_idx = first_line.get('_row_idx', 'Unknown')
                    
                    stage = "[1] Finding company"
                    company_raw = first_line.get('Company') if first_line.get('Company') is not None else first_line.get('company')
                    company_name = self._normalize_excel_text(company_raw)
                    _logger.info(f"Excel Row: {current_row_idx}\nDetected Company Column: {header_map.get('Company', -1)}\nRaw Company Cell: {repr(company_raw)}\nNormalized Company Value: {repr(company_name)}")
                    template_raw = first_line.get('JobWorkLine/ProductTemplate') if first_line.get('JobWorkLine/ProductTemplate') is not None else first_line.get('job work line/product template')
                    template_name = self._normalize_excel_text(template_raw)
                    if not template_name:
                        raise UserError(f"Product Template is missing in Excel row {current_row_idx}.\nDetected Product Template column: {header_map.get('JobWorkLine/ProductTemplate', -1)}\nRaw value: {repr(template_raw)}")
                    
                    if not company_name:
                        raise UserError(f"Company is missing in Excel row {current_row_idx}.\nDetected Company column: {header_map.get('Company', -1)}\nRaw value: {repr(company_raw)}")
                    silver_company = self.env['res.company'].search([('name', '=', company_name)], limit=1)
                    if not silver_company:
                        if "SILVER LLP" in company_name.upper():
                            silver_company = self.env['res.company'].search([('name', 'ilike', 'SILVER LLP')], limit=1)
                        elif "HYD" in company_name.upper():
                            silver_company = self.env['res.company'].search([('name', 'ilike', 'HYD')], limit=1)
                        else:
                            silver_company = self.env['res.company'].search([('name', 'ilike', company_name)], limit=1)
                            
                    if not silver_company:
                        raise UserError(f"Company '{company_name}' not found in database.")
                        
                    stage = "[2] Finding branch"
                    branch_name = str(first_line.get('Branch') or first_line.get('branch') or 'HEAD OFFICE').strip()
                    silver_branch = self.env['res.branch'].search([('name', '=', branch_name), ('company_id', '=', silver_company.id)], limit=1)
                    if not silver_branch:
                        silver_branch = self.env['res.branch'].search([('company_id', '=', silver_company.id)], limit=1)
                        
                    stage = "[11] Setting source location"
                    silver_warehouse = self.env['stock.warehouse'].search([('company_id', '=', silver_company.id)], limit=1)
                    if not silver_warehouse:
                        raise UserError(f"Location could not be resolved. No warehouse found for company '{silver_company.name}'")
                        
                    stock_loc = silver_warehouse.lot_stock_id
                    
                    stage = "[12] Setting destination location"
                    subcon_loc = self.env['stock.location'].search([
                        ('name', '=', 'Subcontracting Location'),
                        ('company_id', '=', silver_company.id)
                    ], limit=1)
                    if not subcon_loc:
                        subcon_loc = self.env.ref('stock.stock_location_suppliers')
                        
                    stage = "[6] Creating Job Work"
                    # Resolve Worker
                    raw_worker = first_line.get('JobWorker') if first_line.get('JobWorker') is not None else first_line.get('job worker')
                    worker = self.get_or_create_partner(raw_worker, silver_company)
                    if not worker:
                        raise UserError(f"Worker '{raw_worker}' could not be resolved for Job Work {jw_num}.")
                        
                    order_date = self.safe_date(first_line.get('OrderDate') if first_line.get('OrderDate') is not None else first_line.get('order date'))

                    # Pre-validate lines to ensure we only create Job Work if there is at least one valid line
                    valid_line_specs = []

                    for line in lines:
                        current_row_idx = line.get('_row_idx', 'Unknown')
                        current_template = str(line.get('JobWorkLine/ProductTemplate') or line.get('job work line/product template') or '')
                        mc_col_idx_line = line.get('_mc_col_idx')
                        mc_header_name_line = line.get('_mc_header_name', 'Job Work Line/Purchase Making Charge')
                        raw_mc = line.get('JobWorkLine/PurchaseMakingCharge')
                        if raw_mc is None and 'PurchaseMakingCharge' in line:
                            raw_mc = line.get('PurchaseMakingCharge')
                        if raw_mc is None and 'job work line/purchase making charge' in line:
                            raw_mc = line.get('job work line/purchase making charge')

                        if self.is_mc_missing(raw_mc):
                            _logger.info(
                                f"Excel Row: {current_row_idx}\n"
                                f"Purchase Making Charge Column Index: {mc_col_idx_line}\n"
                                f"Purchase Making Charge Header: {mc_header_name_line}\n"
                                f"Raw Purchase Making Charge: {raw_mc}\n"
                                f"Normalized Purchase Making Charge: Missing/Blank\n"
                                f"Skipping row because Purchase Making Charge is missing."
                            )
                            continue

                        mc_val = self.parse_mc_value(raw_mc)
                        _logger.info(
                            f"Excel Row: {current_row_idx}\n"
                            f"Purchase Making Charge Column Index: {mc_col_idx_line}\n"
                            f"Purchase Making Charge Header: {mc_header_name_line}\n"
                            f"Raw Purchase Making Charge: {raw_mc}\n"
                            f"Normalized Purchase Making Charge: {mc_val}\n"
                            f"purchase_making_charge_value: {mc_val}"
                        )
                        
                        _logger.info(f"""
====================================
ROW {current_row_idx} VALIDATION
====================================
Job Worker:
{line.get('JobWorker') or line.get('job worker')}

Order Date:
{line.get('OrderDate') or line.get('order date')}

Branch:
{line.get('Branch') or line.get('branch')}

Company:
{company_name}

Type:
{line.get('Type') or line.get('type')}

Variety:
{line.get('Variety') or line.get('variety')}

Design:
{line.get('Design') or line.get('design')}

Size:
{line.get('Size') or line.get('size')}

Stone Colour:
{line.get('StoneColour') or line.get('stone colour')}

Metal Colour:
{line.get('MetalColour') or line.get('metal colour')}

Product Template:
{line.get('JobWorkLine/ProductTemplate') or line.get('job work line/product template')}

Purity:
{line.get('JobWorkLine/Purity') or line.get('job work line/purity')}

Quantity:
{line.get('JobWorkLine/Quantity') or line.get('job work line/quantity')}
====================================
""")
                        
                        _logger.info("==================================================")
                        _logger.info(f"JOB WORK IMPORT\nRow: {current_row_idx}")
                        _logger.info("==================================================")
                        _logger.info(
                            f"Company: {line.get('Company') or line.get('company')}\n"
                            f"Product Template: {current_template}\n"
                            f"Type: {line.get('Type') or line.get('type')}\n"
                            f"Variety: {line.get('Variety') or line.get('variety')}\n"
                            f"Design: {line.get('Design') or line.get('design')}\n"
                            f"Size: {line.get('Size') or line.get('size')}\n"
                            f"Stone Colour: {line.get('StoneColour') or line.get('stone colour')}\n"
                            f"Metal Colour: {line.get('MetalColour') or line.get('metal colour')}\n"
                            f"Purity: {line.get('JobWorkLine/Purity') or line.get('job work line/purity')}\n"
                            f"Quantity: {line.get('JobWorkLine/Quantity') or line.get('job work line/quantity')}\n"
                            f"Stone/Diamond Weight: {line.get('JobWorkLine/Stone/DiamondWeight(g)') or line.get('job work line/stone/diamond weight (g)')}\n"
                            f"Purchase Making Charge: {raw_mc}\n"
                            f"Net Weight: {line.get('JobWorkLine/NetWeight(g)') or line.get('job work line/net weight (g)')}\n"
                            f"No. of Pieces: {line.get('JobWorkLine/No.ofPieces') or line.get('job work line/no. of pieces')}\n"
                            f"Fine Weight: {line.get('JobWorkLine/FineWeight') or line.get('job work line/fine weight')}"
                        )
                        
                        purity_name = line.get('JobWorkLine/Purity') or line.get('job work line/purity')
                        qty = self.safe_float(line.get('JobWorkLine/Quantity') if line.get('JobWorkLine/Quantity') is not None else line.get('job work line/quantity'))
                        stone_wt = self.safe_float(line.get('JobWorkLine/Stone/DiamondWeight(g)') if line.get('JobWorkLine/Stone/DiamondWeight(g)') is not None else line.get('job work line/stone/diamond weight (g)'))
                        no_pcs = self.safe_int(line.get('JobWorkLine/No.ofPieces') if line.get('JobWorkLine/No.ofPieces') is not None else line.get('job work line/no. of pieces'), 1)
                        
                        purity = self.get_or_create_purity(purity_name)
                        
                        # Attributes
                        attrs = {
                            'TYPE': str(line.get('Type') or line.get('type') or '').strip().title(),
                            'VARIETY': str(line.get('Variety') or line.get('variety') or '').strip().title(),
                            'DESIGN': str(line.get('Design') or line.get('design') or '').strip().title(),
                            'SIZE': str(line.get('Size') or line.get('size') or '').strip().title(),
                            'STONE COLOUR': str(line.get('StoneColour') or line.get('stone colour') or '').strip().title(),
                            'METAL COLOUR': str(line.get('MetalColour') or line.get('metal colour') or '').strip().title(),
                        }
                        for k, v in attrs.items():
                            if v.upper() in ('FALSE', '', 'NONE', 'NAN'):
                                attrs[k] = 'None'
                                
                        current_attrs = attrs
                        
                        context_info = {'stage': "[3] Finding product template"}
                        try:
                            product = self._resolve_product(current_template, attrs, silver_company, context_info)
                            stage = context_info['stage']
                        except Exception as inner_e:
                            stage = context_info['stage']
                            raise inner_e
                            
                        if not product:
                            continue
                            
                        valid_line_specs.append({
                            'product': product,
                            'purity': purity,
                            'qty': qty,
                            'stone_wt': stone_wt,
                            'mc_val': mc_val,
                            'no_pcs': no_pcs,
                        })

                    if not valid_line_specs:
                        _logger.info(f"Skipping Job Work {jw_num} because no valid lines were created (Purchase Making Charge missing).")
                        continue

                    # Create Job Work in draft
                    stage = "[6] Creating Job Work"
                    job_work = self.env['jewellery.job.work'].create({
                        'name': jw_num,
                        'job_worker_id': worker.id,
                        'branch_id': silver_branch.id,
                        'company_id': silver_company.id,
                        'order_date': order_date,
                        'state': 'draft'
                    })
                    self.stats['jobs_created'] += 1

                    jw_lines_vals = []
                    for spec in valid_line_specs:
                        jw_lines_vals.append((0, 0, {
                            'job_work_id': job_work.id,
                            'product_id': spec['product'].id,
                            'product_template_id': spec['product'].product_tmpl_id.id,
                            'purity_id': spec['purity'].id if spec['purity'] else False,
                            'quantity': spec['qty'],
                            'net_weight': spec['qty'],
                            'stone_weight': spec['stone_wt'],
                            'purchase_making_charge_value': spec['mc_val'],
                            'no_of_pieces': spec['no_pcs'],
                        }))
                        self.stats['lines_created'] += 1

                    job_work.write({'job_work_line_ids': jw_lines_vals})
                    job_work.flush_recordset()

                    for jw_line in job_work.job_work_line_ids:
                        _logger.info(
                            f"Job Work Line ID: {jw_line.id}\n"
                            f"Purchase Making Charge Value: {jw_line.purchase_making_charge_value}"
                        )
                    
                    # --- 1. Create Issue Voucher ---
                    stage = "[8] Creating Issue Voucher"
                    issue_num = f"ISS-{job_work.name}"
                    
                    # DO NOT CREATE ISSUE VOUCHER LINES
                    # The user explicitly requested that the Issue Voucher contains NO product lines for this import flow.
                    
                    issue = self.env['jewellery.issue.voucher'].create({
                        'name': issue_num,
                        'job_work_id': job_work.id,
                        'job_worker_id': worker.id,
                        'branch_id': silver_branch.id,
                        'company_id': silver_company.id,
                        'source_location_id': stock_loc.id,
                        'received_location_id': subcon_loc.id,
                        'order_date': order_date,
                        'state': 'draft',
                    })
                    
                    _logger.info(f"""[ISSUE VOUCHER]
Job Work: {job_work.name}
Issue Voucher: {issue.name}
Product lines created: 0
Product creation skipped: True
State: Draft""")

                    self.stats['issues_created'] += 1
                    
                    # --- 2. Create Receive Voucher ---
                    stage = "[10] Creating Receive Voucher"
                    receive_num = f"REC-{job_work.name}"
                    
                    job_type_raw = str(first_line.get('ReceiveVoucher/JobTypeSelection') or first_line.get('receive voucher/job type selection') or '')
                    job_type_norm = self._normalize_excel_text(job_type_raw)
                    
                    job_type_val = False
                    selected_label = ""
                    if job_type_norm:
                        selection_values = self.env['jewellery.receive.voucher']._fields['job_type_selection'].selection
                        for key, label in selection_values:
                            if job_type_norm.lower() in label.lower() or label.lower() in job_type_norm.lower():
                                job_type_val = key
                                selected_label = label
                                break
                        if not job_type_val and job_type_norm.lower() == 'gold':
                            job_type_val = 'gold_only'
                            selected_label = 'Gold Only'
                            
                    _logger.info(f"Receive Voucher Excel Row: {current_row_idx}\nReceive Voucher/Job Type Selection raw value: {job_type_raw}\nNormalized Job Type: {job_type_norm}\nSelected Odoo Job Type: {selected_label or 'None'}\nSelected Job Type ID: {job_type_val or 'None'}")
                    
                    fine_rate_val = self.safe_float(first_line.get('ReceiveVoucher/FineRate(g)') or first_line.get('receive voucher/fine rate (g)'))
                    mc_type_raw = str(first_line.get('ReceiveVoucher/MCType') or first_line.get('receive voucher/mc type') or 'Percentage').strip().lower()
                    mc_type = 'percent'
                    if 'amount' in mc_type_raw:
                        mc_type = 'amount'
                    elif 'gram' in mc_type_raw:
                        mc_type = 'rate_per_gram'
                        
                    mc_pct_val = self.safe_float(first_line.get('ReceiveVoucher/MC%') or first_line.get('receive voucher/mc%'))
                    if not mc_pct_val and job_work.job_work_line_ids:
                        mc_pct_val = job_work.job_work_line_ids[0].purchase_making_charge_value
                    mc_amt_val = self.safe_float(first_line.get('ReceiveVoucher/MakingCharge') or first_line.get('receive voucher/making charge'))
                    rate_val = self.safe_float(first_line.get('ReceiveVoucher/Rate(g)') or first_line.get('receive voucher/rate(g)'))
                    wastage_val = self.safe_float(first_line.get('ReceiveVoucher/WastageWeight') or first_line.get('receive voucher/wastage weight'))
                    
                    receive_lines_vals = []
                    issue_lines_sorted = issue.line_ids.sorted('id')
                    
                    for idx, jw_line in enumerate(job_work.job_work_line_ids):
                        issue_line = issue_lines_sorted[idx] if idx < len(issue_lines_sorted) else False
                        receive_lines_vals.append((0, 0, {
                            'product_id': jw_line.product_id.id,
                            'product_template_id': jw_line.product_template_id.id,
                            'purity_id': jw_line.purity_id.id,
                            'qty': jw_line.quantity,
                            'gross_weight': jw_line.gross_weight,
                            'stone_weight': jw_line.stone_weight,
                            'uom_id': jw_line.unit_of_measure.id,
                            'fine_weight': jw_line.fine_weight,
                            'mc_fine': jw_line.mc_fine,
                            'purchase_making_charge_value': jw_line.purchase_making_charge_value,
                            'total_fine': jw_line.total_fine,
                            'issue_voucher_line_id': issue_line.id if issue_line else False,
                            'fine_gms_price': fine_rate_val,
                            'fine_issue_amount': jw_line.total_fine * fine_rate_val,
                        }))

                        _logger.info(
                            f"Excel Purchase Making Charge:\n{jw_line.purchase_making_charge_value}\n\n"
                            f"Job Work Line Purchase Making Charge:\n{jw_line.purchase_making_charge_value}\n\n"
                            f"Receive Voucher Order Line Purchase Making Charge:\n{jw_line.purchase_making_charge_value}"
                        )
                        _logger.info(f"""[MC% MAPPING]
Excel: {jw_line.purchase_making_charge_value}
Job Work Line: {jw_line.purchase_making_charge_value}
Receive Voucher Line: {jw_line.purchase_making_charge_value}""")
                        
                    receive = self.env['jewellery.receive.voucher'].search([('name', '=', receive_num)], limit=1)
                    if not receive:
                        receive = self.env['jewellery.receive.voucher'].create({
                            'name': receive_num,
                            'job_work_id': job_work.id,
                            'job_worker_id': worker.id,
                            'issue_voucher_id': issue.id,
                            'branch_id': silver_branch.id,
                            'company_id': silver_company.id,
                            'received_location_id': stock_loc.id,
                            'order_date': order_date,
                            'fine_rate': fine_rate_val,
                            'making_charge_type': mc_type,
                            'mc_percent': mc_pct_val,
                            'making_charge_value': mc_amt_val,
                            'rate_value': rate_val,
                            'wastage_weight': wastage_val,
                            'line_ids': receive_lines_vals,
                            'job_type_selection': job_type_val,
                            'state': 'draft'
                        })
                    
                    _logger.info(f"Source Location:\n{subcon_loc.name}\n\nDestination Location:\n{stock_loc.name}")
                    
                    if job_type_val == 'gold_only':
                        stage = "[Receive Voucher Validation]"
                        try:
                            # action_done() hardcodes stock.picking_type_internal which belongs to Company 1.
                            # We dynamically find the correct internal picking type for the company and mock env.ref to return it.
                            correct_picking_type = self.env['stock.picking.type'].search([
                                ('company_id', '=', silver_company.id),
                                ('code', '=', 'internal')
                            ], limit=1)
                            
                            receive_with_comp = receive.with_company(silver_company)
                            
                            # The user requested to replicate the Receive Voucher stock flow here to add specific logs and reservation checks.
                            # ADDING COMPANY CONTEXT VERIFICATION
                            
                            # Log and verify all related record companies match the Excel Company exactly.
                            _logger.info(
                                "[Receive Voucher Company Context]\n"
                                f"Excel Row:\n{current_row_idx}\n"
                                f"Excel Company:\n{silver_company.name}\n"
                                f"Company ID:\n{silver_company.id}\n"
                                f"Product:\n{current_template}\n"
                                f"Product Variant Company:\n{receive_with_comp.line_ids[:1].product_id.company_id.name if receive_with_comp.line_ids[:1].product_id.company_id else 'None'}\n"
                                f"Picking Company:\n{silver_company.name}\n"
                                f"Operation Type:\n{correct_picking_type.name}\n"
                                f"Operation Type Company:\n{correct_picking_type.company_id.name}\n"
                                f"Source Location:\n{receive_with_comp.source_location_id.name}\n"
                                f"Source Location Company:\n{receive_with_comp.source_location_id.company_id.name if receive_with_comp.source_location_id.company_id else 'None'}\n"
                                f"Destination Location:\n{receive_with_comp.received_location_id.name}\n"
                                f"Destination Location Company:\n{receive_with_comp.received_location_id.company_id.name if receive_with_comp.received_location_id.company_id else 'None'}\n"
                                f"Stock Move Company:\n{silver_company.name}"
                            )

                            if receive_with_comp.line_ids[:1].product_id.company_id and receive_with_comp.line_ids[:1].product_id.company_id != silver_company:
                                raise UserError(f"Company mismatch before Receive Voucher creation.\n\nExcel Company:\n{silver_company.name}\n\nProduct Company:\n{receive_with_comp.line_ids[:1].product_id.company_id.name}")
                            
                            if correct_picking_type.company_id != silver_company:
                                raise UserError(f"Company mismatch before Receive Voucher creation.\n\nExcel Company:\n{silver_company.name}\n\nOperation Type Company:\n{correct_picking_type.company_id.name}")
                                
                            if receive_with_comp.received_location_id.company_id and receive_with_comp.received_location_id.company_id != silver_company:
                                raise UserError(f"Company mismatch before Receive Voucher creation.\n\nExcel Company:\n{silver_company.name}\n\nDestination Location Company:\n{receive_with_comp.received_location_id.company_id.name}")

                            picking = receive_with_comp.picking_id
                            created_moves = self.env['stock.move']
                            if not picking:
                                picking = self.env['stock.picking'].with_company(silver_company).create({
                                    'company_id': silver_company.id,
                                    'picking_type_id': correct_picking_type.id,
                                    'location_id': receive_with_comp.source_location_id.id,
                                    'location_dest_id': receive_with_comp.received_location_id.id,
                                    'origin': receive_with_comp.name,
                                    'is_old_gold': True,
                                })
                                receive_with_comp.picking_id = picking.id
                                
                                uom_gram = self.env.ref('uom.product_uom_gram')
                                for line in receive_with_comp.line_ids:
                                    price_unit = (line.total_receive_fine_amount / line.gross_weight) if line.gross_weight else 0.0
                                    move = self.env['stock.move'].with_company(silver_company).create({
                                        'company_id': silver_company.id,
                                        'product_id': line.product_id.id,
                                        'product_uom_qty': line.gross_weight,
                                        'name': line.product_id.name,
                                        'product_uom': uom_gram.id,
                                        'location_id': picking.location_id.id,
                                        'location_dest_id': picking.location_dest_id.id,
                                        'picking_id': picking.id,
                                        'purity_id': line.purity_id.id,
                                        'price_unit': price_unit,
                                        'receive_voucher_line_id': line.id,
                                    })
                                    created_moves |= move
                            else:
                                created_moves = picking.move_ids

                            if picking.state not in ['done', 'cancel']:
                                picking.action_confirm()

                            # If negative initial demand exists, Odoo's _action_confirm converts it to a return move
                            # and reassigns it to another picking. We collect all active pickings linked to the created moves.
                            active_pickings = created_moves.mapped('picking_id').filtered(lambda p: p.state not in ('done', 'cancel'))
                            if not active_pickings:
                                active_pickings = picking.filtered(lambda p: p.state not in ('done', 'cancel'))

                            for current_picking in active_pickings:
                                for move in current_picking.move_ids:
                                    _logger.info(f"""========================================
RECEIVE VOUCHER STOCK FLOW
========================================
Job Work: {current_jw}
Receive Voucher: {receive_with_comp.name}
Partner: {worker.name}
Company: {silver_company.name}
Source Location: {move.location_id.display_name}
Destination Location: {move.location_dest_id.display_name}
Operation Type: {correct_picking_type.name}
Product: {move.product_id.display_name}
Quantity: {move.product_uom_qty}
Reserved Quantity: {move.quantity}
Done Quantity: 0.0
Picking State: {current_picking.state}
========================================""")

                                if current_picking.state not in ['done', 'cancel']:
                                    reservable_moves = current_picking.move_ids.filtered(lambda m: m.state not in ('draft', 'cancel', 'done'))
                                    if reservable_moves:
                                        try:
                                            current_picking.action_assign()
                                        except UserError as ue:
                                            if 'Nothing to check the availability for' not in str(ue):
                                                raise
                                        
                                # Odoo 17: Set done quantity on the move and mark as picked
                                for move in current_picking.move_ids:
                                    move.quantity = move.product_uom_qty
                                    move.picked = True
                                    
                                    _logger.info(f"""[PARTNER RECEIPT VALIDATION]
Picking: {current_picking.name}
Product: {move.product_id.display_name}
Source: {move.location_id.display_name}
Destination: {move.location_dest_id.display_name}
Required Quantity: {move.product_uom_qty}
Reserved Quantity: 0.0
Done Quantity: {move.quantity}
Picking Type: {correct_picking_type.name}""")

                                try:
                                    current_picking.with_context(skip_backorder=True).button_validate()
                                except Exception as receive_e:
                                    move = current_picking.move_ids[:1]
                                    error_msg = (
                                        f"Failed to validate Receive Voucher stock.\n\n"
                                        f"Partner:\n{worker.name}\n\n"
                                        f"Source Location:\n{move.location_id.display_name if move else current_picking.location_id.display_name}\n\n"
                                        f"Destination Location:\n{move.location_dest_id.display_name if move else current_picking.location_dest_id.display_name}\n\n"
                                        f"Product:\n{move.product_id.display_name if move else 'Unknown'}\n\n"
                                        f"Required Quantity:\n{move.product_uom_qty if move else 0.0}\n\n"
                                        f"Reserved Quantity:\n0.0\n\n"
                                        f"Done Quantity:\n{move.quantity if move else 0.0}\n\n"
                                        f"Picking Type:\n{correct_picking_type.name}\n\n"
                                        f"Picking:\n{current_picking.name}\n\n"
                                        f"Actual Odoo Error:\n{str(receive_e)}"
                                    )
                                    self.env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', error_msg)
                                    raise UserError(error_msg)

                            primary_picking = (created_moves.mapped('picking_id') or picking)[:1]
                            receive_with_comp.picking_id = primary_picking.id
                            receive_with_comp.state = 'done'
                            if receive_with_comp.job_work_id:
                                receive_with_comp.job_work_id.state = 'received'

                            if order_date and primary_picking:
                                formatted_date = order_date.strftime('%Y-%m-%d 12:00:00')
                                try:
                                    primary_picking.flush_recordset()
                                    primary_picking.move_ids.flush_recordset()
                                    primary_picking.move_line_ids.flush_recordset()

                                    self.env.cr.execute(
                                        "UPDATE stock_picking SET scheduled_date=%s, date_done=%s, date=%s WHERE id=%s",
                                        (formatted_date, formatted_date, formatted_date, primary_picking.id)
                                    )
                                    self.env.cr.execute(
                                        "UPDATE stock_move SET date=%s, date_deadline=%s WHERE picking_id=%s",
                                        (formatted_date, formatted_date, primary_picking.id)
                                    )
                                    self.env.cr.execute(
                                        "UPDATE stock_move_line SET date=%s WHERE picking_id=%s",
                                        (formatted_date, primary_picking.id)
                                    )

                                    primary_picking.invalidate_recordset()
                                    primary_picking.move_ids.invalidate_recordset()
                                    primary_picking.move_line_ids.invalidate_recordset()
                                except Exception as date_e:
                                    _logger.warning(f"Could not apply excel date {formatted_date} to receive voucher picking {primary_picking.name}: {date_e}")
                                
                        except UserError:
                            raise
                        except Exception as receive_e:
                            raise UserError(f"Receive Voucher could not be validated because {str(receive_e)}")
                            
                    self.stats['receives_created'] += 1
                    job_work.state = 'received'
                    
                    count += 1
                    if count % 10 == 0:
                        self.env['ir.config_parameter'].sudo().set_param(
                            f'import_progress_{task_id}', 
                            f"Processed {count} of {total_jws} Job Works..."
                        )
                        
            except Exception as e:
                _logger.exception(f"Job Work import failed. File=excel_file, Row={current_row_idx}")
                self.env.cr.rollback()
                
                attr_str = ""
                if current_attrs:
                    attr_str = f"Type = {current_attrs.get('TYPE', 'None')}\nVariety = {current_attrs.get('VARIETY', 'None')}\nDesign = {current_attrs.get('DESIGN', 'None')}\nSize = {current_attrs.get('SIZE', 'None')}\nStone Colour = {current_attrs.get('STONE COLOUR', 'None')}\nMetal Colour = {current_attrs.get('METAL COLOUR', 'None')}"
                
                business_error = (
                    f"Job Work import failed at Excel row {current_row_idx}.\n\n"
                    f"Job Work: {current_jw}\n"
                    f"Product Template: {current_template}\n\n"
                    f"Attributes:\n{attr_str}\n\n"
                    f"Stage:\n{stage}\n\n"
                    f"Error:\n{str(e)}"
                )
                self.env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', business_error)
                raise UserError(business_error)
                    
            self.env.cr.commit()
            _logger.info("Jewellery Job Work Bulk Import Completed Successfully!")
            self.env['ir.config_parameter'].sudo().set_param(
                f'import_stats_{task_id}', 
                f"Jobs: {self.stats['jobs_created']}, Lines: {self.stats['lines_created']}, Issues: {self.stats['issues_created']}, Receipts: {self.stats['receives_created']}"
            )
            
        except Exception as e:
            _logger.error(f"Error during Job Work import: {str(e)}", exc_info=True)
            self.env.cr.rollback()
            self.env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', str(e))
            raise e
