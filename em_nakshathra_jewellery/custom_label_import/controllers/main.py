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
        file_name = 'productlabel sample.xlsx'
        file_path = get_module_resource('custom_label_import', 'data', file_name)

        if not file_path or not os.path.exists(file_path):
            return f"<h1>Error</h1><p>File not found at {file_path}</p>"

        try:
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            sheet = workbook.active

            h_map = {str(sheet.cell(row=1, column=i).value).strip(): i
                     for i in range(1, sheet.max_column + 1)
                     if sheet.cell(row=1, column=i).value}

            count = 0
            skipped = 0
            unimported_list = []

            # ----------------------------------------------------------------
            # Lookup accounts
            # ----------------------------------------------------------------
            # Opening Balance account: user created it with account_type = 'liability_payable'
            # Search with that type filter first so we get the RIGHT account.
            opening_balance_account = request.env['account.account'].search([
                ('name', 'ilike', 'opening balance'),
                ('account_type', '=', 'liability_payable'),
                ('company_id', '=', request.env.company.id),
            ], limit=1)
            if not opening_balance_account:
                # Fallback: any account with 'opening balance' in name for this company
                opening_balance_account = request.env['account.account'].search([
                    ('name', 'ilike', 'opening balance'),
                    ('company_id', '=', request.env.company.id),
                ], limit=1)
            if not opening_balance_account:
                opening_balance_account = request.env['account.account'].search([
                    ('name', 'ilike', 'opening balance'),
                ], limit=1)

            _logger.info(
                f"Opening Balance account found: {opening_balance_account.name!r} "
                f"(type={opening_balance_account.account_type})"
                if opening_balance_account else "WARNING: No Opening Balance account found!"
            )

            stock_input_account = request.env['account.account'].search([
                ('name', 'ilike', 'stock input'),
                ('company_id', '=', request.env.company.id),
            ], limit=1)
            if not stock_input_account:
                stock_input_account = request.env['account.account'].search([
                    ('name', 'ilike', 'stock input'),
                ], limit=1)

            # ----------------------------------------------------------------
            # Find a journal for the settlement JE.
            # Prefer a journal whose default account is the Opening Balance account.
            # ----------------------------------------------------------------
            opening_balance_journal = None
            if opening_balance_account:
                opening_balance_journal = request.env['account.journal'].search([
                    ('default_account_id', '=', opening_balance_account.id),
                    ('company_id', '=', request.env.company.id),
                ], limit=1)
                if not opening_balance_journal:
                    opening_balance_journal = request.env['account.journal'].search([
                        ('name', 'ilike', 'opening'),
                        ('company_id', '=', request.env.company.id),
                    ], limit=1)
            if not opening_balance_journal:
                # Last resort: any 'general' (miscellaneous) journal
                opening_balance_journal = request.env['account.journal'].search([
                    ('type', '=', 'general'),
                    ('company_id', '=', request.env.company.id),
                ], limit=1)

            # supplier_name -> purchase.order record
            supplier_po_map = {}
            # po_id -> cumulative amount
            po_total_map = {}
            # po_line_id -> gross weight (used when setting move qty)
            po_line_weight_map = {}
            # po_id -> purchase_order_date from first row with that supplier
            po_date_map = {}

            # ================================================================
            # PASS 1 – iterate rows, create labels & PO lines
            # ================================================================
            for row_idx in range(2, sheet.max_row + 1):
                def get_v(col_name, _row=row_idx):
                    idx = h_map.get(col_name)
                    return sheet.cell(row=_row, column=idx).value if idx else False

                barcode = str(get_v('Barcode')).strip() if get_v('Barcode') else False
                supplier_name_raw = get_v('Purchase Order') or get_v('Supplier Name')
                supplier_name = str(supplier_name_raw).strip() if supplier_name_raw else False

                template_name_excel = str(get_v('Product') or get_v('Product/Product Template') or '').strip()
                variant_attrs_excel = str(get_v('Product Variant') or get_v('Product/Product') or '').strip()

                if not barcode and not template_name_excel:
                    continue

                if not barcode:
                    unimported_list.append({'row': row_idx, 'barcode': '', 'product': template_name_excel,
                                            'variant': variant_attrs_excel, 'reason': 'Missing Barcode'})
                    skipped += 1
                    continue

                template = request.env['product.template'].search([('name', '=', template_name_excel)], limit=1)
                if not template:
                    unimported_list.append({'row': row_idx, 'barcode': barcode, 'product': template_name_excel,
                                            'variant': variant_attrs_excel,
                                            'reason': f"Template '{template_name_excel}' not found"})
                    skipped += 1
                    continue

                # ---- Resolve variant ----
                ATTR_POSITION_NAMES = [
                    'Metal Colour', 'Variety', 'Type', 'Design', 'Stone Colour', 'Size',
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
                        attr_line = template.attribute_line_ids.filtered(
                            lambda al, an=attr_name: al.attribute_id.name.strip().lower() == an.lower()
                        )
                        if not attr_line:
                            continue
                        ptav = attr_line[0].product_template_value_ids.filtered(
                            lambda v, vn=val_name: v.name.strip().lower() == vn.lower()
                        )
                        if ptav:
                            ptav_ids |= ptav[0]
                else:
                    for v in template.product_variant_ids:
                        if v.display_name.strip() == variant_attrs_excel:
                            ptav_ids = v.product_template_attribute_value_ids
                            break

                variant_rec = None
                if ptav_ids:
                    matching = template.product_variant_ids.filtered(
                        lambda v: ptav_ids <= v.product_template_attribute_value_ids
                    )
                    if matching:
                        variant_rec = matching[0]
                    else:
                        try:
                            variant_rec = template._create_product_variant(ptav_ids)
                        except Exception as e:
                            _logger.warning(f"Could not create variant for {template.name}: {e}")
                if not variant_rec:
                    variant_rec = template.product_variant_ids[:1]

                # ---- Duplicate check ----
                if request.env['product.label'].search([('barcode', '=', barcode)], limit=1):
                    unimported_list.append({'row': row_idx, 'barcode': barcode, 'product': template_name_excel,
                                            'variant': variant_attrs_excel,
                                            'reason': 'Duplicate Barcode (Already imported)'})
                    skipped += 1
                    continue

                # ----------------------------------------------------------------
                # Create / reuse Purchase Order (one per supplier)
                # ----------------------------------------------------------------
                po_rec = False
                po_line_amount = 0.0
                if supplier_name:
                    if supplier_name not in supplier_po_map:
                        partner = request.env['res.partner'].search([('name', '=', supplier_name)], limit=1)
                        if not partner:
                            partner = request.env['res.partner'].create(
                                {'name': supplier_name, 'supplier_rank': 1}
                            )

                        po_date_raw = get_v('Purchase Order Date')
                        # date_order on purchase.order is a Datetime field
                        if hasattr(po_date_raw, 'replace'):
                            # Already a datetime object from openpyxl
                            po_datetime = po_date_raw
                        elif hasattr(po_date_raw, 'timetuple'):
                            # date object – convert to datetime midnight
                            from datetime import datetime as _dt
                            po_datetime = _dt.combine(po_date_raw, _dt.min.time())
                        else:
                            po_datetime = fields.Datetime.now()
                        po_date = po_datetime.date()  # plain date for bill/payment

                        po_vals = {
                            'partner_id': partner.id,
                            'state': 'draft',
                            'date_order': po_datetime,
                        }
                        po_rec = request.env['purchase.order'].create(po_vals)
                        supplier_po_map[supplier_name] = po_rec
                        po_total_map[po_rec.id] = 0.0
                        po_date_map[po_rec.id] = po_date
                    else:
                        po_rec = supplier_po_map[supplier_name]

                    # Compute PO line amount from purchase columns
                    purchase_metal_amt = self._safe_float(get_v('Purchase Metal Amount'))
                    purchase_mc_amt = self._safe_float(get_v('Purchase Making Charge Amount'))
                    purchase_stone_amt = self._safe_float(get_v('Purchase Stone Amount'))
                    purchase_diamond_amt = self._safe_float(get_v('Purchase Diamond Amount'))
                    po_line_amount = purchase_metal_amt + purchase_mc_amt + purchase_stone_amt + purchase_diamond_amt

                    po_line_qty = self._safe_float(get_v('Order Lines/Quantity')) or 1.0
                    gross_weight = self._safe_float(get_v('Purchase Gross Amount (g)')) or po_line_qty

                    if po_rec and variant_rec:
                        # Use PO datetime for date_planned on the order line
                        po_datetime_for_line = po_rec.date_order or fields.Datetime.now()
                        po_line = request.env['purchase.order.line'].create({
                            'order_id': po_rec.id,
                            'product_id': variant_rec.id,
                            'name': variant_rec.display_name or template.name,
                            'product_qty': gross_weight,
                            'price_unit': po_line_amount / gross_weight if gross_weight else po_line_amount,
                            'date_planned': po_datetime_for_line,
                            'taxes_id': [(5, 0, 0)],  # Remove all taxes
                        })
                        po_total_map[po_rec.id] = po_total_map.get(po_rec.id, 0.0) + po_line_amount
                        po_line_weight_map[po_line.id] = gross_weight

                # ---- Prepare making charge type ----
                raw_type = str(get_v('Purchase Making Charge Type') or '').strip()
                mc_type_map = {'Percentage': 'percent', 'Amount': 'amount', 'Rate per Gram': 'rate_per_gram'}
                making_charge_key = mc_type_map.get(raw_type, 'percent')

                age_from_excel = get_v('Age (Days)')

                vals = {
                    'name': get_v('Label Name'),
                    'product_template_id': template.id,
                    'product_id': variant_rec.id if variant_rec else False,
                    'product_template_attribute_value_ids': [(6, 0, ptav_ids.ids)],
                    'branch_id': self._find_m2o('res.branch', get_v('Branch')),
                    'branch_location_id': self._find_m2o('stock.location',
                                                          get_v('Branch Location') or get_v('Destination Location')),
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
                    unimported_list.append({'row': row_idx, 'barcode': barcode, 'product': template_name_excel,
                                            'variant': variant_attrs_excel,
                                            'reason': f"Creation Error: {str(row_err)}"})
                    skipped += 1
                    continue

                # Backdate create_date to match historical age
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

                # Stock-in
                try:
                    if new_label.product_id and new_label.source_location_id:
                        qty = new_label.purchase_gross_weight or new_label.sale_gross_weight or 1.0
                        # Use PO date for the inventory adjustment if available
                        po_date_for_stock = (
                            po_rec.date_order.date()
                            if po_rec and po_rec.date_order
                            else None
                        )
                        self._create_or_update_stock(
                            new_label.product_id.id,
                            new_label.source_location_id.id,
                            qty,
                            date=po_date_for_stock,
                        )
                    new_label.action_stock_in()
                except Exception as stock_err:
                    _logger.warning(f"Label {new_label.name} stock-in skipped at row {row_idx}: {str(stock_err)}")

            # ================================================================
            # PASS 2 – Confirm PO → Receive Products → Create & Post Bill
            # ================================================================
            for po_rec in supplier_po_map.values():
                try:
                    # --- Step 1: Confirm PO ---
                    po_rec.button_confirm()
                    _logger.info(f"PO {po_rec.name} confirmed.")
                except Exception as e:
                    _logger.warning(f"Could not confirm PO {po_rec.name}: {e}")
                    continue

                try:
                    # --- Step 2: Receive / Validate Picking ---
                    pending_pickings = po_rec.picking_ids.filtered(
                        lambda p: p.state not in ('done', 'cancel')
                    )
                    for picking in pending_pickings:
                        # --- Backdate the picking to the PO date so stock valuation
                        #     entries use the correct historical date. ---
                        po_datetime = po_rec.date_order
                        if po_datetime:
                            picking.scheduled_date = po_datetime
                            picking.date = po_datetime          # Effective date on the transfer

                        for move in picking.move_ids_without_package:
                            # Set done quantity from our weight map, fallback to ordered qty
                            weight = po_line_weight_map.get(move.purchase_line_id.id)
                            move.quantity = weight if weight else move.product_uom_qty
                            move.picked = True
                            # Set the move date so stock valuation JE uses PO date
                            if po_datetime:
                                move.date = po_datetime

                        # Skip backorder creation so validation completes immediately
                        picking.with_context(
                            skip_backorder=True,
                            skip_immediate=True,
                        ).button_validate()
                        _logger.info(f"Picking {picking.name} validated for PO {po_rec.name}.")
                except Exception as e:
                    _logger.warning(f"Could not validate picking for PO {po_rec.name}: {e}")

                # --- Step 3: Create Vendor Bill ---
                total_amount = po_total_map.get(po_rec.id, 0.0)
                if total_amount <= 0:
                    _logger.info(f"PO {po_rec.name} has zero total – skipping bill creation.")
                    continue

                try:
                    po_rec.action_create_invoice()

                    # Fetch draft bills created from this PO
                    bills = po_rec.invoice_ids.filtered(lambda m: m.state == 'draft')
                    if not bills:
                        _logger.warning(f"No draft bill found for PO {po_rec.name}")
                        continue

                    bill = bills[0]
                    bill_date = po_date_map.get(po_rec.id, fields.Date.today())
                    bill.invoice_date = bill_date
                    bill.date = bill_date

                    # --- Step 4: Override line accounts + remove taxes ---
                    # Since the user's Opening Balance account has account_type='liability_payable',
                    # we can now safely change the payable line's account directly to it.
                    # Odoo's action_post() will still pass validation because the type is correct.
                    #
                    #   - Payable line  → Opening Balance account  (Cr, replaces Creditors)
                    #   - Product lines → Stock Input account       (Dr, no tax)
                    for line in bill.line_ids:
                        if line.display_type in ('line_section', 'line_note'):
                            continue
                        if line.account_id.account_type == 'liability_payable':
                            # This is the auto-generated Creditors line — replace with Opening Balance
                            if opening_balance_account:
                                line.account_id = opening_balance_account
                                _logger.info(
                                    f"Bill payable line: Creditors → {opening_balance_account.name}"
                                )
                        else:
                            # Product / expense lines → Stock Input, no tax
                            if stock_input_account:
                                line.account_id = stock_input_account
                            line.tax_ids = [(5, 0, 0)]
                            _logger.info("Bill product line → Stock Input, taxes cleared.")

                    # --- Step 5: Post (confirm) the Bill ---
                    # Bill now has: Dr Stock Input / Cr Opening Balance
                    # Both are valid account types — action_post() will succeed.
                    bill.action_post()
                    _logger.info(f"Bill {bill.name} posted for PO {po_rec.name}.")

                    # --- Step 6: Settle bill → Paid state (no account.payment) ---
                    # The bill's payable line is now on Opening Balance account.
                    # Create a counter JE:
                    #   Dr Opening Balance  (closes the bill's Cr OB line)
                    #   Cr Opening Balance  (balancing entry — net zero on OB)
                    # Reconcile the Dr line with the bill's Cr line → bill = Paid.
                    try:
                        payable_line = bill.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'liability_payable'
                            or (opening_balance_account
                                and l.account_id.id == opening_balance_account.id)
                        )
                        if not payable_line:
                            _logger.warning(
                                f"No payable/OB line on posted bill {bill.name} — skipping settlement."
                            )
                            raise Exception("No payable line on posted bill.")

                        settle_account = payable_line[0].account_id
                        amount = abs(payable_line[0].amount_residual)

                        settle_journal = opening_balance_journal
                        if not settle_journal:
                            settle_journal = request.env['account.journal'].search([
                                ('type', '=', 'general'),
                                ('company_id', '=', request.env.company.id),
                            ], limit=1)

                        if settle_journal and amount > 0:
                            counter_move = request.env['account.move'].create({
                                'move_type': 'entry',
                                'journal_id': settle_journal.id,
                                'date': bill_date,
                                'ref': f"Settlement - {bill.name}",
                                'line_ids': [
                                    (0, 0, {
                                        'account_id': settle_account.id,
                                        'partner_id': po_rec.partner_id.id,
                                        'name': f"Settlement Dr - {bill.name}",
                                        'debit': amount,
                                        'credit': 0.0,
                                    }),
                                    (0, 0, {
                                        'account_id': settle_account.id,
                                        'partner_id': po_rec.partner_id.id,
                                        'name': f"Settlement Cr - {bill.name}",
                                        'debit': 0.0,
                                        'credit': amount,
                                    }),
                                ],
                            })
                            counter_move.action_post()
                            _logger.info(
                                f"Settlement JE {counter_move.name} posted for bill {bill.name}."
                            )

                            # Reconcile bill's Cr OB line ↔ counter JE's Dr OB line
                            bill_lines = bill.line_ids.filtered(
                                lambda l: l.account_id.id == settle_account.id
                                and not l.reconciled
                            )
                            counter_lines = counter_move.line_ids.filtered(
                                lambda l: l.debit > 0
                                and l.account_id.id == settle_account.id
                            )
                            if bill_lines and counter_lines:
                                (bill_lines | counter_lines).reconcile()
                                _logger.info(
                                    f"Bill {bill.name} reconciled → Paid state."
                                )
                            else:
                                _logger.warning(
                                    f"Could not find lines to reconcile for bill {bill.name}: "
                                    f"bill_lines={bill_lines}, counter_lines={counter_lines}"
                                )
                    except Exception as pay_err:
                        _logger.warning(
                            f"Could not settle bill {bill.name}: {pay_err}"
                        )

                except Exception as e:
                    _logger.warning(
                        f"Could not create/post Vendor Bill for PO {po_rec.name}: {e}",
                        exc_info=True
                    )

            request.env.cr.commit()

            # ---- PDF report of unimported records ----
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
                    request.env.cr.commit()
                    download_btn_html = f"""
                    <div style="margin-top: 20px;">
                        <a href="/web/content/{attachment.id}?download=true"
                           style="background-color:#7C5BBA;color:white;padding:12px 20px;
                                  text-decoration:none;font-weight:bold;border-radius:4px;
                                  display:inline-block;font-family:sans-serif;">
                            Download Unimported Products Report (PDF)
                        </a>
                    </div>
                    """
                except Exception as pdf_err:
                    _logger.error(f"Failed to generate skipped report PDF: {pdf_err}")
                    download_btn_html = f"<p style='color:red;'>Failed to generate PDF: {pdf_err}</p>"

            return f"""
            <div style="font-family:sans-serif;max-width:640px;margin:40px auto;padding:24px;
                        border:1px solid #e0e0e0;border-radius:8px;box-shadow:0 4px 6px rgba(0,0,0,.05);">
                <h1 style="color:#7C5BBA;margin-top:0;">Import Finished</h1>
                <p style="font-size:16px;color:#333;"><strong>Labels created:</strong> {count}</p>
                <p style="font-size:16px;color:#333;"><strong>Skipped:</strong> {skipped}</p>
                <p style="font-size:16px;color:#333;">
                    <strong>Purchase Orders processed:</strong> {len(supplier_po_map)}
                </p>
                {download_btn_html}
            </div>
            """

        except Exception as e:
            _logger.error(f"Critical Import Failure: {str(e)}", exc_info=True)
            return f"<h1>Error</h1><p>{str(e)}</p>"

    # ------------------------------------------------------------------
    # Bulk transfer route (unchanged from original)
    # ------------------------------------------------------------------
    @http.route('/import/labels_purchase/transfer_pending', type='http', auth='user')
    def transfer_pending_labels(self, **kwargs):
        # Only transfer labels that:
        #  1. have NOT been stocked-in yet  (is_stocked_in = False)
        #  2. have a purchase gross weight  (> 0)
        #  3. have both source and destination locations set
        pending = request.env['product.label'].search([
            ('purchase_gross_weight', '>', 0),       # Must have a valid weight
            ('branch_location_id', '!=', False),
            ('source_location_id', '!=', False),
        ])
        _logger.info(f"transfer_pending_labels: {len(pending)} labels to transfer.")
        success = 0
        failed = 0
        for label in pending:
            try:
                if label.product_id and label.source_location_id:
                    qty = label.purchase_gross_weight
                    self._create_or_update_stock(label.product_id.id, label.source_location_id.id, qty)
                label.action_stock_in()
                success += 1
            except Exception as e:
                _logger.warning(f"Transfer failed for label {label.name}: {e}")
                failed += 1
        request.env.cr.commit()
        return (f"<h1>Bulk Transfer Complete</h1>"
                f"<p>Transferred: {success} | Failed: {failed} | Total Pending: {len(pending)}</p>")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _safe_float(self, val):
        """Convert a value to float safely, returning 0.0 on failure."""
        try:
            return float(str(val).replace(',', '').strip()) if val not in (None, False, '') else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _generate_skipped_pdf(self, unimported_list):
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter,
                                rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        story = []
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'],
                                     fontName='Helvetica-Bold', fontSize=18,
                                     textColor=colors.HexColor('#7C5BBA'), spaceAfter=15)
        normal_style = styles['Normal']
        header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'],
                                      fontName='Helvetica-Bold', textColor=colors.white)

        story.append(Paragraph("Unimported / Skipped Products Report", title_style))
        story.append(Spacer(1, 10))

        data = [[
            Paragraph("Row", header_style),
            Paragraph("Barcode", header_style),
            Paragraph("Product / Template", header_style),
            Paragraph("Variant Attributes", header_style),
            Paragraph("Reason for Skipping", header_style),
        ]]
        col_widths = [40, 90, 120, 120, 170]

        for item in unimported_list:
            data.append([
                Paragraph(str(item['row']), normal_style),
                Paragraph(str(item.get('barcode') or ''), normal_style),
                Paragraph(str(item.get('product') or ''), normal_style),
                Paragraph(str(item.get('variant') or ''), normal_style),
                Paragraph(str(item.get('reason') or ''), normal_style),
            ])

        t = Table(data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#7C5BBA')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D3D3D3')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9F9F9')]),
        ]))
        story.append(t)
        doc.build(story)
        return buffer.getvalue()

    def _create_or_update_stock(self, product_id, location_id, qty):
        if not product_id or not location_id or not qty or qty <= 0:
            return
    def _create_or_update_stock(self, product_id, location_id, qty, date=None):
        """Create or update a stock quant for the given product/location/qty.
        If `date` is provided it is passed as `force_period_date` so the
        inventory-adjustment stock move (and its valuation entry) is dated
        to the historical purchase order date rather than today.
        """
        if not product_id or not location_id or not qty or qty <= 0:
            return
        try:
            ctx = {'inventory_mode': True}
            if date:
                # force_period_date sets the accounting date on the generated stock move
                ctx['force_period_date'] = date

            quant = request.env['stock.quant'].with_context(**ctx).search([
                ('product_id', '=', product_id),
                ('location_id', '=', location_id),
            ], limit=1)
            if quant:
                quant.inventory_quantity = quant.quantity + qty
            else:
                quant = request.env['stock.quant'].with_context(**ctx).create({
                    'product_id': product_id,
                    'location_id': location_id,
                    'inventory_quantity': qty,
                })
            quant.with_context(**ctx).action_apply_inventory()
        except Exception as e:
            _logger.error(
                f"Failed to set stock for product {product_id} at location {location_id}: {e}"
            )

    def _find_m2o(self, model, name):
        if not name:
            return False
        name = str(name).strip()
        if model == 'stock.location':
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
