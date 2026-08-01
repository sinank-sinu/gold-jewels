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
            return float(val)
        except (ValueError, TypeError):
            return default

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

    def _get_or_create_template_only(self, template_name, current_company, uom_gram):
        template_cache_key = (current_company.id, template_name.lower())
        if template_cache_key in self.template_cache:
            return self.template_cache[template_cache_key]
            
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
            template = TemplateModel.create({
                'name': template_name,
                'type': 'product',
                'uom_id': uom_gram.id,
                'uom_po_id': uom_gram.id,
                'company_id': current_company.id,
            })
            _logger.info(f"Created missing product template: '{template_name}'")
            
        self.template_cache[template_cache_key] = template
        return template

    def _resolve_product(self, raw_name, attrs, current_company, uom_gram):
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
            return self.variant_cache[cache_key]
            
        template_cache_key = (current_company.id, template_name.lower())
        template = self.template_cache.get(template_cache_key)
        if not template:
            template = self._get_or_create_template_only(template_name, current_company, uom_gram)
            
        ptav_ids = []
        for attr_name, attr_val in attrs.items():
            if not attr_val or attr_val == 'None':
                continue
                
            attribute = self.env['product.attribute'].search([('name', '=ilike', attr_name)], limit=1)
            if not attribute:
                continue
                
            value = self.env['product.attribute.value'].search([
                ('attribute_id', '=', attribute.id),
                ('name', '=ilike', attr_val)
            ], limit=1)
            if not value:
                continue
                
            ptal = template.attribute_line_ids.filtered(lambda l: l.attribute_id.id == attribute.id)
            ptav = self.env['product.template.attribute.value'].search([
                ('attribute_line_id', '=', ptal.id),
                ('product_attribute_value_id', '=', value.id)
            ], limit=1)
            if ptav:
                ptav_ids.append(ptav.id)
                
        exact_variant = None
        for variant in template.product_variant_ids:
            if variant.company_id and variant.company_id.id != current_company.id:
                continue
            variant_ptav_ids = set(variant.product_template_attribute_value_ids.ids)
            if variant_ptav_ids == set(ptav_ids):
                exact_variant = variant
                break
                
        if not exact_variant:
            exact_variant = self.env['product.product'].create({
                'product_tmpl_id': template.id,
                'product_template_attribute_value_ids': [(6, 0, ptav_ids)],
            })
            _logger.info(f"Created product variant under '{template_name}'")
            
        self.variant_cache[cache_key] = exact_variant
        return exact_variant

    def process_import(self, file_base64, task_id):
        _logger.info("Starting Jewellery Job Work Bulk Import...")
        try:
            file_content = base64.b64decode(file_base64)
            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
            sheet = wb.active
            
            # Headers are on row 2 (1-indexed row 2)
            raw_headers = [str(cell.value).strip() if cell.value else '' for cell in sheet[2]]
            
            # Clean and normalize header names (remove all whitespace/spaces)
            headers = [re.sub(r'\s+', '', h) for h in raw_headers]
            _logger.info(f"Normalized Headers: {headers}")
            
            # Check required columns
            required_cols = ['JobWorkNumber', 'JobWorker', 'Company', 'JobWorkLine/Quantity', 'JobWorkLine/ProductTemplate']
            missing = [r for r in required_cols if r not in headers]
            if missing:
                error_msg = f"Excel file is missing required columns: {', '.join(missing)}"
                self.env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', error_msg)
                raise UserError(error_msg)
                
            # Align rows with headers
            grouped_data = defaultdict(list)
            
            for row_idx, row in enumerate(sheet.iter_rows(min_row=3, values_only=True), start=3):
                if not row[0] and not any(row):
                    continue
                row_dict = dict(zip(headers, row))
                jw_num = str(row_dict.get('JobWorkNumber') or '').strip()
                if not jw_num or jw_num.endswith('Total'):
                    continue
                grouped_data[jw_num].append(row_dict)
                
            _logger.info(f"Found {len(grouped_data)} unique Job Work Numbers in Excel.")
            
            # 1. PRE-FLIGHT VALIDATION: Check Odoo database for any duplicate Job Work Numbers
            all_jw_numbers = list(grouped_data.keys())
            existing_jws = self.env['jewellery.job.work'].search([('name', 'in', all_jw_numbers)])
            if existing_jws:
                duplicate_names = [jw.name for jw in existing_jws]
                error_msg = f"DUPLICATION ERROR: The following Job Work numbers already exist in Odoo: {', '.join(duplicate_names)}. Import aborted."
                self.env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', error_msg)
                raise UserError(error_msg)
                
            # 2. Map target company (Silver LLP)
            silver_company = self.env['res.company'].search([('name', '=', 'NAKSHATHRA 916 GOLD AND DIAMONDS SILVER LLP')], limit=1)
            if not silver_company:
                raise UserError("Silver Company 'NAKSHATHRA 916 GOLD AND DIAMONDS SILVER LLP' not found in database.")
                
            silver_branch = self.env['res.branch'].search([('name', '=', 'HEAD OFFICE'), ('company_id', '=', silver_company.id)], limit=1)
            if not silver_branch:
                silver_branch = self.env['res.branch'].search([('company_id', '=', silver_company.id)], limit=1)
                
            silver_warehouse = self.env['stock.warehouse'].search([('company_id', '=', silver_company.id)], limit=1)
            if not silver_warehouse:
                raise UserError(f"No warehouse found for company {silver_company.name}")
                
            stock_loc = silver_warehouse.lot_stock_id
            subcon_loc = self.env['stock.location'].search([
                ('name', '=', 'Subcontracting Location'),
                ('company_id', '=', silver_company.id)
            ], limit=1)
            if not subcon_loc:
                subcon_loc = self.env.ref('stock.stock_location_suppliers')
                
            uom_gram = self.env.ref('uom.product_uom_gram')
            
            # Phase 1: Pre-process templates and their attributes to avoid Odoo unlinking variants during loops
            self.env['ir.config_parameter'].sudo().set_param(f'import_progress_{task_id}', 'Pre-processing product templates and attributes...')
            template_attributes = defaultdict(lambda: defaultdict(set))
            for jw_num, lines in grouped_data.items():
                for line in lines:
                    raw_prod = line.get('JobWorkLine/ProductTemplate')
                    template_name = re.sub(r'\s+', ' ', str(raw_prod or '')).strip()
                    if not template_name:
                        continue
                    attrs = {
                        'TYPE': str(line.get('Type') or '').strip().title(),
                        'VARIETY': str(line.get('Variety') or '').strip().title(),
                        'DESIGN': str(line.get('Design') or '').strip().title(),
                        'SIZE': str(line.get('Size') or '').strip().title(),
                        'STONE COLOUR': str(line.get('StoneColour') or '').strip().title(),
                        'METAL COLOUR': str(line.get('MetalColour') or '').strip().title(),
                    }
                    for k, v in attrs.items():
                        if v.upper() not in ('FALSE', '', 'NONE', 'NAN'):
                            template_attributes[template_name][k].add(v)
                            
            for template_name, attr_dict in template_attributes.items():
                template = self._get_or_create_template_only(template_name, silver_company, uom_gram)
                for attr_name, val_set in attr_dict.items():
                    if not val_set:
                        continue
                    attribute = self.env['product.attribute'].search([('name', '=ilike', attr_name)], limit=1)
                    if not attribute:
                        attribute = self.env['product.attribute'].create({'name': attr_name})
                        
                    value_ids = []
                    for val_name in val_set:
                        value = self.env['product.attribute.value'].search([
                            ('attribute_id', '=', attribute.id),
                            ('name', '=ilike', val_name)
                        ], limit=1)
                        if not value:
                            value = self.env['product.attribute.value'].create({
                                'attribute_id': attribute.id,
                                'name': val_name
                            })
                        value_ids.append(value.id)
                        
                    ptal = template.attribute_line_ids.filtered(lambda l: l.attribute_id.id == attribute.id)
                    if not ptal:
                        self.env['product.template.attribute.line'].create({
                            'product_tmpl_id': template.id,
                            'attribute_id': attribute.id,
                            'value_ids': [(6, 0, value_ids)]
                        })
                    else:
                        new_ids = list(set(ptal.value_ids.ids + value_ids))
                        ptal.write({'value_ids': [(6, 0, new_ids)]})
                template.flush_recordset()
                
            # Ensure Silver Bullion exists and pre-stocked
            silver_bullion = self.env['product.product'].search([('name', '=', 'Silver Bullion')], limit=1)
            if not silver_bullion:
                silver_tmpl = self.env['product.template'].create({
                    'name': 'Silver Bullion',
                    'type': 'product',
                    'uom_id': uom_gram.id,
                    'uom_po_id': uom_gram.id,
                    'purchase_ok': True,
                    'company_id': False,
                })
                silver_bullion = silver_tmpl.product_variant_id
                
            # Pre-stock opening balance (1,000,000g)
            Quant = self.env['stock.quant'].sudo()
            quant = Quant.search([('product_id', '=', silver_bullion.id), ('location_id', '=', stock_loc.id)], limit=1)
            if quant:
                quant.quantity = max(quant.quantity, 1000000.0)
            else:
                Quant.create({
                    'product_id': silver_bullion.id,
                    'location_id': stock_loc.id,
                    'quantity': 1000000.0
                })
                
            # Phase 2: Process Job Works
            total_jws = len(grouped_data)
            count = 0
            
            for jw_num, lines in grouped_data.items():
                first_line = lines[0]
                
                # Resolve Worker
                raw_worker = first_line.get('JobWorker')
                worker = self.get_or_create_partner(raw_worker, silver_company)
                if not worker:
                    raise UserError(f"Worker '{raw_worker}' could not be resolved for Job Work {jw_num}.")
                    
                order_date = self.safe_date(first_line.get('OrderDate'))
                
                # Create Job Work in draft
                job_work = self.env['jewellery.job.work'].create({
                    'name': jw_num,
                    'job_worker_id': worker.id,
                    'branch_id': silver_branch.id,
                    'company_id': silver_company.id,
                    'order_date': order_date,
                    'state': 'draft'
                })
                self.stats['jobs_created'] += 1
                
                # Create lines
                total_net = 0.0
                jw_lines_vals = []
                
                for line in lines:
                    raw_prod = line.get('JobWorkLine/ProductTemplate')
                    purity_name = line.get('JobWorkLine/Purity')
                    qty = self.safe_float(line.get('JobWorkLine/Quantity'))
                    stone_wt = self.safe_float(line.get('JobWorkLine/Stone/DiamondWeight(g)'))
                    mc_val = self.safe_float(line.get('ReceiveVoucher/MC%') or line.get('ReceiveVoucher/MCFine'))
                    no_pcs = self.safe_int(line.get('JobWorkLine/No.ofPieces'), 1)
                    
                    purity = self.get_or_create_purity(purity_name)
                    
                    # Attributes
                    attrs = {
                        'TYPE': str(line.get('Type') or '').strip().title(),
                        'VARIETY': str(line.get('Variety') or '').strip().title(),
                        'DESIGN': str(line.get('Design') or '').strip().title(),
                        'SIZE': str(line.get('Size') or '').strip().title(),
                        'STONE COLOUR': str(line.get('StoneColour') or '').strip().title(),
                        'METAL COLOUR': str(line.get('MetalColour') or '').strip().title(),
                    }
                    for k, v in attrs.items():
                        if v.upper() in ('FALSE', '', 'NONE', 'NAN'):
                            attrs[k] = 'None'
                            
                    product = self._resolve_product(raw_prod, attrs, silver_company, uom_gram)
                    if not product:
                        continue
                        
                    jw_lines_vals.append((0, 0, {
                        'job_work_id': job_work.id,
                        'product_id': product.id,
                        'product_template_id': product.product_tmpl_id.id,
                        'purity_id': purity.id if purity else False,
                        'quantity': qty,
                        'net_weight': qty,
                        'stone_weight': stone_wt,
                        'purchase_making_charge_value': mc_val,
                        'no_of_pieces': no_pcs,
                    }))
                    total_net += qty
                    self.stats['lines_created'] += 1
                    
                job_work.write({'job_work_line_ids': jw_lines_vals})
                job_work.flush_recordset()
                total_fine = job_work.total_fine_weight
                
                # --- 1. Create Issue Voucher ---
                issue_num = f"ISS-{job_work.name}"
                
                # Pre-create internal stock picking with correct company context
                picking_type = self.env['stock.picking.type'].search([
                    ('code', '=', 'internal'),
                    ('company_id', '=', silver_company.id)
                ], limit=1)
                
                picking = self.env['stock.picking'].create({
                    'picking_type_id': picking_type.id if picking_type else self.env.ref('stock.picking_type_internal').id,
                    'location_id': stock_loc.id,
                    'location_dest_id': subcon_loc.id,
                    'origin': issue_num,
                    'is_old_gold': True,
                    'company_id': silver_company.id,
                })
                
                move = self.env['stock.move'].create({
                    'product_id': silver_bullion.id,
                    'product_uom_qty': total_net,
                    'name': silver_bullion.name,
                    'product_uom': uom_gram.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'picking_id': picking.id,
                    'purity_id': self.env['gold.purity'].search([('percentage', '>=', 99.0)], limit=1).id,
                    'company_id': silver_company.id,
                })
                
                picking.action_confirm()
                picking.action_assign()
                
                if not move.move_line_ids:
                    self.env['stock.move.line'].create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'quantity': move.product_uom_qty,
                        'company_id': move.company_id.id,
                    })
                else:
                    for ml in move.move_line_ids:
                        ml.quantity = move.product_uom_qty
                        
                picking.with_context(skip_backorder=True).button_validate()
                
                issue = self.env['jewellery.issue.voucher'].create({
                    'name': issue_num,
                    'job_work_id': job_work.id,
                    'job_worker_id': worker.id,
                    'branch_id': silver_branch.id,
                    'company_id': silver_company.id,
                    'source_location_id': stock_loc.id,
                    'received_location_id': subcon_loc.id,
                    'order_date': order_date,
                    'picking_id': picking.id,
                    'state': 'draft'
                })
                
                self.env['jewellery.issue.voucher.line'].create({
                    'voucher_id': issue.id,
                    'product_id': silver_bullion.id,
                    'purity_id': self.env['gold.purity'].search([('percentage', '>=', 99.0)], limit=1).id,
                    'qty': total_net,
                    'fine_weight': total_fine,
                    'gross_weight': total_net,
                })
                self.stats['issues_created'] += 1
                
                # Confirm issue (bypasses picking generation because self.picking_id is already done!)
                issue.action_done()
                # --- 2. Create Receive Voucher ---
                receive_num = f"REC-{job_work.name}"
                fine_rate_val = self.safe_float(first_line.get('ReceiveVoucher/FineRate(g)'))
                mc_type_raw = str(first_line.get('ReceiveVoucher/MCType') or 'Percentage').strip().lower()
                mc_type = 'percent'
                if 'amount' in mc_type_raw:
                    mc_type = 'amount'
                elif 'gram' in mc_type_raw:
                    mc_type = 'rate_per_gram'
                    
                mc_pct_val = self.safe_float(first_line.get('ReceiveVoucher/MC%'))
                mc_amt_val = self.safe_float(first_line.get('ReceiveVoucher/MakingCharge'))
                rate_val = self.safe_float(first_line.get('ReceiveVoucher/Rate(g)'))
                wastage_val = self.safe_float(first_line.get('ReceiveVoucher/WastageWeight'))
                
                rec_picking = self.env['stock.picking'].create({
                    'picking_type_id': picking_type.id if picking_type else self.env.ref('stock.picking_type_internal').id,
                    'location_id': subcon_loc.id,
                    'location_dest_id': stock_loc.id,
                    'origin': receive_num,
                    'is_old_gold': True,
                    'company_id': silver_company.id,
                })
                
                receive_lines_vals = []
                issue_line = issue.line_ids[0] if issue.line_ids else False
                
                for jw_line in job_work.job_work_line_ids:
                    price_unit = (jw_line.fine_weight * fine_rate_val / jw_line.gross_weight) if jw_line.gross_weight else 0.0
                    
                    rec_move = self.env['stock.move'].create({
                        'product_id': jw_line.product_id.id,
                        'product_uom_qty': jw_line.gross_weight,
                        'name': jw_line.product_id.name,
                        'product_uom': jw_line.unit_of_measure.id,
                        'location_id': rec_picking.location_id.id,
                        'location_dest_id': rec_picking.location_dest_id.id,
                        'picking_id': rec_picking.id,
                        'purity_id': jw_line.purity_id.id,
                        'price_unit': price_unit,
                        'company_id': silver_company.id,
                    })
                    
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
                    
                rec_picking.action_confirm()
                rec_picking.action_assign()
                
                for m in rec_picking.move_ids:
                    if not m.move_line_ids:
                        self.env['stock.move.line'].create({
                            'picking_id': rec_picking.id,
                            'move_id': m.id,
                            'product_id': m.product_id.id,
                            'product_uom_id': m.product_uom.id,
                            'location_id': m.location_id.id,
                            'location_dest_id': m.location_dest_id.id,
                            'quantity': m.product_uom_qty,
                            'company_id': m.company_id.id,
                        })
                    else:
                        for ml in m.move_line_ids:
                            ml.quantity = m.product_uom_qty
                            
                rec_picking.with_context(skip_backorder=True).button_validate()
                
                receive = self.env['jewellery.receive.voucher'].create({
                    'name': receive_num,
                    'job_work_id': job_work.id,
                    'job_worker_id': worker.id,
                    'issue_voucher_id': issue.id,
                    'branch_id': silver_branch.id,
                    'company_id': silver_company.id,
                    'source_location_id': subcon_loc.id,
                    'received_location_id': stock_loc.id,
                    'order_date': order_date,
                    'fine_rate': fine_rate_val,
                    'making_charge_type': mc_type,
                    'mc_percent': mc_pct_val,
                    'making_charge_value': mc_amt_val,
                    'rate_value': rate_val,
                    'wastage_weight': wastage_val,
                    'line_ids': receive_lines_vals,
                    'picking_id': rec_picking.id,
                    'state': 'draft'
                })
                self.stats['receives_created'] += 1
                
                for r_line, r_move in zip(receive.line_ids, rec_picking.move_ids):
                    r_move.write({'receive_voucher_line_id': r_line.id})
                    
                # Confirm receive (bypasses picking generation because self.picking_id is already done!)
                receive.action_done()
                
                # Vendor Bill
                if receive.making_charge_amount > 0.0:
                    receive.action_create_making_charge_bill()
                    self.stats['bills_created'] += 1
                    
                # Move Job Work to done
                job_work.action_done()
                
                count += 1
                if count % 10 == 0:
                    self.env.cr.commit()
                    self.env['ir.config_parameter'].sudo().set_param(
                        f'import_progress_{task_id}', 
                        f"Processed {count} of {total_jws} Job Works..."
                    )
                    
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
