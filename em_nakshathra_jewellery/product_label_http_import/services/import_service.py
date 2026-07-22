import base64
import io
import logging
from openpyxl import load_workbook
from odoo.exceptions import UserError
from datetime import datetime

_logger = logging.getLogger(__name__)

class ProductLabelImportService:
    def __init__(self, env):
        self.env = env.sudo()

    def process_import(self, file_base64):
        _logger.info("Starting Product Label Bulk Import via Python Script...")
        file_content = base64.b64decode(file_base64)
        wb = load_workbook(io.BytesIO(file_content), data_only=True)
        sheet = wb.active
        
        # Extract headers and handle duplicates (e.g. Diamond Weight (g) appears twice)
        raw_headers = [str(cell.value).strip() if cell.value else f"Col_{idx}" for idx, cell in enumerate(sheet[1])]
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
        
        # Set up a batch counter to commit periodically if needed
        for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not any(row):
                continue
                
            row_dict = dict(zip(headers, row))
            
            try:
                with self.env.cr.savepoint():
                    _logger.info(f"Processing row {row_idx}...")
                    label = self._process_row(row_dict, row_idx)
                    created += 1
                    _logger.info(f"Row {row_idx} imported successfully as Label {label.name}.")
            except Exception as e:
                _logger.error(f"Error on row {row_idx}: {e}")
                
        self.env.cr.commit()
        
        # Run Transfers (auto-stock in)
        labels = self.env['product.label'].search([('is_stocked_in', '=', False), ('picking_id', '=', False)])
        for label in labels:
            try:
                with self.env.cr.savepoint():
                    label.sudo().action_stock_in()
                    transferred += 1
            except Exception as e:
                _logger.warning(f"Failed to auto-transfer label {label.name}: {e}")
                
        self.env.cr.commit()
                
        return {'created': created, 'transferred': transferred}

    def _process_row(self, row, row_idx):
        # Helper to get row value case-insensitively
        def get_val(key_name):
            for k in row.keys():
                if str(k).strip().lower() == key_name.lower():
                    return row[k]
            return None

        # 1. Product Template & Variant matching
        product_name = str(get_val('Product') or '').strip()
        if not product_name:
            raise UserError(f"Product column is missing on row {row_idx}.")
            
        variant = self._resolve_product_variant(row, product_name, get_val)
        
        # 2. Find Branch
        branch_name = str(get_val('Branch') or '').strip()
        branch = False
        if branch_name:
            branch = self.env['res.branch'].search([('name', '=ilike', branch_name)], limit=1)
            if not branch:
                branch = self.env['res.branch'].create({'name': branch_name})
                
        # 3. Find Source Location
        src_loc_name = str(get_val('Source Location') or '').strip()
        src_loc = False
        if src_loc_name:
            src_loc = self.env['stock.location'].search(['|', ('complete_name', '=ilike', src_loc_name), ('name', '=ilike', src_loc_name)], limit=1)
            if not src_loc:
                src_loc = self.env['stock.location'].create({'name': src_loc_name, 'usage': 'internal'})
                
        # 4. Find Destination Location
        dest_loc_name = str(get_val('Destination Location') or '').strip()
        dest_loc = False
        if dest_loc_name:
            dest_loc = self.env['stock.location'].search(['|', ('complete_name', '=ilike', dest_loc_name), ('name', '=ilike', dest_loc_name)], limit=1)
            if not dest_loc:
                dest_loc = self.env['stock.location'].create({
                    'name': dest_loc_name,
                    'usage': 'internal',
                    'branch_id': branch.id if branch else False
                })
                
        # 5. Find Purchase Order
        po_name = str(get_val('Choose Purchase Order') or get_val('Purchase Order') or '').strip()
        po = False
        if po_name:
            po = self.env['purchase.order'].search([('name', '=ilike', po_name)], limit=1)
            
        # Purity
        purity_name = str(get_val('Purity') or '').strip()
        purity = False
        if purity_name:
            purity = self.env['gold.purity'].search([('name', '=ilike', purity_name)], limit=1)
            if not purity:
                purity = self.env['gold.purity'].create({'name': purity_name})

        # Making charge type mapping
        sale_mc_type_raw = str(get_val('Sale Making Charge Type') or '').strip().lower()
        sale_mc_type = self._map_mc_type(sale_mc_type_raw)
            
        purch_mc_type_raw = str(get_val('Purchase Making Charge Type') or '').strip().lower()
        purch_mc_type = self._map_mc_type(purch_mc_type_raw)

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
        
        vals = {
            'label_name': label_name,
            'name': label_name or 'New',
            'product_id': variant.id,
            'product_tmpl_id': variant.product_tmpl_id.id,
            'branch_id': branch.id if branch else False,
            'source_location_id': src_loc.id if src_loc else False,
            'branch_location_id': dest_loc.id if dest_loc else False,
            'purchase_id': po.id if po else False,
            
            'barcode': str(get_val('Barcode') or '').strip() or False,
            'age_import': int(get_float('Age (Days)')),
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
            'purchase_making_charge_value': get_float('Purchase Making Charge'),
            
            'purchase_stone_rate': get_float('Purchase Stone Amount'),
            'purchase_diamond_rate': get_float('Purchase Diamond Amount'),
            
            'active': True,
        }
            
        label = self.env['product.label'].create(vals)
        
        # Force product_tmpl_id via write to ensure it doesn't get cleared by any internal onchange
        if variant.product_tmpl_id:
            label.write({'product_tmpl_id': variant.product_tmpl_id.id})
            
        return label

    def _map_mc_type(self, raw_val):
        if 'percent' in raw_val or '%' in raw_val:
            return 'percent'
        elif 'amount' in raw_val:
            return 'amount'
        elif 'rate' in raw_val:
            return 'rate_per_gram'
        return 'percent'

    def _resolve_product_variant(self, row, product_name, get_val_func):
        _logger.info(f"Finding Product Template: {product_name}")
        template = self.env['product.template'].search([('name', '=ilike', product_name)], limit=1)
        if not template:
            raise UserError(f"Product Template '{product_name}' not found. Please ensure it is created before importing.")
            
        _logger.info(f"Found existing Product Template: {template.name}")

        attrs = {
            'TYPE': str(get_val_func('TYPE') or '').strip().title(),
            'VARIETY': str(get_val_func('VARIETY') or '').strip().title(),
            'DESIGN': str(get_val_func('DESIGN') or '').strip().title(),
            'SIZE': str(get_val_func('SIZE') or '').strip().title(),
            'STONE COLOUR': str(get_val_func('STONE COLOUR') or '').strip().title(),
            'METAL COLOUR': str(get_val_func('METAL COLOUR') or '').strip().title(),
        }

        ptav_ids = []
        for attr_name, attr_val in attrs.items():
            if not attr_val or attr_val.upper() in ('NONE', 'FALSE', ''):
                attr_val = 'None'
                
            attribute = self.env['product.attribute'].search([('name', '=ilike', attr_name)], limit=1)
            if not attribute:
                raise UserError(f"Product Attribute '{attr_name}' not found. Please ensure it exists.")
                
            value = self.env['product.attribute.value'].search([('attribute_id', '=', attribute.id), ('name', '=ilike', attr_val)], limit=1)
            if not value:
                raise UserError(f"Product Attribute Value '{attr_val}' for '{attr_name}' not found.")
                
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
            raise UserError(f"Exact Product Variant for '{template.name}' with attributes {attrs} not found.")
            
        _logger.info(f"Found exact variant {exact_variant.id} for {template.name}")
            
        return exact_variant
