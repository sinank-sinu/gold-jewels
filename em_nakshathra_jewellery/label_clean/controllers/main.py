from odoo import http, fields
from odoo.http import request
import io
import logging

try:
    import openpyxl
except ImportError:
    pass

_logger = logging.getLogger(__name__)

class LabelCleanController(http.Controller):

    @http.route('/label_clean/run', type='http', auth='user')
    def run_cleanup_form(self, **kwargs):
        html = """
        <html>
            <head>
                <title>Label Clean - Upload Excel</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background-color: #f4f6f9; color: #333; }
                    .container { max-width: 650px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
                    h1 { color: #017e84; margin-top: 0; }
                    p { line-height: 1.6; color: #555; }
                    .file-input { margin: 25px 0; padding: 20px; border: 2px dashed #017e84; border-radius: 6px; text-align: center; background: #f8fafb; }
                    input[type=file] { font-size: 15px; }
                    button { background-color: #017e84; color: white; padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; font-weight: 600; width: 100%; transition: background-color 0.2s; }
                    button:hover { background-color: #015e62; }
                    .info-box { background: #e8f4f8; border-left: 4px solid #017e84; padding: 12px 16px; margin-bottom: 20px; border-radius: 0 4px 4px 0; font-size: 14px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Clean & Insert Sale Order Lines</h1>
                    <div class="info-box">
                        This tool will <b>delete only the unlabeled lines</b> from each confirmed Sale Order and <b>insert fresh lines</b> with the exact values and labels from your uploaded Excel sheet.
                    </div>
                    <form action="/label_clean/upload" method="POST" enctype="multipart/form-data">
                        <div class="file-input">
                            <input type="file" name="file" accept=".xlsx" required/>
                        </div>
                        <button type="submit">Upload and Process</button>
                    </form>
                </div>
            </body>
        </html>
        """
        return html

    def _adjust_stock_quant(self, env, product, location, qty):
        """Directly adjust stock_quant quantity at the specified branch location
        without creating artificial 'Product Quantity Updated' inventory adjustment stock moves."""
        if not product or not location or not qty:
            return
        try:
            env['stock.quant'].sudo()._update_available_quantity(product, location, quantity=qty)
        except Exception as ex:
            _logger.warning("Could not update quant via _update_available_quantity for product %s at %s: %s. Using direct quant write.", product.id, location.id, ex)
            quant = env['stock.quant'].sudo().search([
                ('product_id', '=', product.id),
                ('location_id', '=', location.id)
            ], limit=1)
            if quant:
                quant.sudo().write({'quantity': quant.quantity + qty})
            else:
                env['stock.quant'].sudo().create({
                    'product_id': product.id,
                    'location_id': location.id,
                    'quantity': qty,
                })

    @http.route('/label_clean/upload', type='http', auth='user', methods=['GET', 'POST'], csrf=False)
    def handle_upload(self, file=None, **kwargs):
        if request.httprequest.method == 'GET' or not file:
            return request.redirect('/label_clean/run')
            
        env = kwargs.get('env')
        if not env:
            try:
                env = request.env
            except Exception:
                return "Error: Odoo environment not available."

        try:
            file_data = file.read()
            wb = openpyxl.load_workbook(filename=io.BytesIO(file_data), data_only=True)
            ws = wb.active
        except Exception as e:
            return f"Error reading Excel file: {str(e)}"
            
        headers = [cell.value for cell in ws[1]]
        
        def _safe_float(val):
            try:
                return float(val) if val is not None else 0.0
            except (ValueError, TypeError):
                return 0.0

        def _str(val):
            return str(val).strip() if val is not None else ''

        # Group rows by Vou No
        try:
            vou_no_idx = headers.index('Vou No')
        except ValueError:
            return "Error: Could not find 'Vou No' column in the Excel file."

        rows_by_voucher = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            vou_val = row[vou_no_idx]
            if vou_val:
                vou_key = _str(vou_val)
                rows_by_voucher.setdefault(vou_key, []).append(dict(zip(headers, row)))

        total_orders_processed = 0
        total_unlabeled_deleted = 0
        total_new_lines_created = 0
        error_logs = []
        success_logs = []
        BATCH_SIZE = 100

        for loop_idx, (vou_no, vou_rows) in enumerate(rows_by_voucher.items(), start=1):
            try:
                # 1. Find Sale Order
                order = env['sale.order'].sudo().search([
                    '|', '|',
                    ('name', '=', vou_no),
                    ('origin', '=', vou_no),
                    ('client_order_ref', '=', vou_no)
                ], limit=1)

                if not order:
                    error_logs.append(f"Sale Order '{vou_no}' not found in database.")
                    continue

                # 2. Check for unlabeled lines
                unlabeled_lines = order.order_line.filtered(lambda l: not l.label_id)
                if not unlabeled_lines:
                    success_logs.append(f"Voucher {vou_no} ({order.name}): All lines already have labels. No changes needed.")
                    continue

                total_orders_processed += 1
                unlabeled_count = len(unlabeled_lines)

                # 3. Collect old lines info, moves, and invoice lines for stock adjustments & relinking
                old_line_data = []
                for line in unlabeled_lines:
                    old_line_data.append({
                        'id': line.id,
                        'product': line.product_id,
                        'qty': line.product_uom_qty,
                        'move_ids': line.move_ids.ids,
                        'inv_line_ids': line.invoice_lines.ids,
                    })

                all_old_moves = []
                all_old_inv_lines = []
                for item in old_line_data:
                    all_old_moves.extend(item['move_ids'])
                    all_old_inv_lines.extend(item['inv_line_ids'])

                # 4. Determine branch location of the sale voucher
                branch_loc = None
                if hasattr(order, 'branch_location_id') and order.branch_location_id:
                    branch_loc = order.branch_location_id
                if not branch_loc:
                    for pick in order.picking_ids:
                        if pick.location_id and pick.location_id.usage == 'internal':
                            branch_loc = pick.location_id
                            break
                if not branch_loc and order.warehouse_id:
                    branch_loc = order.warehouse_id.lot_stock_id

                # Return old generic product stock back to the branch location directly in stock_quant (without creating 'Product Quantity Updated' adjustment moves)
                if branch_loc:
                    for item in old_line_data:
                        old_p = item['product']
                        qty = item['qty']
                        if old_p and qty > 0:
                            self._adjust_stock_quant(env, old_p, branch_loc, qty)

                # 5. Delete only the unlabeled lines from the sale order
                env.cr.execute("DELETE FROM sale_order_line WHERE id IN %s", (tuple(unlabeled_lines.ids),))
                order.invalidate_recordset(['order_line'])
                total_unlabeled_deleted += unlabeled_count

                # 6. Filter which Excel rows need to be inserted (avoid duplicating existing remaining labeled lines)
                remaining_lines = order.order_line
                accounted_rem_lines = set()
                used_label_ids = set(remaining_lines.mapped('label_id').ids)

                rows_to_insert = []
                for r in vou_rows:
                    lbl_no = _str(r.get('Label No'))
                    bc_no = _str(r.get('Barcode No'))
                    gross = _safe_float(r.get('Gross Wt.'))
                    prod_name = _str(r.get('Product Variant'))

                    matched_rem = None
                    for rem in remaining_lines:
                        if rem.id in accounted_rem_lines:
                            continue
                        if rem.label_id and (rem.label_id.name == lbl_no or rem.label_id.barcode == bc_no or rem.label_id.barcode == lbl_no):
                            matched_rem = rem
                            break
                        max_wt = max(rem.sale_gross_weight or 0.0, rem.product_uom_qty or 0.0, rem.net_weight or 0.0)
                        if abs(max_wt - gross) < 0.01:
                            if rem.product_id and (prod_name.lower() in rem.product_id.name.lower() or rem.product_id.name.lower() in prod_name.lower()):
                                matched_rem = rem
                                break

                    if matched_rem:
                        accounted_rem_lines.add(matched_rem.id)
                        continue
                    rows_to_insert.append(r)

                # 7. Insert the new lines from Excel
                inserted_for_order = 0
                for r in rows_to_insert:
                    lbl_no = _str(r.get('Label No'))
                    bc_no = _str(r.get('Barcode No'))
                    gross = _safe_float(r.get('Gross Wt.'))
                    net = _safe_float(r.get('Net Wt.'))
                    di_wt = _safe_float(r.get('Di. Wt.'))
                    st_wt = _safe_float(r.get('St. Wt.'))
                    metal_rate = _safe_float(r.get('Metal Rate'))
                    metal_amt = _safe_float(r.get('Metal Amt'))
                    mc_amt = _safe_float(r.get('MC'))
                    di_amt = _safe_float(r.get('Di Amt'))
                    st_amt = _safe_float(r.get('St Amt'))
                    other_charge = _safe_float(r.get('Other Charge'))
                    taxable_amt = _safe_float(r.get('Taxable Amt'))
                    prod_var_name = _str(r.get('Product Variant'))
                    carat = _str(r.get('Carat'))
                    tax_str = _str(r.get('Taxes'))

                    # Resolve Label (include inactive/sold labels)
                    label_obj = env['product.label'].with_context(active_test=False).sudo()
                    label = None
                    if lbl_no:
                        label = label_obj.search([
                            ('name', '=', lbl_no),
                            ('company_id', 'in', [order.company_id.id, False])
                        ], limit=1)
                    if not label and bc_no:
                        label = label_obj.search([
                            ('barcode', '=', bc_no),
                            ('company_id', 'in', [order.company_id.id, False])
                        ], limit=1)
                    if not label and lbl_no:
                        label = label_obj.search([
                            ('barcode', '=', lbl_no),
                            ('company_id', 'in', [order.company_id.id, False])
                        ], limit=1)
                    if not label and bc_no:
                        label = label_obj.search([
                            ('name', '=', bc_no),
                            ('company_id', 'in', [order.company_id.id, False])
                        ], limit=1)

                    # Fallback candidate search (latest first, including inactive)
                    if not label:
                        cand_domain = [
                            ('sale_gross_weight', '>=', gross - 0.01),
                            ('sale_gross_weight', '<=', gross + 0.01),
                            ('company_id', 'in', [order.company_id.id, False]),
                        ]
                        if order.branch_id:
                            cand_domain.append(('branch_id', '=', order.branch_id.id))
                        if prod_var_name:
                            cand_domain.append(('product_template_id.name', 'ilike', prod_var_name.split('(')[0].strip()))

                        candidates = label_obj.search(cand_domain, order='id desc')
                        for cand in candidates:
                            if cand.id not in used_label_ids:
                                label = cand
                                break

                    if label:
                        used_label_ids.add(label.id)

                    # Resolve Product
                    line_product = None
                    if label and label.product_id:
                        line_product = label.product_id
                    elif label and label.product_tmpl_id and label.product_tmpl_id.product_variant_id:
                        line_product = label.product_tmpl_id.product_variant_id
                    if not line_product and prod_var_name:
                        line_product = env['product.product'].sudo().search([
                            ('name', '=ilike', prod_var_name),
                            ('company_id', 'in', [order.company_id.id, False])
                        ], limit=1)

                    if not line_product:
                        error_logs.append(f"Voucher {vou_no}: Could not resolve product for item '{prod_var_name}' / label '{lbl_no}'.")
                        continue

                    # Resolve Purity
                    purity = None
                    if label and label.purity_id:
                        purity = label.purity_id
                    elif carat:
                        purity = env['gold.purity'].sudo().search([('name', 'ilike', carat)], limit=1)

                    # Resolve Taxes
                    taxes = env['account.tax']
                    if tax_str:
                        taxes = env['account.tax'].sudo().search([
                            ('name', 'ilike', tax_str),
                            ('type_tax_use', '=', 'sale'),
                            ('company_id', '=', order.company_id.id)
                        ], limit=1)
                    if not taxes:
                        taxes = line_product.taxes_id.filtered(lambda t: t.company_id.id in (order.company_id.id, False))

                    # Deduct new labeled product stock directly from the branch location in stock_quant (without creating 'Product Quantity Updated' adjustment moves)
                    if branch_loc and gross > 0:
                        self._adjust_stock_quant(env, line_product, branch_loc, -gross)

                    # Create new sale order line
                    price_unit_val = (taxable_amt / gross) if (gross and taxable_amt) else (metal_rate or 0.0)
                    new_line_vals = {
                        'order_id': order.id,
                        'product_id': line_product.id,
                        'label_id': label.id if label else False,
                        'purity_id': purity.id if purity else False,
                        'product_uom_qty': gross or 1.0,
                        'product_uom': line_product.uom_id.id,
                        'sale_gross_weight': gross,
                        'net_weight': net or gross,
                        'sale_stone_weight': st_wt,
                        'sale_diamond_weight_gm': di_wt,
                        'sale_stone_rate': st_amt,
                        'sale_diamond_rate': di_amt,
                        'other_weight_amount': other_charge,
                        'gold_rate': metal_rate,
                        'price_unit': price_unit_val,
                        'tax_id': [(6, 0, taxes.ids)] if taxes else [],
                    }
                    new_sol = env['sale.order.line'].with_company(order.company_id).sudo().create(new_line_vals)

                    # Immediately clean up auto-generated draft stock moves and pickings created by _action_launch_stock_rule
                    auto_moves = new_sol.move_ids.filtered(lambda m: m.id not in all_old_moves)
                    for am in auto_moves:
                        ap = am.picking_id
                        am.move_line_ids.sudo().unlink()
                        am.sudo().unlink()
                        if ap and not ap.move_ids and ap.state not in ('done', 'cancel'):
                            ap.sudo().unlink()

                    # Update metal amount, MC and subtotals
                    if metal_amt > 0:
                        env.cr.execute("UPDATE sale_order_line SET metal_amount = %s WHERE id = %s", (metal_amt, new_sol.id))
                        new_sol.invalidate_recordset(['metal_amount'])
                    if mc_amt > 0 and metal_amt > 0:
                        pct = (mc_amt / metal_amt) * 100.0
                        new_sol.sudo().write({'mc_percent_actual': pct})
                    if taxable_amt > 0:
                        env.cr.execute("UPDATE sale_order_line SET price_subtotal = %s, price_total = %s WHERE id = %s", 
                                                (taxable_amt, taxable_amt * 1.03, new_sol.id))
                        new_sol.invalidate_recordset(['price_subtotal', 'price_total'])

                    # Reassign picking stock move
                    if all_old_moves:
                        old_move_id = all_old_moves.pop(0)
                        env.cr.execute("""
                            UPDATE stock_move 
                            SET product_id = %s, sale_line_id = %s, product_uom_qty = %s, quantity = %s,
                                label_id = %s, purity_id = %s, grams = %s
                            WHERE id = %s
                        """, (line_product.id, new_sol.id, gross or 1.0, gross or 1.0,
                              label.id if label else None, purity.id if purity else None, gross or 1.0, old_move_id))
                        env.cr.execute("""
                            UPDATE stock_move_line 
                            SET product_id = %s, quantity = %s, quantity_product_uom = %s
                            WHERE move_id = %s
                        """, (line_product.id, gross or 1.0, gross or 1.0, old_move_id))

                    # Reassign posted invoice line in the same existing invoice
                    if all_old_inv_lines:
                        old_inv_line_id = all_old_inv_lines.pop(0)
                        env.cr.execute("""
                            INSERT INTO sale_order_line_invoice_rel (order_line_id, invoice_line_id)
                            VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                        """, (new_sol.id, old_inv_line_id))
                        env.cr.execute("""
                            UPDATE account_move_line
                            SET product_id = %s, name = %s, label_id = %s, purity_id = %s
                            WHERE id = %s
                        """, (line_product.id, line_product.display_name,
                              label.id if label else None, purity.id if purity else None, old_inv_line_id))

                    # Ensure line is marked fully delivered and invoiced
                    env.cr.execute("""
                        UPDATE sale_order_line
                        SET qty_delivered = %s,
                            qty_invoiced = %s,
                            qty_to_invoice = 0.0,
                            invoice_status = 'invoiced'
                        WHERE id = %s
                    """, (gross or 1.0, gross or 1.0, new_sol.id))

                    inserted_for_order += 1
                    total_new_lines_created += 1

                # Clean up any stray draft/assigned pickings created during line insertion
                stray_pickings = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
                for sp in stray_pickings:
                    sp.move_line_ids.sudo().unlink()
                    sp.move_ids.sudo().unlink()
                    sp.sudo().unlink()

                # Ensure all order lines have fully delivered and invoiced status
                for sol in order.order_line:
                    env.cr.execute("""
                        UPDATE sale_order_line
                        SET qty_delivered = product_uom_qty,
                            qty_invoiced = product_uom_qty,
                            qty_to_invoice = 0.0,
                            invoice_status = 'invoiced'
                        WHERE id = %s
                    """, (sol.id,))

                # Finalize order delivery and invoice status
                try:
                    order._compute_delivery_status()
                except Exception:
                    pass
                try:
                    order._compute_invoice_status()
                except Exception:
                    pass

                env.cr.execute("""
                    UPDATE sale_order
                    SET invoice_status = 'invoiced',
                        delivery_status = 'full'
                    WHERE id = %s
                """, (order.id,))

                order.invalidate_recordset()
                success_logs.append(f"Voucher {vou_no} ({order.name}): Deleted {unlabeled_count} unlabeled line(s) and inserted {inserted_for_order} new labeled line(s).")

            except Exception as e:
                env.cr.rollback()
                _logger.exception("Error processing voucher %s", vou_no)
                error_logs.append(f"Voucher {vou_no}: Error - {str(e)}")
                continue

            # Batch commit and ORM cache clearing every 100 vouchers
            if loop_idx % BATCH_SIZE == 0:
                env.cr.commit()
                env.invalidate_all()
                _logger.info("Label Clean: Processed and committed %s / %s vouchers (Updated %s orders)",
                             loop_idx, len(rows_by_voucher), total_orders_processed)

        # Final commit and cache clear for any remaining vouchers
        env.cr.commit()
        env.invalidate_all()
        _logger.info("Label Clean: Complete! Processed %s vouchers in total (%s orders updated)",
                     len(rows_by_voucher), total_orders_processed)

        # Format Results HTML
        result_html = f"""
        <html>
            <head>
                <title>Processing Results - Label Clean</title>
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background-color: #f4f6f9; color: #333; }}
                    .container {{ max-width: 750px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
                    h1 {{ color: #017e84; margin-top: 0; }}
                    .stats {{ display: flex; gap: 20px; margin: 25px 0; }}
                    .stat-box {{ flex: 1; background: #f8fafb; border: 1px solid #e1e5eb; padding: 15px; border-radius: 6px; text-align: center; }}
                    .stat-number {{ font-size: 24px; font-weight: bold; color: #017e84; }}
                    .stat-label {{ font-size: 13px; color: #6c757d; margin-top: 5px; }}
                    ul {{ line-height: 1.6; padding-left: 20px; }}
                    li {{ margin-bottom: 5px; }}
                    .error-text {{ color: #d9534f; }}
                    .success-text {{ color: #5cb85c; }}
                    a.btn {{ display: inline-block; background-color: #017e84; color: white; padding: 10px 20px; border-radius: 4px; text-decoration: none; font-weight: 600; margin-top: 20px; }}
                    a.btn:hover {{ background-color: #015e62; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>Processing Complete!</h1>
                    <div class="stats">
                        <div class="stat-box">
                            <div class="stat-number">{total_orders_processed}</div>
                            <div class="stat-label">Orders Updated</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-number">{total_unlabeled_deleted}</div>
                            <div class="stat-label">Unlabeled Lines Deleted</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-number">{total_new_lines_created}</div>
                            <div class="stat-label">New Labeled Lines Added</div>
                        </div>
                    </div>
        """

        if success_logs:
            result_html += "<h3>Activity Summary:</h3><ul class='success-text'>"
            for log in success_logs[:100]:
                result_html += f"<li>{log}</li>"
            if len(success_logs) > 100:
                result_html += f"<li><i>... and {len(success_logs) - 100} more vouchers processed successfully (check server logs for details).</i></li>"
            result_html += "</ul>"

        if error_logs:
            result_html += "<h3 class='error-text'>Warnings / Errors:</h3><ul class='error-text'>"
            for err in error_logs:
                result_html += f"<li>{err}</li>"
            result_html += "</ul>"

        result_html += """
                    <a class="btn" href="/label_clean/run">Upload Another File</a>
                </div>
            </body>
        </html>
        """
        return result_html
