import openpyxl
import logging
import base64
from io import BytesIO
import datetime

from odoo import http, fields
from odoo.http import request
from odoo.exceptions import UserError, ValidationError

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

_logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SALES sheet column indices  (0-based)
# A=0  Branch (unused – we read from col 0 as branch name)
# B=1  Vou No
# C=2  Party Name
# D=3  Vou Date
# E=4  Source Location
# F=5  Label No
# G=6  Barcode No
# H=7  Product Variant  (fallback if label not found)
# I=8  Salesman
# J=9  Carat (Purity)
# K=10 Pcs
# L=11 Gross Wt
# M=12 Net Wt
# N=13 Stone Wt
# O=14 Diamond Wt
# P=15 Metal Rate (gold_rate)
# Q=16 Metal Amt
# R=17 Stone Amt
# S=18 Other Charge
# T=19 Taxable Amt
# U=20 Tax%
# V=21 Tax Amt
# W=22 CGST Amt
# X=23 SGST Amt
# Y=24 UPI Ref 1
# Z=25 UPI Amt 1
# AA=26 UPI Ref 2
# AB=27 UPI Amt 2
# AC=28 Bank Ref
# AD=29 Bank Amt
# AE=30 Card Ref
# AF=31 Card Amt
# AG=32 Cash Amt
# AH=33 Scheme Amt
# AI=34 OG Amt
# AJ=35 Customer Refund (negative balance to pay back)
# ─────────────────────────────────────────────────────────────────────────────

# OG sheet columns  (0-based)
# A=0 Branch, B=1 Vou No (sale ref), C=2 Vou No, D=3 Item Name (product/purity fallback)
# E=4 Carat, F=5 Gross Wt, G=6 Net Wt, H=7 Stone Wt, I=8 (fine?), J=9 Metal Rate, K=10 Amount
# L=11 Branch Location

# GOLD SCHEME sheet columns (0-based)
# A=0 Branch, B=1 Customer, C=2 Vou No (sale ref), D=3 Ticket No, E=4 Amount


def _flt(val, default=0.0):
    try:
        return float(val or default)
    except Exception:
        return default


def _str(val):
    return str(val).strip() if val is not None else ''


