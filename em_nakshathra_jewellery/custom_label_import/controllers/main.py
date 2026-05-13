import openpyxl
import logging
import os
from odoo import http, fields
from odoo.http import request
from odoo.modules.module import get_module_resource

_logger = logging.getLogger(__name__)

class LabelPurchaseImportController(http.Controller):

    @http.route('/import/labels_purchase/now', type='http', auth='user')
    def trigger_import(self, **kwargs):
        # Path to the specific Excel file
        file_name = 'PRODUCT LABEL FINAL OP STOCK.xlsx'
        file_path = get_module_resource('custom_label_import', 'data', file_name)
        
        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"

        try:
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            sheet = workbook.active
            
            # Map headers to column indices
            h_map = {str(sheet.cell(row=1, column=i).value).strip(): i 
                     for i in range(1, sheet.max_column + 1) 
                     if sheet.cell(row=1, column=i).value}

            po_tracker = {}
            count = 0
            skipped = 0

            for row_idx in range(2, sheet.max_row + 1):
                def get_v(col_name):
                    idx = h_map.get(col_name)
                    return sheet.cell(row=row_idx, column=idx).value if idx else False

                barcode = str(get_v('Barcode')).strip() if get_v('Barcode') else False
                supplier_name = str(get_v('Supplier Name')).strip() if get_v('Supplier Name') else False
                
                if not barcode:
                    continue
                
                # --- 1. Identify Variant Exactly ---
                variant_name_excel = str(get_v('Product/Product') or '').strip()
                template_name_excel = str(get_v('Product/Product Template') or '').strip()

                # A. Find the specific Template first
                template = request.env['product.template'].search([('name', '=', template_name_excel)], limit=1)

                variant_rec = False
                if template:
                    # B. Filter the variants of THIS template specifically
                    # We loop through variants to ensure the display_name is a 100% string match
                    for v in template.product_variant_ids:
                        if v.display_name.strip() == variant_name_excel:
                            variant_rec = v
                            break
                            
                    # C. Backup: If direct loop fails, try a strict search with template ID
                    if not variant_rec:
                        variant_rec = request.env['product.product'].search([
                            ('product_tmpl_id', '=', template.id),
                            ('display_name', '=', variant_name_excel)
                        ], limit=1)

                if not variant_rec:
                    _logger.error(f"FAIL: Could not distinguish variant '{variant_name_excel}' for template '{template_name_excel}'")
                    continue

                # Avoid duplicate imports based on Barcode
                if request.env['product.label'].search([('barcode', '=', barcode)], limit=1):
                    skipped += 1
                    continue

                # --- 1. Handle Supplier & Purchase Order ---
                current_po_id = False
                if supplier_name:
                    if supplier_name not in po_tracker:
                        partner = request.env['res.partner'].search([('name', '=', supplier_name)], limit=1)
                        if not partner:
                            partner = request.env['res.partner'].create({
                                'name': supplier_name,
                                'company_type': 'company',
                                'supplier_rank': 1,
                            })
                        
                        new_po = request.env['purchase.order'].create({
                            'partner_id': partner.id,
                            'date_order': fields.Datetime.now(),
                            'origin': 'Bulk Label Import',
                        })
                        po_tracker[supplier_name] = (new_po.id, partner.id)
                    
                    current_po_id, partner_id = po_tracker.get(supplier_name)

             
                # --- 3. Prepare Mapping ---
                raw_type = str(get_v('Purchase Making Charge Type')).strip()
                mc_type_mapping = {
                    'Percentage': 'percent', 
                    'Amount': 'amount', 
                    'Rate per Gram': 'rate_per_gram'
                }
                making_charge_key = mc_type_mapping.get(raw_type, 'percent')

                vals = {
                    'name': get_v('Label Name'),
                    'age': get_v('Age (Days)'),
                    'product_template_id': variant_rec.product_tmpl_id.id,
                    'product_id': variant_rec.id,
                    'branch_id': self._find_m2o('res.branch', get_v('Branch')), 
                    'branch_location_id': self._find_m2o('stock.location', get_v('Branch Location')),
                    'tag_weight': get_v('Tag Weight (g)'),
                    'purity_id': self._find_m2o('gold.purity', get_v('Purity')),
                    'barcode': barcode,
                    'purchase_id': current_po_id,
                    'diamond_certificate': get_v('Diamond Certificate'),
                    'purchase_diamond_weight_gm': get_v('Diamond Weight (g)'),
                    'purchase_gross_weight': get_v('Purchase Gross Amount (g)'),
                    'purchase_stone_weight': get_v('Purchase Stone Weight (g)'),
                    'purchase_diamond_weight_ct': get_v('Diamond Weight (ct)'),
                    'purchase_net_weight': get_v('Purchase Net Weight (g)'),
                    'purchase_making_charge_type': making_charge_key,
                    'purchase_making_charge_value': get_v('Purchase Making Charge'),
                    'mc_fine': get_v('MC Fine'),
                    'purchase_making_charge_amount': get_v('Purchase Making Charge Amount'),
                    'purchase_metal_rate': get_v('Purchase Metal Amount'),
                    'purchase_stone_rate': get_v('Purchase Stone Amount'),
                    'purchase_diamond_rate': get_v('Purchase Diamond Amount'),
                    'sale_gross_weight': get_v('Sale Gross Weight (g)'),
                    'sale_making_charge_value': get_v('Sale Making Charge Max'),
                    'sale_making_charge_min': get_v('Sale Making Charge Min'),
                    'sale_diamond_rate': get_v('Sale Diamond Amount'),
                    'sale_stone_rate': get_v('Sale Stone Amount'),
                    'active': True if str(get_v('Active')).lower() in ['true', '1', 'yes'] else False,
                    'purchase_price_per_gram': get_v('Purchase fine Rate / gram'),
                }

                try:
                    request.env['product.label'].create(vals)
                    # Create PO line if variant is found and PO is active
                    if current_po_id and vals.get('product_id'):
                        self._create_po_line(current_po_id, vals)
                    count += 1
                except Exception as row_err:
                    _logger.error(f"Failed at row {row_idx}: {str(row_err)}")
                    request.env.cr.rollback()

            request.env.cr.commit()
            return f"<h1>Import Finished</h1><p>Created: {count} | POs Created: {len(po_tracker)} | Skipped: {skipped}</p>"

        except Exception as e:
            _logger.error(f"Critical Import Failure: {str(e)}")
            return f"<h1>Error</h1><p>{str(e)}</p>"

    def _find_m2o(self, model, name):
        if not name: return False
        record = request.env[model].search([('name', '=', str(name).strip())], limit=1)
        return record.id if record else False

    def _create_po_line(self, po_id, vals):
        """ Creates a Purchase Order Line linked to the newly imported label. """
        product = request.env['product.product'].browse(vals['product_id'])
        request.env['purchase.order.line'].create({
            'order_id': po_id,
            'product_template_id': vals['product_template_id'],
            'product_id': vals['product_id'],
            'name': f"Label: {vals['barcode']} - {vals['name'] or product.name}",
            'product_qty': 1.0,
            'price_unit': float(vals.get('purchase_gross_weight') or 0.0),
            'date_planned': fields.Datetime.now(),
            'product_uom': product.uom_id.id,
        })

