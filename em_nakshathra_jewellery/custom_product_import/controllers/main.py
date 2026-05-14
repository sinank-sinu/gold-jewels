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
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"

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

            count = 0

            for p_name, p_data in grouped_products.items():

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

        except Exception as e:

            request.env.cr.rollback()

            _logger.exception("IMPORT FAILED")

            return f"<h1>Error</h1><p>{str(e)}</p>"