class SaleImportController(http.Controller):

    @http.route('/import/sales_migration/form', type='http', auth='user')
    def import_form(self, **kwargs):
        html = """
        <!DOCTYPE html><html><head><title>Import Sales Data</title>
        <style>
            body{font-family:sans-serif;margin:40px;background:#f4f6f9;}
            .container{max-width:800px;margin:auto;background:white;padding:20px;border-radius:8px;box-shadow:0 4px 6px rgba(0,0,0,.1);}
            h2{color:#333;} .btn{background:#7C5BBA;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;font-size:16px;}
            .btn:hover{background:#5c438f;} input[type="file"]{margin:20px 0;}
            .instructions{font-size:14px;color:#555;margin-bottom:20px;}
        </style></head><body><div class="container">
        <h2>Import Sales (Full Lifecycle)</h2>
        <div class="instructions"><p>Upload the Excel (.xlsx) file. The system will:</p>
        <ul><li>Create Sale Orders (with Salesman, Branch, Label, Purity, Gold Rate, Taxes)</li>
        <li>Apply Old Gold (from OG sheet)</li><li>Apply Scheme (from GOLD SCHEME sheet)</li>
        <li>Confirm order, validate delivery</li>
        <li>Create & post Customer Invoice</li>
        <li>Register UPI / Bank / Card / Cash payments with branch journals & references</li>
        <li>Create Customer Refund payment if balance is negative</li>
        </ul></div>
        <form action="/import/sales_migration/process" method="POST" enctype="multipart/form-data">
            <input type="hidden" name="csrf_token" value="{csrf_token}"/>
            <input type="file" name="file" accept=".xlsx" required="1"/>
            <button type="submit" class="btn">Import Data</button>
        </form></div></body></html>
        """.replace("{csrf_token}", request.csrf_token())
        return html

    @http.route('/import/sales_migration/process', type='http', auth='user', methods=['POST'], csrf=True)
    def import_process(self, file, **kwargs):
        if not file:
            return "<h1>Error</h1><p>No file uploaded.</p>"
        try:
            wb = openpyxl.load_workbook(file, data_only=True)
            sheet = wb.active

            success_count = 0
            error_log = []
            skipped_list = []

            # ── Pre-parse OG sheet ──────────────────────────────────────────
            # OG columns: [0]=Date [1]=Customer [2]=Sales Vou No [3]=Purchase Vou No
            #             [4]=Item Name [5]=Carat [6]=Gross Wt [7]=Net Wt [8]=Di Wt
            #             [9]=Metal Rate [10]=Amount [11]=Branch Location
            og_data = {}  # keyed by sales sheet vou_no
            if 'OG' in wb.sheetnames:
                for row in wb['OG'].iter_rows(min_row=2, values_only=True):
                    if not any(row):
                        continue
                    vou = _str(row[2])   # col C = Sales Voucher No (matches SALES col B)
                    if vou:
                        if vou not in og_data:
                            og_data[vou] = []
                        og_data[vou].append({
                            'item_name':     _str(row[4]),
                            'carat':         _str(row[5]),
                            'gross_wt':      _flt(row[6]),
                            'net_wt':        _flt(row[7]),
                            'di_wt':         _flt(row[8]),
                            'di_amt':        _flt(row[9]),
                            'metal_rate':    _flt(row[10]),
                            'amount':        _flt(row[11]),
                            'branch_location': _str(row[12]) if len(row) > 12 else '',
                        })

            # ── Pre-parse GOLD SCHEME sheet ─────────────────────────────────
            # SCHEME columns: [0]=Date [1]=Customer [2]=Voucher No [3]=Ticket No [4]=Amount
            scheme_data = {}  # keyed by sales sheet vou_no
            for sname in ('GOLD SCHEME', 'GOLD_SCHEME', 'GoldScheme', 'Scheme'):
                if sname in wb.sheetnames:
                    for row in wb[sname].iter_rows(min_row=2, values_only=True):
                        if not any(row):
                            continue
                        vou = _str(row[2])  # col C = Voucher No (matches SALES col B)
                        if vou:
                            scheme_data[vou] = {
                                'customer':  _str(row[1]),
                                'ticket_no': _str(row[3]),
                                'amount':    _flt(row[4]),
                            }
                    break

            # ── Group SALES rows by Vou No ───────────────────────────────────
            sales_data = {}
            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                if not any(row):
                    continue
                vou_no = _str(row[1])
                if not vou_no:
                    continue
                if vou_no not in sales_data:
                    sales_data[vou_no] = []
                sales_data[vou_no].append((row_idx, row))
                
            # ── Process each Vou No ──────────────────────────────────────────
            for vou_no, rows in sales_data.items():
                try:
                    with request.env.cr.savepoint():
                        self._process_sale_voucher(
                            vou_no, rows, og_data, scheme_data,
                            skipped_list, error_log
                        )
                    success_count += 1
                except Exception as e:
                    error_log.append(f"Voucher {vou_no}: {e}")
                    _logger.exception("Voucher %s failed", vou_no)

            request.env.cr.commit()
            return self._build_result_html(success_count, skipped_list, error_log)

        except Exception as e:
            return f"<h1 style='color:red'>Fatal Error</h1><p>{e}</p>"

    # ─────────────────────────────────────────────────────────────────────────
    def _process_sale_voucher(self, vou_no, rows, og_data, scheme_data, skipped_list, error_log):
        env = request.env

        # ── 1. Parse Header from first row ───────────────────────────────────
        first_row_idx, hdr_row = rows[0]
        
        branch_name       = _str(hdr_row[0])
        cust_name         = _str(hdr_row[2]) or 'Unknown'
        date_val          = hdr_row[3]
        source_loc_name   = _str(hdr_row[4])
        salesman_name     = _str(hdr_row[8])

        if isinstance(date_val, (datetime.datetime, datetime.date)):
            order_date = date_val
        else:
            order_date = fields.Datetime.now()

        # ── 2. Header Lookups ─────────────────────────────────────────────────
        branch = env['res.branch'].search([('name', 'ilike', branch_name)], limit=1) if branch_name else env['res.branch']

        partner = env['res.partner'].search([('name', '=', cust_name)], limit=1)
        if not partner:
            partner = env['res.partner'].create({'name': cust_name})

        salesman = env['res.users'].search([('name', 'ilike', salesman_name)], limit=1) if salesman_name else env['res.users']
        if salesman_name and not salesman:
            try:
                salesman = env['res.users'].sudo().create({
                    'name': salesman_name,
                    'login': salesman_name.strip().lower().replace(' ', '_') + '@generated.local',
                })
            except Exception as e:
                _logger.warning("Voucher %s: Could not create salesman %s: %s", vou_no, salesman_name, e)

        source_loc = env['stock.location']
        if source_loc_name:
            source_loc = env['stock.location'].search([('complete_name', 'ilike', source_loc_name), ('usage', '=', 'internal')], limit=1)
            if not source_loc:
                source_loc = env['stock.location'].search([('name', 'ilike', source_loc_name), ('usage', '=', 'internal')], limit=1)
        if not source_loc and branch:
            source_loc = branch.branch_location_id

        # ── 3. Build Sale Order ───────────────────────────────────────────────
        order_vals = {
            'partner_id': partner.id,
            'date_order': order_date,
            'origin': vou_no,
        }
        if branch:
            order_vals['branch_id'] = branch.id
            warehouse = env['stock.warehouse'].sudo().search([
                ('branch_id', '=', branch.id),
                ('company_id', '=', env.company.id),
            ], limit=1)
            if not warehouse:
                warehouse = env['stock.warehouse'].sudo().search([
                    ('company_id', '=', env.company.id),
                ], limit=1)
            if warehouse:
                order_vals['warehouse_id'] = warehouse.id
        if salesman:
            order_vals['user_id'] = salesman.id
        if source_loc:
            order_vals['branch_location_id'] = source_loc.id

        # Find max header-level amounts across all rows
        og_amt = max([_flt(r[35]) if len(r) > 35 else 0.0 for idx, r in rows])
        scheme_amt = max([_flt(r[34]) if len(r) > 34 else 0.0 for idx, r in rows])
        
        # Override with amounts from OG/Scheme sheets if present
        og_infos = og_data.get(vou_no, [])
        if og_infos:
            og_amt_from_sheet = sum([info.get('amount', 0.0) for info in og_infos])
            if og_amt_from_sheet > 0:
                og_amt = og_amt_from_sheet
            
        sch_info = scheme_data.get(vou_no, {})
        if sch_info and sch_info.get('amount', 0.0) > 0:
            scheme_amt = sch_info.get('amount', 0.0)
        
        if og_amt > 0:
            order_vals['has_old_gold'] = True

        order = env['sale.order'].create(order_vals)

        # ── 4. Process Order Lines ────────────────────────────────────────────
        for row_idx, row in rows:
            product_var_name  = _str(row[5])
            label_ref         = _str(row[6])
            purity_name       = _str(row[9])
            gross_wt          = _flt(row[11])
            diamond_wt        = _flt(row[13])
            stone_wt          = _flt(row[14])
            metal_rate        = _flt(row[15])
            metal_amt         = _flt(row[16]) if len(row) > 16 else 0.0
            mc_amt            = _flt(row[17]) if len(row) > 17 else 0.0
            diamond_amt       = _flt(row[18]) if len(row) > 18 else 0.0
            stone_amt         = _flt(row[19]) if len(row) > 19 else 0.0
            other_charge      = _flt(row[20]) if len(row) > 20 else 0.0

            label = env['product.label']
            if label_ref:
                label = env['product.label'].search([('name', '=', label_ref)], limit=1)
                if not label:
                    label = env['product.label'].search([('barcode', '=', label_ref)], limit=1)
            if label_ref and not label:
                skipped_list.append({'row': row_idx, 'customer': cust_name, 'label': label_ref, 'reason': 'Label not found'})

            purity = env['gold.purity']
            if purity_name:
                purity = env['gold.purity'].search([('name', 'ilike', purity_name)], limit=1)
            if not purity and label:
                purity = label.purity_id

            line_product = env['product.product']
            if label:
                if label.product_id:
                    line_product = label.product_id
                elif label.product_tmpl_id:
                    variant = label.product_tmpl_id.product_variant_id
                    if variant:
                        line_product = variant

            if not line_product and product_var_name:
                line_product = env['product.product'].search([('name', 'ilike', product_var_name)], limit=1)
                if not line_product:
                    line_product = env['product.product'].search([('display_name', 'ilike', product_var_name)], limit=1)

            if line_product:
                if label and not label.product_id and line_product:
                    try:
                        label.sudo().write({'product_id': line_product.id})
                    except Exception:
                        pass

                taxes = line_product.taxes_id.filtered(lambda t: t.company_id == env.company)
                line_vals = {
                    'order_id': order.id,
                    'product_id': line_product.id,
                    'label_id': label.id if label else False,
                    'purity_id': purity.id if purity else False,
                    'product_uom_qty': gross_wt or (label.sale_gross_weight if label else 0) or 1.0,
                    'product_uom': line_product.uom_id.id,
                    'price_unit': 0.0,
                    'sale_stone_weight': stone_wt or (label.sale_stone_weight if label else 0),
                    'sale_stone_weight_ct': label.sale_stone_weight_ct if label else 0,
                    'sale_diamond_weight_gm': diamond_wt or (label.sale_diamond_weight_gm if label else 0),
                    'sale_diamond_weight_ct': label.sale_diamond_weight_ct if label else 0,
                    'sale_stone_rate': stone_amt or (label.sale_stone_rate if label else 0),
                    'sale_diamond_rate': diamond_amt or (label.sale_diamond_rate if label else 0),
                    'other_weight_amount': other_charge,
                    'tax_id': [(6, 0, taxes.ids)] if taxes else [],
                }
                
                line = env['sale.order.line'].sudo().create(line_vals)
                
                if hasattr(line, '_onchange_label_id'):
                    line._onchange_label_id()
                
                line_updates = {}
                if metal_rate > 0:
                    line_updates['gold_rate'] = metal_rate
                    
                target_metal = metal_amt if (len(row) > 16 and row[16] is not None) else (metal_rate * gross_wt if metal_rate else 0)
                
                if len(row) > 17 and row[17] is not None:
                    # we must set mc_percent_actual because mc_amount_actual is a non-stored compute
                    if target_metal > 0:
                        pct = (mc_amt / target_metal) * 100.0
                        line_updates['mc_percent_actual'] = pct
                
                if line_updates:
                    line.sudo().write(line_updates)
                    
                # Force metal_amount via SQL if provided in excel, as it's a stored compute field without inverse
                if len(row) > 16 and row[16] is not None:
                    env.cr.execute("UPDATE sale_order_line SET metal_amount = %s WHERE id = %s", (metal_amt, line.id))
                    line.invalidate_recordset(['metal_amount'])

                if hasattr(line, '_compute_subtotal'):
                    try: line._compute_subtotal()
                    except Exception: pass
                if hasattr(line, '_compute_price_unit'):
                    try: line._compute_price_unit()
                    except Exception: pass
                try:
                    line.flush_recordset(['price_subtotal', 'price_subtotal_actual', 'price_unit'])
                except Exception: pass
            
        # ── 5. Apply Old Gold ────────────────────────────────────────────────
        og_branch_loc_final = source_loc
        if og_amt > 0:
            og_infos = og_data.get(vou_no, [])
            if not og_infos:
                og_infos = [{'amount': og_amt}]
            
            for og_info in og_infos:
                amt = og_info.get('amount', 0.0)
                if amt <= 0:
                    continue
                first_purity_name = _str(hdr_row[9])
                og_purity_name = og_info.get('carat', '') or first_purity_name
    
                og_purity = env['gold.purity']
                if og_purity_name:
                    og_purity = env['gold.purity'].search([('name', 'ilike', og_purity_name)], limit=1)
                if not og_purity and order.order_line:
                    og_purity = order.order_line[0].purity_id
                if not og_purity:
                    og_purity = env['gold.purity'].search([], limit=1)
    
                if not og_purity:
                    _logger.warning("Voucher %s: No purity found for OG – skipping OG line", vou_no)
                    continue
                
                og_gross = og_info.get('gross_wt', 0.0)
                og_net   = og_info.get('net_wt', 0.0)
                og_stone = og_info.get('stone_wt', 0.0)
                og_rate  = og_info.get('metal_rate', 0.0)

                if og_rate <= 0:
                    og_rate = amt / og_net if og_net > 0 else 0.0

                og_branch_loc_name = og_info.get('branch_location', '')
                og_branch_loc = env['stock.location']
                if og_branch_loc_name:
                    og_branch_loc = env['stock.location'].search([
                        ('complete_name', 'ilike', og_branch_loc_name),
                        ('usage', '=', 'internal'),
                    ], limit=1)
                if not og_branch_loc and source_loc:
                    og_branch_loc = source_loc
                if og_branch_loc:
                    og_branch_loc_final = og_branch_loc
                    order.branch_location_id = og_branch_loc.id

                env['sale.old.gold.line'].create({
                    'sale_id': order.id,
                    'purity_id': og_purity.id,
                    'gross_weight': og_gross or (amt / og_rate if og_rate else 0.0),
                    'stone_weight': og_stone,
                    'rate': og_rate,
                    'amount': amt,
                })
                
            try:
                order.with_context(skip_old_gold_amount_compute=True).action_apply_old_gold()
            except Exception as e:
                _logger.warning("Voucher %s: Old Gold apply failed: %s", vou_no, e)

        # ── 6. Apply Scheme ───────────────────────────────────────────────────
        if scheme_amt > 0:
            sch_info = scheme_data.get(vou_no, {})
            ticket_no = sch_info.get('ticket_no', '')
            existing_scheme = env['jewellery.scheme.enrollment'].search([
                ('partner_id', '=', partner.id),
                ('ticket_number', '=', ticket_no),
                ('state', '=', 'completed'),
                ('is_redeemed', '=', False),
            ], limit=1)
            if not existing_scheme and ticket_no:
                existing_scheme = env['jewellery.scheme.enrollment'].search([
                    ('partner_id', '=', partner.id),
                    ('ticket_number', '=', ticket_no),
                ], limit=1)

            if existing_scheme:
                order.apply_scheme = True
                order.active_scheme_id = existing_scheme.id
                try:
                    order.action_apply_scheme()
                except Exception as e:
                    _logger.warning("Voucher %s: Scheme apply failed: %s", vou_no, e)

        # ── 7. Confirm Order ──────────────────────────────────────────────────
        order.with_context(mail_notrack=True).action_confirm()

        # ── 8. Validate Delivery ──────────────────────────────────────────────
        for picking in order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
            if picking.picking_type_code == 'outgoing' and source_loc:
                picking.location_id = source_loc.id
                for move in picking.move_ids:
                    move.location_id = source_loc.id
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                if hasattr(move, 'picked'):
                    move.picked = True
            try:
                res = picking.with_context(skip_backorder=True, cancel_backorder=True).button_validate()
                if isinstance(res, dict):
                    model = res.get('res_model', '')
                    ctx = res.get('context', {})
                    if model == 'stock.immediate.transfer':
                        wiz = env['stock.immediate.transfer'].with_context(ctx).create({'pick_ids': [(4, picking.id)]})
                        wiz.process()
                    elif model == 'stock.backorder.confirmation':
                        wiz = env['stock.backorder.confirmation'].with_context(ctx).create({'pick_ids': [(4, picking.id)]})
                        wiz.process()
            except Exception as e:
                _logger.warning("Voucher %s: Delivery validate failed: %s", vou_no, e)

        # ── Validate Old Gold Delivery ────────────────────────────────────────
        if order.purchase_order_id:
            for picking in order.purchase_order_id.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                if og_branch_loc_final:
                    picking.location_dest_id = og_branch_loc_final.id
                    for move in picking.move_ids:
                        move.location_dest_id = og_branch_loc_final.id
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    if hasattr(move, 'picked'):
                        move.picked = True
                try:
                    res = picking.with_context(skip_backorder=True, cancel_backorder=True).button_validate()
                    if isinstance(res, dict):
                        model = res.get('res_model', '')
                        ctx = res.get('context', {})
                        if model == 'stock.immediate.transfer':
                            wiz = env['stock.immediate.transfer'].with_context(ctx).create({'pick_ids': [(4, picking.id)]})
                            wiz.process()
                        elif model == 'stock.backorder.confirmation':
                            wiz = env['stock.backorder.confirmation'].with_context(ctx).create({'pick_ids': [(4, picking.id)]})
                            wiz.process()
                except Exception as e:
                    _logger.warning("Voucher %s: Old Gold Delivery validate failed: %s", vou_no, e)

        # ── 9. Invoice ────────────────────────────────────────────────────────
        if not order.order_line:
            return

        invoice = order._create_invoices()
        if not invoice:
            return
            
        inv_vals = {}
        if order_date:
            inv_vals['invoice_date'] = order_date.date() if isinstance(order_date, datetime.datetime) else order_date
        if vou_no:
            inv_vals['ref'] = vou_no
            
        if inv_vals:
            invoice.write(inv_vals)
            
        invoice.action_post()

        # ── 10. Payments ───────────────────────────────────────────────────────
        def _find_branch_journal(jtype, name_hint=''):
            domain = [('type', '=', jtype), ('company_id', '=', env.company.id)]
            if branch:
                domain.append(('branch_id', '=', branch.id))
            if name_hint:
                j = env['account.journal'].search(domain + [('name', 'ilike', name_hint)], limit=1)
                if j:
                    return j
            j = env['account.journal'].search(domain, limit=1)
            if not j:
                j = env['account.journal'].search([('type', '=', jtype), ('company_id', '=', env.company.id)], limit=1)
            return j

        def _pay(amount, jtype, name_hint='', ref=''):
            if amount <= 0:
                return
            journal = _find_branch_journal(jtype, name_hint)
            if not journal:
                _logger.warning("Voucher %s: Journal not found type=%s hint=%s", vou_no, jtype, name_hint)
                return
            wiz_ctx = {'active_model': 'account.move', 'active_ids': invoice.ids}
            create_vals = {
                'amount': amount,
                'journal_id': journal.id,
                'payment_date': order_date,
            }
            if ref:
                create_vals['communication'] = ref
            wiz = env['account.payment.register'].with_context(**wiz_ctx).create(create_vals)
            payments = wiz.action_create_payments()
            if ref:
                try:
                    pay_domain = [('reconciled_invoice_ids', 'in', invoice.ids), ('journal_id', '=', journal.id)]
                    pay_rec = env['account.payment'].search(pay_domain, order='id desc', limit=1)
                    if pay_rec and hasattr(pay_rec, 'bank_reference'):
                        pay_rec.bank_reference = ref
                except Exception:
                    pass

        try:
            upi_amt1  = max([_flt(r[25]) if len(r) > 25 else 0.0 for idx, r in rows])
            upi_ref1  = next((_str(r[26]) for idx, r in rows if len(r) > 26 and _str(r[26])), '')
            upi_amt2  = max([_flt(r[27]) if len(r) > 27 else 0.0 for idx, r in rows])
            upi_ref2  = next((_str(r[28]) for idx, r in rows if len(r) > 28 and _str(r[28])), '')
            card_amt1 = max([_flt(r[29]) if len(r) > 29 else 0.0 for idx, r in rows])
            card_ref1 = next((_str(r[30]) for idx, r in rows if len(r) > 30 and _str(r[30])), '')
            card_amt2 = max([_flt(r[31]) if len(r) > 31 else 0.0 for idx, r in rows])
            card_ref2 = next((_str(r[32]) for idx, r in rows if len(r) > 32 and _str(r[32])), '')
            cash_amt  = max([_flt(r[33]) if len(r) > 33 else 0.0 for idx, r in rows])

            _pay(upi_amt1,  'bank', 'upi',  upi_ref1)
            _pay(upi_amt2,  'bank', 'upi',  upi_ref2)
            _pay(card_amt1, 'bank', 'card', card_ref1)
            _pay(card_amt2, 'bank', 'card', card_ref2)
            _pay(cash_amt,  'cash', '')
        except Exception as e:
            _logger.warning("Voucher %s: Payment failed: %s", vou_no, e)
    def _build_result_html(self, success_count, skipped_list, error_log):
        download_html = ''
        if skipped_list:
            try:
                pdf = self._generate_skipped_pdf(skipped_list)
                b64 = base64.b64encode(pdf).decode()
                download_html = f"""<div style="margin-top:20px">
                <a href="data:application/pdf;base64,{b64}" download="Unimported_Sales.pdf"
                   style="background:#E53935;color:white;padding:10px 16px;text-decoration:none;
                          font-weight:bold;border-radius:4px;display:inline-block">
                   Download Unimported Sales Report (PDF)
                </a></div>"""
            except Exception as e:
                download_html = f"<p style='color:red'>PDF error: {e}</p>"

        html = f"""<div style="font-family:sans-serif;margin:40px;max-width:900px;padding:24px;
                border:1px solid #e0e0e0;border-radius:8px;box-shadow:0 4px 6px rgba(0,0,0,.05)">
            <h1 style="color:{'green' if success_count else '#333'}">Import Completed</h1>
            <p><strong>Processed (SO→Invoice→Payment):</strong> {success_count}</p>
            <p><strong>Skipped (label not found):</strong> {len(skipped_list)}</p>
            {download_html}"""
        if error_log:
            html += "<h2 style='color:red;margin-top:20px'>Errors:</h2><ul>"
            for e in error_log:
                html += f"<li>{e}</li>"
            html += "</ul>"
        html += "<br><a href='/import/sales_migration/form' style='color:#7C5BBA;font-weight:bold'>← Go Back</a></div>"
        return html

    def _generate_skipped_pdf(self, unimported_list):
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        ts = ParagraphStyle('T', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=16,
                            textColor=colors.HexColor('#E53935'), spaceAfter=12)
        ns = styles['Normal']
        hs = ParagraphStyle('H', parent=ns, fontName='Helvetica-Bold', textColor=colors.white)
        story = [Paragraph("Unimported Sales (Labels Not Found)", ts), Spacer(1, 8)]
        data = [[Paragraph("Row", hs), Paragraph("Customer", hs), Paragraph("Label", hs), Paragraph("Reason", hs)]]
        for item in unimported_list:
            data.append([Paragraph(str(item['row']), ns), Paragraph(str(item.get('customer') or ''), ns),
                         Paragraph(str(item.get('label') or ''), ns), Paragraph(str(item.get('reason') or ''), ns)])
        t = Table(data, colWidths=[50, 150, 150, 190])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E53935')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D3D3D3')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9F9F9')]),
        ]))
        story.append(t)
        doc.build(story)
        return buffer.getvalue()
