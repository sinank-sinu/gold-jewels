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

        file_name = 'PRODUCT TEMPLATE FINAL.xlsx'
        file_path = get_module_resource(
            'custom_product_import',
            'data',
            file_name
        )

        if not file_path or not os.path.exists(file_path):
<<<<<<< HEAD
            return f"<h1>Error</h1><p>File not found.</p>"
=======
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"
<<<<<<< HEAD
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            
<<<<<<< HEAD
=======
            # Map headers to column indices
>>>>>>> bi_binsha_nakshathra_changes
            h_map = {str(sheet.cell(row=1, column=i).value).strip(): i 
                     for i in range(1, sheet.max_column + 1) 
                     if sheet.cell(row=1, column=i).value}
=======

        try:
            workbook = openpyxl.load_workbook(
                file_path,
                data_only=True
            )

            sheet = workbook.active

            # ---------------------------------------------------
            # HEADER MAP
            # ---------------------------------------------------

            h_map = {
                str(sheet.cell(row=1, column=i).value).strip(): i
                for i in range(1, sheet.max_column + 1)
                if sheet.cell(row=1, column=i).value
            }
>>>>>>> bi_binsha_nakshathra_changes

            grouped_products = {}
            last_valid_name = False

            # ---------------------------------------------------
            # HELPERS
            # ---------------------------------------------------

            def get_cell(row_idx, col_name):
                idx = h_map.get(col_name)
                return sheet.cell(row=row_idx, column=idx).value if idx else False

            def is_yes(val):
                return str(val).strip().lower() in [
                    'yes', '1', '1.0', 'true'
                ]

            # ---------------------------------------------------
            # STEP 1 : GROUP EXCEL DATA
            # ---------------------------------------------------

<<<<<<< HEAD
<<<<<<< HEAD
            # --- STEP 1: GROUPING ---
=======
            # --- STEP 1: DATA GROUPING ---
>>>>>>> bi_binsha_nakshathra_changes
=======
>>>>>>> bi_binsha_nakshathra_changes
            for row_idx in range(2, sheet.max_row + 1):

                row_name = get_cell(row_idx, 'Name')

                if row_name:
                    last_valid_name = str(row_name).strip()

                if not last_valid_name:
                    continue

                # -------------------------------------------
                # CREATE GROUP
                # -------------------------------------------

                if last_valid_name not in grouped_products:

                    uom_name = get_cell(row_idx, 'Unit of Measure')
                    company_name = get_cell(row_idx, 'Company')
                    purity_name = get_cell(row_idx, 'Purity')

                    uom = request.env['uom.uom'].search([
                        ('name', '=', str(uom_name).strip())
                    ], limit=1)

                    company = request.env['res.company'].search([
                        ('name', '=', str(company_name).strip())
                    ], limit=1)

                    purity = False

                    if purity_name:
                        purity = request.env['gold.purity'].search([
                            ('name', 'ilike', str(purity_name).strip())
                        ], limit=1)

                    grouped_products[last_valid_name] = {
                        'info': {
                            'name': last_valid_name,
                            'standard_price': float(
                                get_cell(row_idx, 'Cost') or 0.0
                            ),
                            'uom_id': uom.id or request.env.ref(
                                'uom.product_uom_unit'
                            ).id,
                            'company_id': company.id or request.env.company.id,
                            'purity_id': purity.id if purity else False,
                            'sale_ok': is_yes(
                                get_cell(row_idx, 'Can be Sold')
                            ),
                            'purchase_ok': is_yes(
                                get_cell(row_idx, 'Can be Purchased')
                            ),
                            'type': 'product',
                        },
                        'attributes': {}
                    }

                # -------------------------------------------
                # ATTRIBUTE DATA
                # -------------------------------------------

                attr_name = get_cell(
                    row_idx,
                    'Product Attributes/Attribute'
                )

                attr_values = get_cell(
                    row_idx,
                    'Product Attributes/Values'
                )

                if attr_name and attr_values:
<<<<<<< HEAD
<<<<<<< HEAD
=======
                    # Clean and split values (e.g., "Red, Blue" -> ["Red", "Blue"])
>>>>>>> bi_binsha_nakshathra_changes
                    val_list = [v.strip() for v in str(attr_values).split(',')]
                    if attr_name in grouped_products[last_valid_name]['attributes']:
                        grouped_products[last_valid_name]['attributes'][attr_name].extend(val_list)
                    else:
                        grouped_products[last_valid_name]['attributes'][attr_name] = val_list

