import openpyxl  
import logging
import os
from odoo import http
from odoo.http import request
from odoo.modules.module import get_module_resource

_logger = logging.getLogger(__name__)

class JewelryImportController(http.Controller):

    @http.route('/import/products/now', type='http', auth='user')
    def trigger_import(self, **kwargs):
        # Increase variant limit
        request.env['ir.config_parameter'].sudo().set_param('product.dynamic_variant_limit', 20000)
        
        file_name = 'PRODUCT TEMPLATE FINAL.xlsx'
        file_path = get_module_resource('custom_product_import', 'data', file_name)
        
        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found.</p>"

        try:
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            sheet = workbook.active
            
            h_map = {str(sheet.cell(row=1, column=i).value).strip(): i 
                     for i in range(1, sheet.max_column + 1) 
                     if sheet.cell(row=1, column=i).value}

            grouped_products = {}
            last_valid_name = False 

            # --- STEP 1: GROUPING ---
            for row_idx in range(2, sheet.max_row + 1):
                def get_v(col_name):
                    idx = h_map.get(col_name)
                    return sheet.cell(row=row_idx, column=idx).value if idx else False

                row_name = get_v('Name')
                if row_name:
                    last_valid_name = str(row_name).strip()

                if not last_valid_name:
                    continue

                if last_valid_name not in grouped_products:
                    def is_yes(val):
                        return str(val).lower() in ['yes', '1', '1.0', 'true', '1.00']

                    grouped_products[last_valid_name] = {
                        'info': {
                            'name': last_valid_name,
                            'standard_price': float(get_v('Cost') or 0.0),
                            'uom_id': request.env['uom.uom'].search([('name', '=', get_v('Unit of Measure'))], limit=1).id or request.env.ref('uom.product_uom_unit').id,
                            'company_id': request.env['res.company'].search([('name', '=', get_v('Company'))], limit=1).id or request.env.company.id,
                            'purity_id': request.env['gold.purity'].search([('name', '=', str(get_v('Purity')).strip())], limit=1).id if get_v('Purity') else False,
                            'sale_ok': is_yes(get_v('Can be Sold')),
                            'purchase_ok': is_yes(get_v('Can be Purchased')),
                            'type': 'product',
                        },
                        'attributes': {}
                    }
                
                attr_name = str(get_v('Product Attributes/Attribute')).strip() if get_v('Product Attributes/Attribute') else False
                attr_values = get_v('Product Attributes/Values')

                if attr_name and attr_values:
                    val_list = [v.strip() for v in str(attr_values).split(',')]
                    if attr_name in grouped_products[last_valid_name]['attributes']:
                        grouped_products[last_valid_name]['attributes'][attr_name].extend(val_list)
                    else:
                        grouped_products[last_valid_name]['attributes'][attr_name] = val_list

            # --- STEP 2: CREATION WITH DUPLICATION CHECK ---
            count = 0
            for p_name, p_data in grouped_products.items():
                # CHECK IF PRODUCT ALREADY EXISTS
                product = request.env['product.template'].search([('name', '=', p_name)], limit=1)
                
                if not product:
                    product = request.env['product.template'].create(p_data['info'])
                    _logger.info(f"Created new product: {p_name}")
                else:
                    _logger.info(f"Product {p_name} already exists, skipping creation.")
                    # Optionally update the product info here if you want: product.write(p_data['info'])
                
                # --- STEP 3: ATTRIBUTES ---
                for a_name, a_vals in p_data['attributes'].items():
                    attribute = request.env['product.attribute'].search([('name', '=', a_name)], limit=1)
                    if not attribute:
                        attribute = request.env['product.attribute'].create({'name': a_name, 'create_variant': 'no_variant'})

                    # Deduplicate values
                    value_ids = []
                    for val_name in set(a_vals): 
                        v_rec = request.env['product.attribute.value'].search([
                            ('name', '=', val_name), ('attribute_id', '=', attribute.id)], limit=1)
                        if not v_rec:
                            v_rec = request.env['product.attribute.value'].create({'name': val_name, 'attribute_id': attribute.id})
                        value_ids.append(v_rec.id)

                    if value_ids:
                        # Check if this attribute line already exists for this product
                        existing_line = request.env['product.template.attribute.line'].search([
                            ('product_tmpl_id', '=', product.id),
                            ('attribute_id', '=', attribute.id)
                        ], limit=1)
                        
                        if not existing_line:
                            try:
                                request.env['product.template.attribute.line'].create({
                                    'product_tmpl_id': product.id,
                                    'attribute_id': attribute.id,
                                    'value_ids': [(6, 0, value_ids)]
                                })
                            except Exception as attr_err:
                                _logger.warning(f"Attribute line skip: {str(attr_err)}")
                
                count += 1

            request.env.cr.commit()
            return f"<h1>Import Finished</h1><p>Processed {count} unique products from Excel.</p>"

        except Exception as e:
            _logger.error(f"Import Failed: {str(e)}")
            return f"<h1>Error</h1><p>{str(e)}</p>"
