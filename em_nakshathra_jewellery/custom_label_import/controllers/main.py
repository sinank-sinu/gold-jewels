import openpyxl
import logging
import os
import base64
from io import BytesIO
from datetime import timedelta
from odoo import http, fields
from odoo.http import request
from odoo.modules.module import get_module_resource
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

_logger = logging.getLogger(__name__)

class LabelPurchaseImportController(http.Controller):

    @http.route('/import/labels_purchase/now', type='http', auth='user')
    def trigger_import(self, **kwargs):
        # Path to the specific Excel file
        file_name = 'productlabel sample.xlsx'
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

            count = 0
            skipped = 0
            unimported_list = []
            
            supplier_po_map = {}
            po_total_map = {}
            po_line_weight_map = {}
            
            opening_balance_account = request.env['account.account'].search([
                ('name', 'ilike', 'opening balance'),
                ('company_id', '=', request.env.company.id)
            ], limit=1)
            
            # If standard account not found, fallback to just name search across all
            if not opening_balance_account:
                opening_balance_account = request.env['account.account'].search([
                    ('name', 'ilike', 'opening balance')
                ], limit=1)

            for row_idx in range(2, sheet.max_row + 1):
                def get_v(col_name):
                    idx = h_map.get(col_name)
                    return sheet.cell(row=row_idx, column=idx).value if idx else False

                barcode = str(get_v('Barcode')).strip() if get_v('Barcode') else False
                
                # Check for 'Purchase Order' column first, then fallback to 'Supplier Name'
                po_column_val = get_v('Purchase Order') or get_v('Supplier Name')
                supplier_name = str(po_column_val).strip() if po_column_val else False
                
                # --- 1. Identify Template and Attributes Exactly ---
                template_name_excel = str(get_v('Product') or get_v('Product/Product Template') or '').strip()
                variant_attrs_excel = str(get_v('Product Variant') or get_v('Product/Product') or '').strip()

                if not barcode and not template_name_excel:
                    # Empty row, skip without logging
                    continue

                if not barcode:
                    unimported_list.append({
                        'row': row_idx,
                        'barcode': '',
                        'product': template_name_excel,
                        'variant': variant_attrs_excel,
                        'reason': 'Missing Barcode'
                    })
                    skipped += 1
                    continue

                template = request.env['product.template'].search([('name', '=', template_name_excel)], limit=1)

                if not template:
                    _logger.error(f"FAIL: Could not find template '{template_name_excel}'")
                    unimported_list.append({
                        'row': row_idx,
                        'barcode': barcode,
                        'product': template_name_excel,
                        'variant': variant_attrs_excel,
                        'reason': f"Could not find template '{template_name_excel}'"
                    })
                    skipped += 1
                    continue

                # Fixed attribute name order corresponding to Excel tuple positions,
                # matching actual DB attribute names (case-insensitive match used below):
                # pos0=metal, pos1=varieity 1, pos2=type1, pos3=Design, pos4=Stone color1, pos5=Size 1
                ATTR_POSITION_NAMES = [
                    'Metal Colour', # tuple position 0
                    'Variety',   # tuple position 1
                    'Type',        # tuple position 2
                    'Design',       # tuple position 3
                    'Stone Colour', # tuple position 4
                    'Size',       # tuple position 5
                ]

                ptav_ids = request.env['product.template.attribute.value']
                if variant_attrs_excel.startswith('(') and variant_attrs_excel.endswith(')'):
                    attr_val_names = [v.strip() for v in variant_attrs_excel.strip('()').split(',')]
                    for pos, val_name in enumerate(attr_val_names):
                        if not val_name or val_name.lower() in ('none', 'false', ''):
                            continue
                        if pos >= len(ATTR_POSITION_NAMES):
                            continue
                        attr_name = ATTR_POSITION_NAMES[pos]
                        # Find the attribute line in this product by attribute name
                        attr_line = template.attribute_line_ids.filtered(
                            lambda al, an=attr_name: al.attribute_id.name.strip().lower() == an.lower()
                        )
                        if not attr_line:
                            _logger.warning(
                                f"Row {row_idx}: Attribute '{attr_name}' not found in product '{template.name}' — skipping position {pos}."
                            )
                            continue
                        # Find the matching value (case-insensitive)
                        ptav = attr_line[0].product_template_value_ids.filtered(
                            lambda v, vn=val_name: v.name.strip().lower() == vn.lower()
                        )
                        if ptav:
                            ptav_ids |= ptav[0]
                        else:
                            _logger.warning(
                                f"Row {row_idx}: Value '{val_name}' not found for attribute '{attr_name}' in product '{template.name}'."
                            )
                else:
                    # Fallback: match by full display name
                    for v in template.product_variant_ids:
                        if v.display_name.strip() == variant_attrs_excel:
                            ptav_ids = v.product_template_attribute_value_ids
                            break

                # Find the variant whose attribute combination contains all matched PTAVs.
                # We use subset matching because _get_variant_for_combination requires
                # ALL PTAVs (including None-valued ones) which we intentionally skip.
                variant_rec = None
                if ptav_ids:
                    matching = template.product_variant_ids.filtered(
                        lambda v: ptav_ids <= v.product_template_attribute_value_ids
                    )
                    if matching:
                        variant_rec = matching[0]
                    else:
                        _logger.warning(
                            f"Row {row_idx}: No variant found for {template.name} "
                            f"with PTAVs {ptav_ids.mapped('name')}. Trying to create."
                        )
                        try:
                            variant_rec = template._create_product_variant(ptav_ids)
                        except Exception as e:
                            _logger.warning(f"Could not create variant for {template.name}: {e}")
                if not variant_rec:
                    variant_rec = template.product_variant_ids[:1]


                # Avoid duplicate imports based on Barcode
                if request.env['product.label'].search([('barcode', '=', barcode)], limit=1):
                    unimported_list.append({
                        'row': row_idx,
                        'barcode': barcode,
                        'product': template_name_excel,
                        'variant': variant_attrs_excel,
                        'reason': 'Duplicate Barcode (Already imported)'
                    })
                    skipped += 1
                    continue

                # --- Create or find Partner & PO ---
                po_rec = False
                po_line_amount = 0.0
                if supplier_name:
                    if supplier_name not in supplier_po_map:
                        partner = request.env['res.partner'].search([('name', '=', supplier_name)], limit=1)
                        if not partner:
                            partner = request.env['res.partner'].create({'name': supplier_name, 'supplier_rank': 1})
                        
                        po_rec = request.env['purchase.order'].create({
                            'partner_id': partner.id,
                            'state': 'draft',
                        })
                        supplier_po_map[supplier_name] = po_rec
                        po_total_map[po_rec.id] = 0.0
                    else:
                        po_rec = supplier_po_map[supplier_name]
                        
                    purchase_metal_rate = float(get_v('Purchase Metal Amount') or 0.0)
                    purchase_mc_amt = float(get_v('Purchase Making Charge Amount') or 0.0)
                    purchase_stone_rate = float(get_v('Purchase Stone Amount') or 0.0)
                    purchase_diamond_rate = float(get_v('Purchase Diamond Amount') or 0.0)
                    po_line_amount = purchase_metal_rate + purchase_mc_amt + purchase_stone_rate + purchase_diamond_rate
                    po_line_qty = float(get_v('Order Lines/Quantity') or 1.0)
                    
                    if po_rec and variant_rec:
                        po_line = request.env['purchase.order.line'].create({
                            'order_id': po_rec.id,
                            'product_id': variant_rec.id,
                            'name': variant_rec.display_name or template.name,
                            'product_qty': po_line_qty,
                            'price_unit': po_line_amount,
                            'date_planned': fields.Datetime.now(),
                        })
                        po_total_map[po_rec.id] += (po_line_amount * po_line_qty)
                        po_line_weight_map[po_line.id] = float(get_v('Purchase Gross Amount (g)') or 0.0)

                # --- 3. Prepare Mapping ---
                raw_type = str(get_v('Purchase Making Charge Type')).strip()
                mc_type_mapping = {
                    'Percentage': 'percent', 
                    'Amount': 'amount', 
                    'Rate per Gram': 'rate_per_gram'
                }
                making_charge_key = mc_type_mapping.get(raw_type, 'percent')

                age_from_excel = get_v('Age (Days)')

                vals = {
                    'name': get_v('Label Name'),
                    'product_template_id': template.id,
                    'product_id': variant_rec.id if variant_rec else False,
                    'product_template_attribute_value_ids': [(6, 0, ptav_ids.ids)],
                    'branch_id': self._find_m2o('res.branch', get_v('Branch')), 
                    'branch_location_id': self._find_m2o('stock.location', get_v('Branch Location') or get_v('Destination Location')),
                    'source_location_id': self._find_m2o('stock.location', get_v('Source Location')),
                    'tag_weight': get_v('Tag Weight (g)'),
                    'purity_id': self._find_m2o('gold.purity', get_v('Purity')),
                    'barcode': barcode,
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
                    'purchase_id': po_rec.id if po_rec else False,
                }

                try:
                    new_label = request.env['product.label'].create(vals)
                    count += 1
                except Exception as row_err:
                    _logger.error(f"Failed to create label at row {row_idx}: {str(row_err)}")
                    request.env.cr.rollback()
                    unimported_list.append({
                        'row': row_idx,
                        'barcode': barcode,
                        'product': template_name_excel,
                        'variant': variant_attrs_excel,
                        'reason': f"Creation Error: {str(row_err)}"
                    })
                    skipped += 1
                    continue

                # Backdate create_date so the computed 'age' field shows the correct
                # historical value from the Excel (age = today - create_date + 1)
                try:
                    age_int = int(float(str(age_from_excel))) if age_from_excel else 0
                    if age_int > 1:
                        historical_date = fields.Datetime.now() - timedelta(days=age_int - 1)
                        request.env.cr.execute(
                            "UPDATE product_label SET create_date = %s WHERE id = %s",
                            (historical_date, new_label.id)
                        )
                except Exception as age_err:
                    _logger.warning(f"Row {row_idx}: Could not set age: {age_err}")

                # Always attempt stock-in for each label — action_stock_in validates locations
                try:
                    if new_label.product_id and new_label.source_location_id:
                        qty = new_label.purchase_gross_weight or new_label.sale_gross_weight or 1.0
                        self._create_or_update_stock(new_label.product_id.id, new_label.source_location_id.id, qty)
                    new_label.action_stock_in()
                except Exception as stock_err:
                    _logger.warning(f"Label {new_label.name} stock-in skipped at row {row_idx}: {str(stock_err)}")

            # Confirm all POs and create Journal Entries
            for po_rec in supplier_po_map.values():
                try:
                    po_rec.button_confirm()
                    
                    # Validate stock for PO
                    for picking in po_rec.picking_ids.filtered(lambda p: p.state not in ['done', 'cancel']):
                        for move in picking.move_ids_without_package:
                            if move.purchase_line_id and move.purchase_line_id.id in po_line_weight_map:
                                move.quantity = po_line_weight_map[move.purchase_line_id.id]
                            else:
                                move.quantity = move.product_uom_qty
                        picking.button_validate()
                        
                except Exception as e:
                    _logger.warning(f"Could not confirm/validate PO {po_rec.name}: {e}")
                
                # Create Purchase Journal Entry / Vendor Bill
                total_amount = po_total_map.get(po_rec.id, 0.0)
                if total_amount > 0 and opening_balance_account:
                    try:
                        # 1. Create Vendor Bill
                        po_rec.action_create_invoice()
                        
                        # Get created bill
                        bill = po_rec.invoice_ids.filtered(lambda m: m.state == 'draft')
                        if bill:
                            bill.invoice_date = fields.Date.context_today(po_rec)
                            bill.date = fields.Date.context_today(po_rec)
                            
                            # 2. Post Bill
                            bill.action_post()
                            
                            # 3. Register Payment
                            try:
                                ctx = {'active_model': 'account.move', 'active_ids': bill.ids}
                                payment_register = request.env['account.payment.register'].with_context(ctx).create({})
                                payment_register.action_create_payments()
                            except Exception as pay_err:
                                _logger.warning(f"Could not register payment for bill {bill.name}: {pay_err}")
                                
                    except Exception as e:
                        _logger.warning(f"Could not create/post Vendor Bill for PO {po_rec.name}: {e}")

            request.env.cr.commit()

            # Generate PDF Report of Unimported / Skipped Products
            download_btn_html = ""
            if unimported_list:
                try:
                    pdf_data = self._generate_skipped_pdf(unimported_list)
                    attachment = request.env['ir.attachment'].create({
                        'name': 'unimported_products_report.pdf',
                        'type': 'binary',
                        'datas': base64.b64encode(pdf_data),
                        'res_model': 'res.users',
                        'res_id': request.env.uid,
                        'mimetype': 'application/pdf',
                    })
                    # Commit attachment creation
                    request.env.cr.commit()
                    download_btn_html = f"""
                    <div style="margin-top: 20px;">
                        <a href="/web/content/{attachment.id}?download=true" 
                           style="background-color: #7C5BBA; color: white; padding: 12px 20px; text-decoration: none; font-weight: bold; border-radius: 4px; display: inline-block; font-family: sans-serif;">
                            Download Unimported Products Report (PDF)
                        </a>
                    </div>
                    """
                except Exception as pdf_err:
                    _logger.error(f"Failed to generate skipped report PDF: {pdf_err}")
                    download_btn_html = f"<p style='color: red;'>Failed to generate PDF Report: {pdf_err}</p>"

            return f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
                <h1 style="color: #7C5BBA; margin-top: 0;">Import Finished</h1>
                <p style="font-size: 16px; color: #333;"><strong>Created labels:</strong> {count}</p>
                <p style="font-size: 16px; color: #333;"><strong>Skipped labels:</strong> {skipped}</p>
                {download_btn_html}
            </div>
            """

        except Exception as e:
            _logger.error(f"Critical Import Failure: {str(e)}")
            return f"<h1>Error</h1><p>{str(e)}</p>"

    @http.route('/import/labels_purchase/transfer_pending', type='http', auth='user')
    def transfer_pending_labels(self, **kwargs):
        """Bulk-transfer all existing labels that have locations set but haven't been stocked in yet."""
        pending = request.env['product.label'].search([
            ('is_stocked_in', '=', False),
            ('branch_location_id', '!=', False),
            ('source_location_id', '!=', False),
        ])
        success = 0
        failed = 0
        for label in pending:
            try:
                if label.product_id and label.source_location_id:
                    qty = label.purchase_gross_weight or label.sale_gross_weight or 1.0
                    self._create_or_update_stock(label.product_id.id, label.source_location_id.id, qty)
                label.action_stock_in()
                success += 1
            except Exception as e:
                _logger.warning(f"Transfer failed for label {label.name}: {e}")
                failed += 1
        request.env.cr.commit()
        return (f"<h1>Bulk Transfer Complete</h1>"
                f"<p>Transferred: {success} | Failed: {failed} | Total Pending: {len(pending)}</p>")

    def _generate_skipped_pdf(self, unimported_list):
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        story = []
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=18,
            textColor=colors.HexColor('#7C5BBA'),
            spaceAfter=15
        )
        normal_style = styles['Normal']
        header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontName='Helvetica-Bold', textColor=colors.white)
        
        story.append(Paragraph("Unimported / Skipped Products Report", title_style))
        story.append(Spacer(1, 10))
        
        # Table data
        data = [[
            Paragraph("Row", header_style),
            Paragraph("Barcode", header_style),
            Paragraph("Product / Template", header_style),
            Paragraph("Variant Attributes", header_style),
            Paragraph("Reason for Skipping", header_style)
        ]]
        
        col_widths = [40, 90, 120, 120, 170]
        
        for item in unimported_list:
            data.append([
                Paragraph(str(item['row']), normal_style),
                Paragraph(str(item['barcode'] or ''), normal_style),
                Paragraph(str(item['product'] or ''), normal_style),
                Paragraph(str(item['variant'] or ''), normal_style),
                Paragraph(str(item['reason'] or ''), normal_style)
            ])
            
        t = Table(data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#7C5BBA')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#D3D3D3')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F9F9F9')]),
        ]))
        
        story.append(t)
        doc.build(story)
        return buffer.getvalue()

    def _create_or_update_stock(self, product_id, location_id, qty):
        if not product_id or not location_id or not qty or qty <= 0:
            return
        try:
            quant = request.env['stock.quant'].with_context(inventory_mode=True).search([
                ('product_id', '=', product_id),
                ('location_id', '=', location_id),
            ], limit=1)
            if quant:
                quant.inventory_quantity = quant.quantity + qty
            else:
                quant = request.env['stock.quant'].with_context(inventory_mode=True).create({
                    'product_id': product_id,
                    'location_id': location_id,
                    'inventory_quantity': qty,
                })
            quant.action_apply_inventory()
        except Exception as e:
            _logger.error(f"Failed to set stock for product {product_id} at location {location_id}: {e}")

    def _find_m2o(self, model, name):
        if not name: return False
        name = str(name).strip()
        if model == 'stock.location':
            # Use case-insensitive search on complete_name first (e.g. 'WH/Stock'),
            # then fall back to partial name match (e.g. 'KNR FINAL' → 'KNR Final')
            record = request.env[model].search(
                [('complete_name', 'ilike', name), ('usage', 'in', ['internal', 'supplier', 'inventory'])], limit=1
            )
            if not record:
                record = request.env[model].search(
                    [('name', 'ilike', name), ('usage', 'in', ['internal', 'supplier', 'inventory'])], limit=1
                )
        else:
            record = request.env[model].search([('name', '=', name)], limit=1)
        return record.id if record else False