<<<<<<< HEAD
            # --- STEP 2: CREATION WITH DUPLICATION CHECK ---
            count = 0
            for p_name, p_data in grouped_products.items():
                # CHECK IF PRODUCT ALREADY EXISTS
=======
            # --- STEP 2: PRODUCT CREATION AND ATTRIBUTE MAPPING ---
=======

                    attr_name = str(attr_name).strip()

                    val_list = [
                        v.strip()
                        for v in str(attr_values).split(',')
                        if v.strip()
                    ]

                    if attr_name not in grouped_products[last_valid_name]['attributes']:
                        grouped_products[last_valid_name]['attributes'][attr_name] = []

                    grouped_products[last_valid_name]['attributes'][attr_name].extend(
                        val_list
                    )

            # ---------------------------------------------------
            # STEP 2 : CREATE PRODUCTS
            # ---------------------------------------------------

>>>>>>> bi_binsha_nakshathra_changes
            count = 0

            for p_name, p_data in grouped_products.items():
<<<<<<< HEAD
                # 1. Search for existing product
>>>>>>> bi_binsha_nakshathra_changes
                product = request.env['product.template'].search([('name', '=', p_name)], limit=1)
                
                if not product:
                    product = request.env['product.template'].create(p_data['info'])
                    _logger.info(f"Created new product: {p_name}")
                else:
<<<<<<< HEAD
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
=======
                    _logger.info(f"Product {p_name} exists, checking for attribute updates.")
                
                # 2. Map Attributes and Values
                for a_name, a_vals in p_data['attributes'].items():
                    # Find or create the global Attribute (e.g., "Color")
                    attribute = request.env['product.attribute'].search([('name', '=', a_name)], limit=1)
                    if not attribute:
                        attribute = request.env['product.attribute'].create({
                            'name': a_name, 
                            'create_variant': 'always'
                        })
=======
>>>>>>> bi_binsha_nakshathra_changes

                try:

                    # ---------------------------------------
                    # PRODUCT
                    # ---------------------------------------

                    product = request.env['product.template'].search([
                        ('name', '=', p_name)
                    ], limit=1)

                    if not product:

                        product = request.env['product.template'].create(
                            p_data['info']
                        )

                        _logger.info(f"Created product : {p_name}")

                    else:

                        _logger.info(f"Product exists : {p_name}")

                    # ---------------------------------------
                    # ATTRIBUTES
                    # ---------------------------------------

                    for a_name, a_vals in p_data['attributes'].items():

                        # -----------------------------------
                        # SEARCH ATTRIBUTE ONLY
                        # DO NOT CREATE ATTRIBUTE
                        # -----------------------------------

                        attribute = request.env['product.attribute'].search([
                            ('name', 'ilike', a_name.strip())
                        ], limit=1)

<<<<<<< HEAD
                    if value_ids:
                        # 3. Link Attribute to the specific Product (Attribute Line)
>>>>>>> bi_binsha_nakshathra_changes
                        existing_line = request.env['product.template.attribute.line'].search([
                            ('product_tmpl_id', '=', product.id),
                            ('attribute_id', '=', attribute.id)
                        ], limit=1)
                        
<<<<<<< HEAD
                        if not existing_line:
=======
                        if existing_line:
                            # Update: Combine existing values with new ones from Excel
                            current_vals = existing_line.value_ids.ids
                            combined_vals = list(set(current_vals + value_ids))
                            existing_line.write({'value_ids': [(6, 0, combined_vals)]})
                        else:
                            # Create: New line for this product
>>>>>>> bi_binsha_nakshathra_changes
                            try:
                                request.env['product.template.attribute.line'].create({
                                    'product_tmpl_id': product.id,
                                    'attribute_id': attribute.id,
                                    'value_ids': [(6, 0, value_ids)]
                                })
                            except Exception as attr_err:
<<<<<<< HEAD
                                _logger.warning(f"Attribute line skip: {str(attr_err)}")
=======
                                _logger.warning(f"Could not map attribute {a_name} to {p_name}: {str(attr_err)}")
>>>>>>> bi_binsha_nakshathra_changes
                
                count += 1

            request.env.cr.commit()
<<<<<<< HEAD
            return f"<h1>Import Finished</h1><p>Processed {count} unique products from Excel.</p>"
        except Exception as e:
            _logger.error(f"Import Failed: {str(e)}")
            return f"<h1>Error</h1><p>{str(e)}</p>"
=======
            return f"<h1>Import Finished</h1><p>Successfully processed {count} products and their attributes.</p>"
