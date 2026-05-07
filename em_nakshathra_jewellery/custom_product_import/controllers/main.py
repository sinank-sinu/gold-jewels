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

# import openpyxl  
# import logging
# import os
# from odoo import http
# from odoo.http import request
# from odoo.modules.module import get_module_resource

# _logger = logging.getLogger(__name__)

# class JewelryImportController(http.Controller):

#     @http.route('/import/products/now', type='http', auth='user')
#     def trigger_import(self, **kwargs):
#         file_name = 'PRODUCT TEMPLATE FINAL.xlsx'
#         file_path = get_module_resource('custom_product_import', 'data', file_name)
        
#         if not file_path or not os.path.exists(file_path):
#             return f"<h1>Error</h1><p>File '{file_name}' not found.</p>"

#         try:
#             workbook = openpyxl.load_workbook(file_path, data_only=True)
#             sheet = workbook.active
            
#             # 1. Map Headers
#             h_map = {str(sheet.cell(row=1, column=i).value).strip(): i 
#                      for i in range(1, sheet.max_column + 1) 
#                      if sheet.cell(row=1, column=i).value}

#             grouped_products = {}
#             last_valid_name = False  # This remembers the product name for the blank rows

#             # 2. First Pass: Group all rows belonging to the same product
#             for row_idx in range(2, sheet.max_row + 1):
#                 def get_v(col_name):
#                     idx = h_map.get(col_name)
#                     return sheet.cell(row=row_idx, column=idx).value if idx else False

#                 row_name = get_v('Name')
                
#                 # If this row has a name, update our "last_valid_name"
#                 if row_name:
#                     last_valid_name = str(row_name).strip()

#                 # If we have no name on this row AND no previous name to use, skip it
#                 if not last_valid_name:
#                     continue

#                 # Initialize the product group if we haven't seen this name yet
#                 if last_valid_name not in grouped_products:
#                     grouped_products[last_valid_name] = {
#                         'info': {
#                             'name': last_valid_name,
#                             'standard_price': float(get_v('Cost') or 0.0),
#                             'uom_id': request.env['uom.uom'].search([('name', '=', get_v('Unit of Measure'))], limit=1).id or request.env.ref('uom.product_uom_unit').id,
#                             'company_id': request.env['res.company'].search([('name', '=', get_v('Company'))], limit=1).id or request.env.company.id,
#                             'branch_id': request.env['res.branch'].search([('name', '=', get_v('Branch'))], limit=1).id,
#                             'purity_id': request.env['gold.purity'].search([('name', '=', str(get_v('Purity')).strip())], limit=1).id if get_v('Purity') else False,
#                             'sale_ok': str(get_v('Can be Sold')).lower() == 'yes',
#                             'purchase_ok': str(get_v('Can be Purchased')).lower() == 'yes',
#                             'type': 'product',
#                         },
#                         'attributes': {}
#                     }
                
#                 # Collect Attribute details from the current row
#                 attr_name = str(get_v('Product Attributes/Attribute')).strip() if get_v('Product Attributes/Attribute') else False
#                 attr_values = get_v('Product Attributes/Values')

#                 if attr_name and attr_values:
#                     val_list = [v.strip() for v in str(attr_values).split(',')]
#                     if attr_name in grouped_products[last_valid_name]['attributes']:
#                         grouped_products[last_valid_name]['attributes'][attr_name].extend(val_list)
#                     else:
#                         grouped_products[last_valid_name]['attributes'][attr_name] = val_list

#             # 3. Second Pass: Create the products in Odoo
#             count = 0
#             for p_name, p_data in grouped_products.items():
#                 # Create Template
#                 product = request.env['product.template'].create(p_data['info'])
                
#                 # Create Attribute Lines (Loops through Size, Color, etc.)
#                 for a_name, a_vals in p_data['attributes'].items():
#                     attribute = request.env['product.attribute'].search([('name', '=', a_name)], limit=1)
#                     if not attribute:
#                         attribute = request.env['product.attribute'].create({
#                             'name': a_name,
#                             'create_variant': 'dynamic'
#                             })

#                     value_ids = []
#                     for val_name in set(a_vals): # set() removes duplicates
#                         v_rec = request.env['product.attribute.value'].search([
#                             ('name', '=', val_name), ('attribute_id', '=', attribute.id)], limit=1)
#                         if not v_rec:
#                             v_rec = request.env['product.attribute.value'].create({
#                                 'name': val_name, 'attribute_id': attribute.id})
#                         value_ids.append(v_rec.id)

#                     if value_ids:
#                         request.env['product.template.attribute.line'].create({
#                             'product_tmpl_id': product.id,
#                             'attribute_id': attribute.id,
#                             'value_ids': [(6, 0, value_ids)]
#                         })
#                 count += 1

