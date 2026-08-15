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
        self.job_work_cache = {}

    def process_import(self, file_base64):
        self.job_work_cache = {}
        created = 0
        transferred = 0
        failed_labels = []
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
                        if not label:
                            _logger.info("Row %s skipped.", row_idx)
                            continue
                        
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
                            
                        # Create and force validate the transfer for the label stock directly in the script
                        if label.source_location_id and label.branch_location_id:
                            picking_type = self.env['stock.picking.type'].search([
                                ('code', '=', 'internal'),
                                ('company_id', '=', label.branch_id.company_id.id)
                            ], limit=1) or self.env.ref('stock.picking_type_internal')
                            
                            picking = self.env['stock.picking'].create({
                                'picking_type_id': picking_type.id,
                                'location_id': label.source_location_id.id,
                                'location_dest_id': label.branch_location_id.id,
                                'origin': label.name,
                                'branch_id': label.branch_id.id,
                            })

                            self.env['stock.move'].create({
                                'name': f"Stock In: {label.name}",
                                'product_id': label.product_id.id,
                                'product_uom_qty': label.purchase_gross_weight or 1.0,
                                'product_uom': label.product_id.uom_id.id,
                                'location_id': label.source_location_id.id,
                                'location_dest_id': label.branch_location_id.id,
                                'picking_id': picking.id,
                                'label_id': label.id,
                                'purity_id': label.purity_id.id if label.purity_id else False,
                                'branch_id': label.branch_id.id,
                            })

                            picking.action_confirm()
                            picking.action_assign()
                            for move in picking.move_ids_without_package:
                                move.quantity = move.product_uom_qty
                                move.picked = True
                            
                            # Force completion without checking UI wizards
                            picking._action_done()

                            label.write({
                                'picking_id': picking.id,
                                'is_stocked_in': True,
                            })

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
                        # Total product.label records currently in the database

                except Exception as e:
                        label_name = row_dict.get("Label Name") or row_dict.get("label name") or ""
                        failed_labels.append({
                            "row": row_idx,
                            "label": str(label_name).strip(),
                            "reason": str(e),
                        })
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
            total_labels = self.env['product.label'].search_count([])

            _logger.info("=" * 100)
            _logger.info("PRODUCT LABEL IMPORT COMPLETED")
            _logger.info("Rows Imported Successfully : %s", created)
            _logger.info("Labels Transferred         : %s", transferred)
            _logger.info("Total product.label Records: %s", total_labels)
            _logger.info("Failed Records             : %s", len(failed_labels))

            if failed_labels:
                _logger.info("---------- NON CREATED LABELS ----------")
                for rec in failed_labels:
                    _logger.info(
                        "Row: %s | Label: %s | Reason: %s",
                        rec["row"],
                        rec["label"],
                        rec["reason"],
                    )
                _logger.info("-------- END NON CREATED LABELS --------")

            _logger.info("=" * 100)

        return {
                "created": created,
                "transferred": transferred,
                "total_product_labels": total_labels,
                "failed": len(failed_labels),
            }
                
        # return {'created': created, 'transferred': transferred}

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
            
        variant = self._resolve_product_variant(row, product_name, get_val, excel_company)
        if variant.company_id and variant.company_id.id != excel_company.id:
            raise UserError(f"Product Variant {variant.name} belongs to company {variant.company_id.name}, but Excel row specifies {excel_company.name}.")
        
        # 2. Find Branch
        branch_name = str(get_val('Branch') or '').strip()
        branch = False
        if branch_name:
            branch = self.env['res.branch'].search([
                ('name', '=ilike', branch_name),
            ], limit=1)

            # if branch:
            #     if not branch.company_id:
            #         branch.company_id = excel_company.id
            #     elif branch.company_id != excel_company:
            #         _logger.warning(
            #             "Branch '%s' belongs to company '%s', using existing branch.",
            #             branch.name,
            #             branch.company_id.name,
            #         )
            # else:
            #     branch = self.env['res.branch'].create({
            #         'name': branch_name,
            #         'company_id': excel_company.id,
            #     })
            if not branch:
                _logger.warning(
                                "Branch '%s' not found",
                                branch_name
                            )
                # branch = self.env['res.branch'].create({'name': branch_name, 'company_id': excel_company.id})
                
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
        if not label_name:
            _logger.warning(
                "Row %s skipped because 'Label Name' is empty in the Excel.",
                row_idx,
            )
            return False
        
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

        # Job Work lookup
        raw_jw = (
            get_val('Job Work Number') or 
            get_val('Job Work No') or 
            get_val('Job Work') or 
            get_val('JobWorkNumber') or 
            get_val('job_work_number')
        )
        job_work = self._resolve_job_work(raw_jw, excel_company, row_idx, normalized_barcode or raw_barcode)

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
            'job_work_id': job_work.id if job_work else False,
            
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
        _logger.info(f"Row {row_idx}: Final Product Label created with purchase_making_charge_value = {label.purchase_making_charge_value}, purchase_making_charge_amount = {label.purchase_making_charge_amount}, job_work_id = {label.job_work_id.id if label.job_work_id else False}")
        
        # Force product_tmpl_id via write to ensure it doesn't get cleared by any internal onchange
        write_vals = {}
        if variant.product_tmpl_id:
            write_vals['product_tmpl_id'] = variant.product_tmpl_id.id
            write_vals['product_id'] = variant.id
            
        if job_work:
            write_vals['job_work_id'] = job_work.id

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

    def _normalize_job_work_number(self, val):
        if val is None or val is False:
            return None
        if isinstance(val, float):
            if val.is_integer():
                val = str(int(val))
            else:
                val = str(val)
        elif isinstance(val, int):
            val = str(val)
        else:
            val = str(val)

        val = val.strip()
        if val.endswith('.0') and val[:-2].isdigit():
            val = val[:-2]

        if not val or val.lower() in ('none', 'null', 'nan', 'false', ''):
            return None
        return val

    def _resolve_job_work(self, raw_jw, excel_company, row_idx, barcode):
        norm_jw = self._normalize_job_work_number(raw_jw)
        if not norm_jw:
            _logger.info(f"Row {row_idx} | Job Work Number: EMPTY")
            return False

        cache_key = (excel_company.id, norm_jw)
        if cache_key in self.job_work_cache:
            job_work = self.job_work_cache[cache_key]
            _logger.info(f"Row {row_idx} | Job Work Number: {norm_jw} | Job Work ID: {job_work.id} (from cache)")
            return job_work

        # Search by reference name in jewellery.job.work
        job_work = self.env['jewellery.job.work'].search([
            ('name', '=ilike', norm_jw),
            ('company_id', 'in', [excel_company.id, False])
        ], limit=1)

        if not job_work:
            job_work = self.env['jewellery.job.work'].search([
                ('name', '=ilike', norm_jw)
            ], limit=1)

        if job_work:
            self.job_work_cache[cache_key] = job_work
            _logger.info(f"Row {row_idx} | Job Work Number: {norm_jw} | Job Work ID: {job_work.id}")
            return job_work
        else:
            _logger.warning(f"Row {row_idx} | Job Work Number: {norm_jw} | Job Work not found")
            _logger.warning(f"Job Work not found: {norm_jw} | Row: {row_idx} | Barcode: {barcode}")
            raise UserError(f"Job Work not found: {norm_jw} | Row: {row_idx} | Barcode: {barcode}")

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

        ptav_ids = []
        for attr_name, attr_val in attrs.items():
            attribute = self.env['product.attribute'].search([('name', '=ilike', attr_name)], limit=1)
            if not attribute:
                raise UserError(f"Product Attribute '{attr_name}' not found. Please ensure it exists.")

            if attr_val is None:
                value = self.env["product.attribute.value"].search([
                    ("attribute_id", "=", attribute.id),
                    ("name", "=", False),
                ], limit=1)
            else:
                import re

                def normalize_attr(val):
                    val = str(val or "").strip().lower()

                    # Normalize spaces
                    val = re.sub(r"\s+", " ", val)

                    # Ignore spaces around hyphens
                    val = re.sub(r"\s*-\s*", "-", val)

                    # Normalize quotes
                    val = val.replace("“", '"').replace("”", '"')
                    val = re.sub(r'\s*"\s*', '"', val)

                    return val

                values = self.env["product.attribute.value"].search([
                    ("attribute_id", "=", attribute.id),
                ])

                value = values.filtered(
                    lambda v: normalize_attr(v.name) == normalize_attr(attr_val)
                )[:1]

            if not value:
                raise UserError(
                    f"Product Attribute Value '{attr_val}' for '{attr_name}' not found."
                )
                
            ptal = template.attribute_line_ids.filtered(lambda l: l.attribute_id.id == attribute.id)
            if not ptal:
                raise UserError(f"Attribute '{attr_name}' is not assigned to Product Template '{template.name}'.")
                
            ptav = self.env['product.template.attribute.value'].search([
                ('attribute_line_id', '=', ptal.id),
                ('product_attribute_value_id', '=', value.id)
            ], limit=1)
            if ptav:
                ptav_ids.append(ptav.id)
            else:
                raise UserError(f"Value '{attr_val}' for Attribute '{attr_name}' is not configured on Product Template '{template.name}'.")
                
        # Resolve Variant EXACT MATCH
        exact_variant = False
        target_ptav_set = set(ptav_ids)
        for variant in template.product_variant_ids:
            if set(variant.product_template_attribute_value_ids.ids) == target_ptav_set:
                exact_variant = variant
                break
                
        if not exact_variant:
            error_msg = f"Product Variant not found for template '{template.name}' with exactly these attributes: {attrs}. Please ensure the variant is created before importing."
            _logger.error(error_msg)
            raise UserError(error_msg)
            
        return exact_variant

ProductJobWorkLabelImportService = ProductLabelImportService