=======
                        if not attribute:
                            _logger.warning(
                                f"Attribute not found : {a_name}"
                            )
                            continue

                        # -----------------------------------
                        # SKIP HUGE ATTRIBUTES
                        # -----------------------------------

                        if attribute.create_variant == 'always':

                            total_combinations = 1

                            for line in product.attribute_line_ids:
                                total_combinations *= max(
                                    1,
                                    len(line.value_ids)
                                )

                            estimated = total_combinations * max(
                                1,
                                len(set(a_vals))
                            )

                            if estimated > 500:
                                _logger.warning(
                                    f"Skipping huge combination "
                                    f"for {product.name} "
                                    f"Attribute : {a_name} "
                                    f"Estimated : {estimated}"
                                )
                                continue

                        # -----------------------------------
                        # ATTRIBUTE VALUES
                        # -----------------------------------

                        value_ids = []

                        for val_name in set(a_vals):

                            val_name = str(val_name).strip()

                            v_rec = request.env[
                                'product.attribute.value'
                            ].search([
                                ('name', 'ilike', val_name),
                                ('attribute_id', '=', attribute.id)
                            ], limit=1)

                            if not v_rec:

                                _logger.warning(
                                    f"Value not found : "
                                    f"{val_name} "
                                    f"for attribute {a_name}"
                                )

                                continue

                            value_ids.append(v_rec.id)

                        if not value_ids:
                            continue

                        # -----------------------------------
                        # ATTRIBUTE LINE
                        # -----------------------------------

                        existing_line = request.env[
                            'product.template.attribute.line'
                        ].search([
                            ('product_tmpl_id', '=', product.id),
                            ('attribute_id', '=', attribute.id)
                        ], limit=1)

                        if existing_line:

                            existing_ids = existing_line.value_ids.ids

                            missing_vals = list(
                                set(value_ids) - set(existing_ids)
                            )

                            if missing_vals:

                                existing_line.write({
                                    'value_ids': [
                                        (4, val_id)
                                        for val_id in missing_vals
                                    ]
                                })

                                _logger.info(
                                    f"Updated attribute "
                                    f"{a_name} "
                                    f"for {p_name}"
                                )

                        else:

                            request.env[
                                'product.template.attribute.line'
                            ].create({
                                'product_tmpl_id': product.id,
                                'attribute_id': attribute.id,
                                'value_ids': [(6, 0, value_ids)]
                            })

                            _logger.info(
                                f"Created attribute line "
                                f"{a_name} "
                                f"for {p_name}"
                            )

                    count += 1

                    # ---------------------------------------
                    # COMMIT EVERY 20 PRODUCTS
                    # ---------------------------------------

                    if count % 20 == 0:
                        request.env.cr.commit()
                        _logger.info(
                            f"Committed {count} products"
                        )

                except Exception as product_error:

                    request.env.cr.rollback()

                    _logger.error(
                        f"Error processing {p_name} : "
                        f"{str(product_error)}"
                    )

                    continue

            # ---------------------------------------------------
            # FINAL COMMIT
            # ---------------------------------------------------

            request.env.cr.commit()

            return (
                f"<h1>Import Finished</h1>"
                f"<p>Successfully processed {count} products.</p>"
            )
>>>>>>> bi_binsha_nakshathra_changes

        except Exception as e:

            request.env.cr.rollback()

            _logger.exception("IMPORT FAILED")

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
#         # Increase variant limit for large imports
#         request.env['ir.config_parameter'].sudo().set_param('product.dynamic_variant_limit', 20000)
        
#         file_name = 'PRODUCT TEMPLATE FINAL.xlsx'
#         file_path = get_module_resource('custom_product_import', 'data', file_name)
        
#         if not file_path or not os.path.exists(file_path):
#             return f"<h1>Error</h1><p>File not found at {file_path}</p>"

#         try:
#             workbook = openpyxl.load_workbook(file_path, data_only=True)
#             sheet = workbook.active
            
#             # Map headers to column indices
#             h_map = {str(sheet.cell(row=1, column=i).value).strip(): i 
#                      for i in range(1, sheet.max_column + 1) 
#                      if sheet.cell(row=1, column=i).value}

#             grouped_products = {}
#             last_valid_name = False 

#             # --- STEP 1: DATA GROUPING ---
#             for row_idx in range(2, sheet.max_row + 1):
#                 def get_v(col_name):
#                     idx = h_map.get(col_name)
#                     return sheet.cell(row=row_idx, column=idx).value if idx else False

#                 row_name = get_v('Name')
#                 if row_name:
#                     last_valid_name = str(row_name).strip()

#                 if not last_valid_name:
#                     continue

#                 if last_valid_name not in grouped_products:
#                     def is_yes(val):
#                         return str(val).lower() in ['yes', '1', '1.0', 'true', '1.00']