#             request.env.cr.commit()
#             return f"<h1>Success</h1><p>Processed {count} products. 'Bangle xx' should now have both Size and Color.</p>"

#         except Exception as e:
#             _logger.error(f"Import Failed: {str(e)}")
#             return f"<h1>Error</h1><p>{str(e)}</p>"



# import openpyxl
# import logging
# import os

# from odoo import http
# from odoo.http import request
# from odoo.modules.module import get_module_resource

# _logger = logging.getLogger(__name__)


# class JewelryImportController(http.Controller):

#     @http.route('/import/products/now', type='http', auth='user')
#     def trigger_import(self, **kwargs):

#         file_name = 'PRODUCT TEMPLATE FINAL.xlsx'

#         file_path = get_module_resource(
#             'custom_product_import',
#             'data',
#             file_name
#         )

#         if not file_path or not os.path.exists(file_path):
#             return f"<h1>Error</h1><p>File '{file_name}' not found.</p>"

#         try:

#             workbook = openpyxl.load_workbook(
#                 file_path,
#                 data_only=True
#             )

#             sheet = workbook.active

#             env = request.env(context=dict(

#                 request.env.context,

#                 tracking_disable=True,
#                 mail_create_nolog=True,
#                 mail_create_nosubscribe=True,
#                 mail_notrack=True,
#                 no_reset_password=True,

#             ))

#             # =====================================================
#             # HEADER MAP
#             # =====================================================

#             h_map = {
#                 str(sheet.cell(row=1, column=i).value).strip(): i
#                 for i in range(1, sheet.max_column + 1)
#                 if sheet.cell(row=1, column=i).value
#             }

#             # =====================================================
#             # CACHE MAPS
#             # =====================================================

#             uom_cache = {
#                 rec.name.strip().lower(): rec.id
#                 for rec in env['uom.uom'].search([])
#             }

#             company_cache = {
#                 rec.name.strip().lower(): rec.id
#                 for rec in env['res.company'].search([])
#             }

#             branch_cache = {
#                 rec.name.strip().lower(): rec.id
#                 for rec in env['res.branch'].search([])
#             }

#             purity_cache = {
#                 rec.name.strip().lower(): rec.id
#                 for rec in env['gold.purity'].search([])
#             }

#             attribute_cache = {
#                 rec.name.strip().lower(): rec.id
#                 for rec in env['product.attribute'].search([])
#             }

#             value_cache = {
#                 (rec.attribute_id.id, rec.name.strip().lower()): rec.id
#                 for rec in env['product.attribute.value'].search([])
#             }

#             # =====================================================
#             # GROUP PRODUCTS
#             # =====================================================

#             grouped_products = {}

#             last_valid_name = False

#             for row_idx in range(2, sheet.max_row + 1):

#                 def get_v(col_name):
#                     idx = h_map.get(col_name)
#                     return (
#                         sheet.cell(row=row_idx, column=idx).value
#                         if idx else False
#                     )

#                 row_name = get_v('Name')

#                 if row_name:
#                     last_valid_name = str(row_name).strip()

#                 if not last_valid_name:
#                     continue

#                 # =================================================
#                 # CREATE PRODUCT GROUP
#                 # =================================================

#                 if last_valid_name not in grouped_products:

#                     uom_name = str(
#                         get_v('Unit of Measure') or ''
#                     ).strip().lower()

#                     company_name = str(
#                         get_v('Company') or ''
#                     ).strip().lower()

#                     branch_name = str(
#                         get_v('Branch') or ''
#                     ).strip().lower()

#                     purity_name = str(
#                         get_v('Purity') or ''
#                     ).strip().lower()

#                     grouped_products[last_valid_name] = {

#                         'info': {

#                             'name': last_valid_name,

#                             'standard_price': float(
#                                 get_v('Cost') or 0.0
#                             ),

#                             'uom_id': (
#                                 uom_cache.get(uom_name)
#                                 or env.ref(
#                                     'uom.product_uom_unit'
#                                 ).id
#                             ),

#                             'uom_po_id': (
#                                 uom_cache.get(uom_name)
#                                 or env.ref(
#                                     'uom.product_uom_unit'
#                                 ).id
#                             ),

#                             'company_id': (
#                                 company_cache.get(company_name)
#                                 or env.company.id
#                             ),

#                             'branch_id': branch_cache.get(
#                                 branch_name
#                             ),

#                             'purity_id': purity_cache.get(
#                                 purity_name
#                             ),

#                             'sale_ok': str(
#                                 get_v('Can be Sold')
#                             ).strip().lower() == 'yes',

#                             'purchase_ok': str(
#                                 get_v('Can be Purchased')
#                             ).strip().lower() == 'yes',

#                             'type': 'product',
#                         },

#                         'attributes': {}
#                     }

#                 # =================================================
#                 # ATTRIBUTE COLLECTION
#                 # =================================================

#                 attr_name = get_v('Product Attributes/Attribute')

#                 attr_values = get_v('Product Attributes/Values')

#                 if attr_name and attr_values:

#                     attr_name = str(attr_name).strip()

#                     val_list = [
#                         v.strip()
#                         for v in str(attr_values).split(',')
#                         if v.strip()
#                     ]

#                     if attr_name not in grouped_products[
#                         last_valid_name
#                     ]['attributes']:

#                         grouped_products[
#                             last_valid_name
#                         ]['attributes'][attr_name] = []

#                     grouped_products[
#                         last_valid_name
#                     ]['attributes'][attr_name].extend(
#                         val_list
#                     )

#             # =====================================================
#             # CREATE PRODUCTS
#             # =====================================================

#             count = 0

#             BATCH_SIZE = 20

#             for p_name, p_data in grouped_products.items():

#                 try:

#                     with env.cr.savepoint():

#                         # =========================================
#                         # SKIP IF EXISTS
#                         # =========================================

#                         existing_product = env[
#                             'product.template'
#                         ].search([
#                             ('name', '=', p_name)
#                         ], limit=1)

#                         if existing_product:
#                             continue

#                         # =========================================
#                         # BUILD ATTRIBUTE LINES FIRST
#                         # =========================================

#                         attribute_lines = []

#                         for a_name, a_vals in p_data[
#                             'attributes'
#                         ].items():

#                             a_key = a_name.strip().lower()

#                             # =====================================
#                             # ATTRIBUTE
#                             # =====================================
#                             attribute_id = attribute_cache.get(a_key)

#                             attribute = env['product.attribute'].browse(attribute_id)
#                             # attribute = attribute_cache.get(
#                             #     a_key
#                             # )

#                             if not attribute:

#                                 attribute = env[
#                                     'product.attribute'
#                                 ].create({
#                                     'name': a_name,
#                                 })

#                                 attribute_cache[a_key] = attribute

#                             # =====================================
#                             # VALUES
#                             # =====================================

#                             value_ids = []

#                             for val_name in set(a_vals):

#                                 if not val_name:
#                                     continue

#                                 val_name = str(
#                                     val_name
#                                 ).strip()

#                                 if val_name.lower() == 'none':
#                                     continue

#                                 cache_key = (
#                                     attribute.id,
#                                     val_name.lower()
#                                 )

#                                 # value = value_cache.get(
#                                 #     cache_key
#                                 # )
#                                 value_id = value_cache.get(cache_key)
#                                 value = env['product.attribute.value'].browse(value_id)

#                                 if not value:

#                                     value = env[
#                                         'product.attribute.value'
#                                     ].create({
#                                         'name': val_name,
#                                         'attribute_id': attribute.id
#                                     })

#                                     value_cache[
#                                         cache_key
#                                     ] = value

#                                 value_ids.append(value.id)

#                             # =====================================
#                             # ATTRIBUTE LINE
#                             # =====================================

#                             if value_ids:

#                                 attribute_lines.append((
#                                     0,
#                                     0,
#                                     {
#                                         'attribute_id': attribute.id,
#                                         'value_ids': [
#                                             (
#                                                 6,
#                                                 0,
#                                                 value_ids
#                                             )
#                                         ]
#                                     }
#                                 ))

#                         # =========================================
#                         # FINAL PRODUCT CREATE
#                         # =========================================

#                         product_vals = p_data['info']

#                         product_vals.update({
#                             'attribute_line_ids': attribute_lines
#                         })

#                         env['product.template'].create(
#                             product_vals
#                         )

#                         count += 1

#                         # =========================================
#                         # BATCH COMMIT
#                         # =========================================

#                         if count % BATCH_SIZE == 0:

#                             env.cr.commit()

#                             env.clear()

#                             _logger.info(
#                                 f'Committed {count} products'
#                             )

#                 except Exception as e:

#                     _logger.error(
#                         f'ERROR IN PRODUCT {p_name}: {str(e)}'
#                     )

#             env.cr.commit()

#             return f"""
#                 <h1>SUCCESS</h1>
#                 <p>
#                     Imported {count} products successfully.
#                 </p>
#             """

#         except Exception as e:

#             _logger.error(f"IMPORT FAILED: {str(e)}")

#             return f"""
#                 <h1>ERROR</h1>
#                 <p>{str(e)}</p>
#             """