#                     grouped_products[last_valid_name] = {
#                         'info': {
#                             'name': last_valid_name,
#                             'standard_price': float(get_v('Cost') or 0.0),
#                             'uom_id': request.env['uom.uom'].search([('name', '=', get_v('Unit of Measure'))], limit=1).id or request.env.ref('uom.product_uom_unit').id,
#                             'company_id': request.env['res.company'].search([('name', '=', get_v('Company'))], limit=1).id or request.env.company.id,
#                             'purity_id': request.env['gold.purity'].search([('name', '=', str(get_v('Purity')).strip())], limit=1).id if get_v('Purity') else False,
#                             'sale_ok': is_yes(get_v('Can be Sold')),
#                             'purchase_ok': is_yes(get_v('Can be Purchased')),
#                             'type': 'product',
#                         },
#                         'attributes': {}
#                     }
                
#                 attr_name = str(get_v('Product Attributes/Attribute')).strip() if get_v('Product Attributes/Attribute') else False
#                 attr_values = get_v('Product Attributes/Values')

#                 if attr_name and attr_values:
#                     # Clean and split values (e.g., "Red, Blue" -> ["Red", "Blue"])
#                     val_list = [v.strip() for v in str(attr_values).split(',')]
#                     if attr_name in grouped_products[last_valid_name]['attributes']:
#                         grouped_products[last_valid_name]['attributes'][attr_name].extend(val_list)
#                     else:
#                         grouped_products[last_valid_name]['attributes'][attr_name] = val_list

#             # --- STEP 2: PRODUCT CREATION AND ATTRIBUTE MAPPING ---
#             count = 0
#             for p_name, p_data in grouped_products.items():
#                 # 1. Search for existing product
#                 product = request.env['product.template'].search([('name', '=', p_name)], limit=1)
                
#                 if not product:
#                     product = request.env['product.template'].create(p_data['info'])
#                     _logger.info(f"Created new product: {p_name}")
#                 else:
#                     _logger.info(f"Product {p_name} exists, checking for attribute updates.")
                
#                 # 2. Map Attributes and Values
#                 for a_name, a_vals in p_data['attributes'].items():
#                     # Find or create the global Attribute (e.g., "Color")
#                     attribute = request.env['product.attribute'].search([('name', '=', a_name)], limit=1)
#                     if not attribute:
#                         attribute = request.env['product.attribute'].create({
#                             'name': a_name, 
#                             'create_variant': 'always'
#                         })

#                     # Find or create the Attribute Values (e.g., "Gold", "Silver")
#                     value_ids = []
#                     for val_name in set(a_vals): # Use set() to avoid duplicates in the same row
#                         v_rec = request.env['product.attribute.value'].search([
#                             ('name', '=', val_name), 
#                             ('attribute_id', '=', attribute.id)
#                         ], limit=1)
#                         if not v_rec:
#                             v_rec = request.env['product.attribute.value'].create({
#                                 'name': val_name, 
#                                 'attribute_id': attribute.id
#                             })
#                         value_ids.append(v_rec.id)

#                     if value_ids:
#                         # 3. Link Attribute to the specific Product (Attribute Line)
#                         existing_line = request.env['product.template.attribute.line'].search([
#                             ('product_tmpl_id', '=', product.id),
#                             ('attribute_id', '=', attribute.id)
#                         ], limit=1)
                        
#                         if existing_line:
#                             # Update: Combine existing values with new ones from Excel
#                             current_vals = existing_line.value_ids.ids
#                             combined_vals = list(set(current_vals + value_ids))
#                             existing_line.write({'value_ids': [(6, 0, combined_vals)]})
#                         else:
#                             # Create: New line for this product
#                             try:
#                                 request.env['product.template.attribute.line'].create({
#                                     'product_tmpl_id': product.id,
#                                     'attribute_id': attribute.id,
#                                     'value_ids': [(6, 0, value_ids)]
#                                 })
#                             except Exception as attr_err:
#                                 _logger.warning(f"Could not map attribute {a_name} to {p_name}: {str(attr_err)}")
                
#                 count += 1

#             request.env.cr.commit()
#             return f"<h1>Import Finished</h1><p>Successfully processed {count} products and their attributes.</p>"

#         except Exception as e:
#             _logger.error(f"Import Failed: {str(e)}")
#             return f"<h1>Error</h1><p>{str(e)}</p>"

<<<<<<< HEAD

>>>>>>> bi_binsha_nakshathra_changes
=======
>>>>>>> bi_binsha_nakshathra_changes
