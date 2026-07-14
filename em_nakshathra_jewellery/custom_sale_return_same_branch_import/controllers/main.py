import openpyxl
import logging
import base64
from io import BytesIO
import datetime
import traceback

from odoo import http, fields
from odoo.http import request
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

def _flt(val, default=0.0):
    try:
        return float(val or default)
    except Exception:
        return default

def _str(val):
    return str(val).strip() if val is not None else ''

class SaleReturnMigrationController(http.Controller):

    @http.route('/import/sale_return_migration/form', type='http', auth='user')
    def import_form(self, **kwargs):
        html = """
        <!DOCTYPE html><html><head><title>Import Sale Return Data</title>
        <style>
            body{font-family:sans-serif;margin:40px;background:#f4f6f9;}
            .container{max-width:800px;margin:auto;background:white;padding:20px;border-radius:8px;box-shadow:0 4px 6px rgba(0,0,0,.1);}
            h2{color:#333;} .btn{background:#D32F2F;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;font-size:16px;}
            .btn:hover{background:#B71C1C;} input[type="file"]{margin:20px 0;}
            .instructions{font-size:14px;color:#555;margin-bottom:20px;}
        </style></head><body><div class="container">
        <h2>Import Sale Return (Credit Note & New Sale)</h2>
        <div class="instructions"><p>Upload the Excel (.xlsx) file. The system will:</p>
        <ul>
        <li>Find existing Sale Order based on SR sheet.</li>
        <li>Create and post a Credit Note for the existing invoice.</li>
        <li>Return the stock (Delivery).</li>
        <li>Update Sale Order with new lines from SALES sheet, and zero out existing lines.</li>
        <li>Validate new Delivery & create new Invoice.</li>
        <li>Apply Credit Note as outstanding and Register payments for balance.</li>
        </ul></div>
        <form action="/import/sale_return_migration/process" method="POST" enctype="multipart/form-data">
            <input type="hidden" name="csrf_token" value="{csrf_token}"/>
            <input type="file" name="file" accept=".xlsx" required="1"/>
            <button type="submit" class="btn">Import Data</button>
        </form></div></body></html>
        """.replace("{csrf_token}", request.csrf_token())
        return html

    @http.route('/import/sale_return_migration/process', type='http', auth='user', methods=['POST'], csrf=True)
    def import_process(self, file, **kwargs):
        if not file:
            return "<h1>Error</h1><p>No file uploaded.</p>"
        try:
            wb = openpyxl.load_workbook(file, data_only=True)
            
            # Pre-parse SALES sheet (New lines)
            sales_data = {}
            sales_sheet_name = next((s for s in wb.sheetnames if 'SALES' in s.strip().upper()), None)
            
            if sales_sheet_name:
                header_row = next(wb[sales_sheet_name].iter_rows(min_row=1, max_row=1, values_only=True))
                headers = [_str(h).lower().strip().replace(' ', '') for h in header_row]
                
                c_m = {} # column map
                for i, h in enumerate(headers):
                    if 'source' in h and 'loc' in h: c_m['src_loc'] = i
                    elif ('dest' in h and 'loc' in h) or 'returnloc' in h: c_m['dest_loc'] = i
                    elif 'branch' in h: c_m['branch'] = i
                    elif 'vou' in h and 'no' in h: c_m['vou_no'] = i
                    elif 'party' in h: c_m['party'] = i
                    elif 'date' in h: c_m['vou_date'] = i
                    elif 'label' in h: c_m['label'] = i
                    elif 'barcode' in h: c_m['barcode'] = i
                    elif 'item' in h: c_m['item'] = i
                    elif 'salesman' in h: c_m['salesman'] = i
                    elif 'purity' in h or 'carat' in h: c_m['purity'] = i
                    elif 'gross' in h: c_m['gross'] = i
                    elif 'net' in h: c_m['net'] = i
                    elif 'diamond' in h and 'wt' in h: c_m['dia_wt'] = i
                    elif 'stone' in h and 'wt' in h: c_m['st_wt'] = i
                    elif 'metal' in h and 'rate' in h: c_m['m_rate'] = i
                    elif 'metal' in h and 'amt' in h: c_m['m_amt'] = i
                    elif 'mc' in h and 'amt' in h: c_m['mc'] = i
                    elif 'diamond' in h and 'amt' in h: c_m['dia_amt'] = i
                    elif 'stone' in h and 'amt' in h: c_m['st_amt'] = i
                    elif 'other' in h: c_m['other'] = i
                    elif 'tax' in h: c_m['tax'] = i
                    elif 'upi1' in h or 'upi_amt1' in h: c_m['upi_amt1'] = i
                    elif 'upi1' in h and 'ref' in h: c_m['upi_ref1'] = i
                    elif 'upi2' in h or 'upi_amt2' in h: c_m['upi_amt2'] = i
                    elif 'upi2' in h and 'ref' in h: c_m['upi_ref2'] = i
                    elif 'card1' in h or 'card_amt1' in h: c_m['card_amt1'] = i
                    elif 'card1' in h and 'ref' in h: c_m['card_ref1'] = i
                    elif 'card2' in h or 'card_amt2' in h: c_m['card_amt2'] = i
                    elif 'card2' in h and 'ref' in h: c_m['card_ref2'] = i
                    elif 'cash' in h and 'amt' in h: c_m['cash_amt'] = i
                    elif 'scheme' in h: c_m['gold_scheme_amt'] = i
                    elif 'ticket' in h: c_m['ticket_no'] = i
                
                for row_idx, row in enumerate(wb[sales_sheet_name].iter_rows(min_row=2, values_only=True), start=2):
                    if not any(row): continue
                    vou_no = _str(row[c_m.get('vou_no', 1)]) # Vou No
                    if vou_no:
                        if vou_no not in sales_data:
                            sales_data[vou_no] = []
                        
                        vou_date = row[c_m.get('vou_date', 3)]
                        if isinstance(vou_date, (datetime.datetime, datetime.date)):
                            vou_date = vou_date.strftime('%Y-%m-%d %H:%M:%S')
                            
                        # Optional revision date at the end
                        rev_date = row[-1] if len(row) > 36 else False
                        if isinstance(rev_date, (datetime.datetime, datetime.date)):
                            rev_date = rev_date.strftime('%Y-%m-%d %H:%M:%S')
                            
                        r = list(row) + [None]*50
                        
                        sales_data[vou_no].append({
                            'branch_name': _str(r[c_m.get('branch', 0)]),
                            'party_name': _str(r[c_m.get('party', 2)]),
                            'vou_date': vou_date,
                            'source_loc': _str(r[c_m.get('src_loc', 4)]),
                            'dest_loc': _str(r[c_m.get('dest_loc', 5)]),
                            'label_no': _str(r[c_m.get('label', 6)]),
                            'barcode_no': _str(r[c_m.get('barcode', 7)]),
                            'item_name': _str(r[c_m.get('item', 8)]),
                            'salesman': _str(r[c_m.get('salesman', 9)]),
                            'purity': _str(r[c_m.get('purity', 10)]),
                            'gross_wt': _flt(r[c_m.get('gross', 11)]),
                            'diamond_wt': _flt(r[c_m.get('dia_wt', 13)]),
                            'stone_wt': _flt(r[c_m.get('st_wt', 14)]),
                            'metal_rate': _flt(r[c_m.get('m_rate', 15)]),
                            'metal_amt': _flt(r[c_m.get('m_amt', 16)]),
                            'mc_amt': _flt(r[c_m.get('mc', 17)]),
                            'diamond_amt': _flt(r[c_m.get('dia_amt', 18)]),
                            'stone_amt': _flt(r[c_m.get('st_amt', 19)]),
                            'other_charge': _flt(r[c_m.get('other', 20)]),
                            'taxes': _str(r[c_m.get('tax', 22)]),
                            'upi_amt1': _flt(r[c_m.get('upi_amt1', 25)]),
                            'upi_ref1': _str(r[c_m.get('upi_ref1', 26)]),
                            'upi_amt2': _flt(r[c_m.get('upi_amt2', 27)]),
                            'upi_ref2': _str(r[c_m.get('upi_ref2', 28)]),
                            'card_amt1': _flt(r[c_m.get('card_amt1', 29)]),
                            'card_ref1': _str(r[c_m.get('card_ref1', 30)]),
                            'card_amt2': _flt(r[c_m.get('card_amt2', 31)]),
                            'card_ref2': _str(r[c_m.get('card_ref2', 32)]),
                            'cash_amt': _flt(r[c_m.get('cash_amt', 33)]),
                            'gold_scheme_amt': _flt(r[c_m.get('gold_scheme_amt', 35)]),
                            'ticket_no': _str(r[c_m.get('ticket_no', -1)]) if 'ticket_no' in c_m else '',
                            'reversal_date': rev_date,
                        })

            # Pre-parse SR sheet
            sr_rows = []
            seen_docs = set()
            if 'SR' in wb.sheetnames:
                sr_sheet = wb['SR']
                sr_header_row = next(sr_sheet.iter_rows(min_row=1, max_row=1, values_only=True))
                sr_headers = [_str(h).lower().strip().replace(' ', '') for h in sr_header_row]
                sr_cm = {}
                for i, h in enumerate(sr_headers):
                    if 'source' in h and 'loc' in h: sr_cm['src_loc'] = i
                    
                for row_idx, row in enumerate(sr_sheet.iter_rows(min_row=2, values_only=True), start=2):
                    if not any(row): continue
                    source_doc = _str(row[0]) # Source document
                    if not source_doc: continue
                    
                    # Deduplicate by source document to avoid processing the same order multiple times
                    if source_doc in seen_docs:
                        continue
                    seen_docs.add(source_doc)
                    
                    reason = _str(row[38]) if len(row) > 38 else ''
                    rev_date = row[39] if len(row) > 39 else False
                    if isinstance(rev_date, (datetime.datetime, datetime.date)):
                        rev_date = rev_date.strftime('%Y-%m-%d %H:%M:%S')
                        
                    sr_loc = _str(row[sr_cm['src_loc']]) if 'src_loc' in sr_cm and len(row) > sr_cm['src_loc'] else ''
                        
                    sr_rows.append({
                        'source_doc': source_doc,
                        'sr_row': [source_doc, _str(row[1]) if len(row) > 1 else ''],
                        'reason': reason,
                        'reversal_date': rev_date,
                        'sr_loc': sr_loc,
                        'row_idx': row_idx
                    })

            import uuid, json
            file_id = str(uuid.uuid4())
            temp_path = f'/tmp/odoo_import_{file_id}.json'
            
            with open(temp_path, 'w') as f:
                json.dump({'sales_data': sales_data, 'sr_rows': sr_rows}, f)
                
            total_records = len(sr_rows)

            html = f"""
            <!DOCTYPE html><html><head><title>Processing Import</title>
            <style>
                body{{font-family:sans-serif;margin:40px;background:#f4f6f9;}}
                .container{{max-width:800px;margin:auto;background:white;padding:20px;border-radius:8px;box-shadow:0 4px 6px rgba(0,0,0,.1);}}
                .progress-bar{{width:100%;background:#e0e0e0;border-radius:4px;overflow:hidden;margin-top:20px;height:24px;}}
                .progress{{width:0%;height:100%;background:#4CAF50;transition:width 0.2s;}}
                .logs{{margin-top:20px;max-height:400px;overflow-y:auto;background:#222;color:#0f0;padding:10px;font-family:monospace;font-size:13px;line-height:1.4;}}
            </style>
            </head><body><div class="container">
            <h2>Processing Import ({total_records} Records)</h2>
            <p>Please do not close or refresh this window until the process completes.</p>
            <div class="progress-bar"><div class="progress" id="progress"></div></div>
            <p id="status">0 / {total_records} processed</p>
            <div class="logs" id="logs"></div>
            
            <script>
                let offset = 0;
                const limit = 50; // Process 50 rows per chunk
                const total = {total_records};
                const file_id = '{file_id}';
                let total_success = 0;
                let all_errors = [];

                function logMsg(msg) {{
                    const d = document.getElementById('logs');
                    d.innerHTML += "<div>" + msg + "</div>";
                    d.scrollTop = d.scrollHeight;
                }}

                function processChunk() {{
                    if (offset >= total) {{
                        logMsg("<br><b style='color:#4CAF50'>Import Completed! Success: " + total_success + ", Errors: " + all_errors.length + "</b>");
                        if(all_errors.length > 0) {{
                            logMsg("<br><b style='color:red'>Errors:</b><br>" + all_errors.join("<br>"));
                        }}
                        logMsg("<br><a href='/import/sale_return_migration/form' style='color:#fff;text-decoration:underline'>← Go Back</a>");
                        return;
                    }}

                    logMsg("Processing row " + offset + " to " + Math.min(offset + limit, total) + "...");
                    
                    fetch('/import/sale_return_migration/process_chunk', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{params: {{file_id: file_id, offset: offset, limit: limit}}}}),
                    }})
                    .then(r => r.json())
                    .then(res => {{
                        if (res.error) {{
                            logMsg("<span style='color:red'>Server Error: " + (res.error.message || JSON.stringify(res.error)) + "</span>");
                            return;
                        }}
                        const data = res.result;
                        if(data.error) {{
                            logMsg("<span style='color:red'>Fatal Error: " + data.error + "</span>");
                            return;
                        }}
                        total_success += data.success_count;
                        if(data.errors && data.errors.length > 0) {{
                            all_errors = all_errors.concat(data.errors);
                            for(let e of data.errors) logMsg("<span style='color:red'>" + e + "</span>");
                        }}
                        
                        offset += limit;
                        const pct = Math.min(100, Math.round((offset / total) * 100));
                        document.getElementById('progress').style.width = pct + '%';
                        document.getElementById('status').innerText = Math.min(offset, total) + ' / ' + total + ' processed';
                        
                        processChunk();
                    }})
                    .catch(e => {{
                        logMsg("<span style='color:red'>Network Error: " + e + "</span>");
                    }});
                }}
                
                if(total > 0) {{
                    processChunk();
                }} else {{
                    logMsg("No records to process.");
                }}
            </script>
            </div></body></html>
            """
            return html

        except Exception as e:
            return f"<h1 style='color:red'>Fatal Error</h1><p>{str(e)}</p>"

    @http.route('/import/sale_return_migration/process_chunk', type='json', auth='user', methods=['POST'])
    def import_process_chunk(self, file_id, offset, limit, **kwargs):
        try:
            import json, os
            temp_path = f'/tmp/odoo_import_{file_id}.json'
            if not os.path.exists(temp_path):
                return {'error': 'Temporary data file not found. Please upload the file again.'}
                
            with open(temp_path, 'r') as f:
                data = json.load(f)
                
            sr_rows = data['sr_rows']
            sales_data = data['sales_data']
            
            chunk = sr_rows[offset : offset+limit]
            
            success_count = 0
            error_log = []
            
            for row in chunk:
                source_doc = row['source_doc']
                sr_row = row['sr_row']
                reason = row.get('reason', '')
                rev_date = row.get('reversal_date', False)
                sr_loc = row.get('sr_loc', '')
                row_idx = row['row_idx']
                
                try:
                    with request.env.cr.savepoint():
                        self._process_return_row(source_doc, sr_row, sales_data, row_idx, error_log, reason=reason, rev_date=rev_date, sr_loc=sr_loc)
                    success_count += 1
                except Exception as e:
                    error_log.append(f"SR Row {row_idx} ({source_doc}): {str(e)}")
                    _logger.exception("SR Row %s failed", row_idx)

            return {
                'success_count': success_count,
                'errors': error_log
            }
        except Exception as e:
            return {'error': str(e)}

    def _process_return_row(self, source_doc, sr_row, sales_data, row_idx, error_log, reason='', rev_date=False, sr_loc=''):
        env = request.env

        # SR sheet: [0]=Source document (=origin), [1]=Customer name
        cust_name = _str(sr_row[1]) if sr_row and len(sr_row) > 1 else ''

        # --- Resolve partner ---
        partner = env['res.partner']
        if cust_name:
            partner = env['res.partner'].search([('name', '=', cust_name)], limit=1)
            if not partner:
                partner = env['res.partner'].search([('name', 'ilike', cust_name)], limit=1)

        # --- Search Sale Order by origin (Source Document field) + customer ---
        order = env['sale.order']
        if partner:
            order = env['sale.order'].search([
                ('origin', 'ilike', source_doc),
                ('partner_id', '=', partner.id),
            ], limit=1)

        if not order:
            # Fallback: origin only (any customer)
            order = env['sale.order'].search([('origin', 'ilike', source_doc)], limit=1)

        if not order:
            # Last resort: match by order name (e.g. if source_doc is the SO name itself)
            order = env['sale.order'].search([('name', 'ilike', source_doc)], limit=1)

        if not order:
            raise UserError(
                f"Sale Order not found for Source Document='{source_doc}' "
                f"and Customer='{cust_name}'. Checked: origin, name fields."
            )

        # Get the corresponding SALES data (which has the new lines)
        s_data_list = sales_data.get(source_doc, [])
        if not s_data_list:
            raise UserError(f"No corresponding SALES sheet data for {source_doc}")
            
        s_data = s_data_list[0] # Take the first one for header info

        if not reason:
            reason = 'Sale Return'
        if not isinstance(rev_date, (datetime.datetime, datetime.date, str)) or not rev_date:
            rev_date = fields.Date.context_today(order)

        # 1. Reverse Invoice (Credit Note)
        posted_invoices = order.invoice_ids.filtered(lambda i: i.state == 'posted' and i.move_type == 'out_invoice')
        credit_notes = env['account.move']
        for inv in posted_invoices:
            # Create reversal wizard
            reversal_wiz = env['account.move.reversal'].with_context(active_model="account.move", active_ids=inv.ids).create({
                'reason': reason,
                'date': rev_date,
                'journal_id': inv.journal_id.id,
            })
            res = reversal_wiz.reverse_moves()
            if res and 'res_id' in res:
                cn = env['account.move'].browse(res['res_id'])
                cn.action_post()
                credit_notes |= cn

        # Resolve sr_loc if provided in SR sheet
        excel_return_loc = False
        if sr_loc:
            import re
            loc_pattern = '%' + '%'.join(re.split(r'[^a-zA-Z0-9]', sr_loc)) + '%'
            excel_return_loc = env['stock.location'].search(['|', ('complete_name', 'ilike', loc_pattern), ('name', 'ilike', loc_pattern)], limit=1)

        # 2. Return Stock
        done_pickings = order.picking_ids.filtered(lambda p: p.state == 'done' and p.picking_type_code == 'outgoing')
        for picking in done_pickings:
            # Use default_get to properly populate the return moves based on the picking
            wiz_context = {
                'active_id': picking.id,
                'active_ids': picking.ids,
                'active_model': 'stock.picking',
            }
            default_vals = env['stock.return.picking'].with_context(**wiz_context).default_get(
                ['picking_id', 'product_return_moves', 'location_id', 'original_location_id']
            )
            
            # Use Excel return location, fallback to original product source location
            target_loc_id = excel_return_loc.id if excel_return_loc else (picking.location_id.id if picking.location_id else False)
            if target_loc_id:
                default_vals['location_id'] = target_loc_id
                
            # Explicitly build product return moves based on delivered quantity
            return_moves = []
            for move in picking.move_ids:
                if move.state == 'cancel' or move.scrapped: continue
                # In Odoo 17, the delivered quantity is 'quantity'.
                delivered_qty = getattr(move, 'quantity', getattr(move, 'product_qty', 0))
                if delivered_qty > 0:
                    # check if already returned
                    returned_qty = sum(move.move_dest_ids.filtered(
                        lambda m: m.state in ['partially_available', 'assigned', 'done'] and not m.scrapped
                    ).mapped(lambda m: getattr(m, 'quantity', getattr(m, 'product_qty', 0))))
                    
                    qty_to_return = delivered_qty - returned_qty
                    if qty_to_return > 0:
                        return_moves.append((0, 0, {
                            'product_id': move.product_id.id,
                            'quantity': qty_to_return,
                            'move_id': move.id,
                            'uom_id': move.product_id.uom_id.id,
                        }))
            
            if not return_moves:
                _logger.warning("No quantity to return for picking %s (already returned?)", picking.name)
                continue
                
            default_vals['product_return_moves'] = return_moves
                
            return_wiz = env['stock.return.picking'].with_context(**wiz_context).create(default_vals)
            
            res = return_wiz.create_returns()
            if res and 'res_id' in res:
                return_picking = env['stock.picking'].browse(res['res_id'])
                
                # Double-check and force destination location on the returned moves and picking
                if target_loc_id:
                    return_picking.location_dest_id = target_loc_id
                    for m in return_picking.move_ids:
                        m.location_dest_id = target_loc_id
                        for ml in m.move_line_ids:
                            ml.location_dest_id = target_loc_id
                            
                # validate return picking
                return_picking.action_confirm()
                return_picking.action_assign()
                for move in return_picking.move_ids:
                    move.quantity = move.product_uom_qty
                    if hasattr(move, 'picked'): move.picked = True
                
                try:
                    res_val = return_picking.with_context(skip_backorder=True, cancel_backorder=True).button_validate()
                    if isinstance(res_val, dict):
                        model = res_val.get('res_model', '')
                        ctx = res_val.get('context', {})
                        if model == 'stock.immediate.transfer':
                            wiz = env['stock.immediate.transfer'].with_context(ctx).create({'pick_ids': [(4, return_picking.id)]})
                            wiz.process()
                        elif model == 'stock.backorder.confirmation':
                            wiz = env['stock.backorder.confirmation'].with_context(ctx).create({'pick_ids': [(4, return_picking.id)]})
                            wiz.process_cancel_backorder()
                except Exception as e:
                    _logger.warning("Return Delivery validate failed: %s", e)

        # 3. Update Sale Order
        # Set old lines to 0
        for line in order.order_line:
            if line.product_uom_qty > 0:
                # Bypass any potential errors if possible by using direct SQL fallback
                try:
                    line.write({'product_uom_qty': 0})
                except Exception as e:
                    _logger.warning("Could not set qty to 0 for line %s via ORM: %s", line.id, e)
                    env.cr.execute("UPDATE sale_order_line SET product_uom_qty = 0 WHERE id = %s", (line.id,))

        labels_to_deactivate = env['product.label']
        # Add new lines
        for new_s in s_data_list:
            label_ref = new_s.get('label_no')
            barcode_ref = new_s.get('barcode_no')
            item_name = new_s.get('item_name')
            
            # If no identifiers provided, skip
            if not label_ref and not barcode_ref and not item_name: continue
            
            label = env['product.label']
            if label_ref:
                label = env['product.label'].search([('name', '=', label_ref)], limit=1)
            if not label and barcode_ref:
                label = env['product.label'].search([('barcode', '=', barcode_ref)], limit=1)
            
            line_product = env['product.product']
            if label:
                labels_to_deactivate |= label
                line_product = label.product_id or label.product_tmpl_id.product_variant_id
                
            # Fallback to product name if label not found or label has no product
            if not line_product and item_name:
                line_product = env['product.product'].search([('name', 'ilike', item_name)], limit=1)
            
            if not line_product:
                raise UserError(f"Product not found for Label '{label_ref}', Barcode '{barcode_ref}', or Item Name '{item_name}'.")

            purity_name = new_s.get('purity')
            purity = env['gold.purity'].search([('name', 'ilike', purity_name)], limit=1) if purity_name else (label.purity_id if label else False)
            
            taxes = line_product.taxes_id.filtered(lambda t: t.company_id == env.company)
            
            line_vals = {
                'order_id': order.id,
                'product_id': line_product.id,
                'label_id': label.id if label else False,
                'purity_id': purity.id if purity else False,
                'product_uom_qty': new_s.get('gross_wt') or (label.sale_gross_weight if label else 0) or 1.0,
                'product_uom': line_product.uom_id.id,
                'sale_stone_weight': new_s.get('stone_wt') or (label.sale_stone_weight if label else 0),
                'sale_diamond_weight_gm': new_s.get('diamond_wt') or (label.sale_diamond_weight_gm if label else 0),
                'sale_stone_rate': new_s.get('stone_amt') or (label.sale_stone_rate if label else 0),
                'sale_diamond_rate': new_s.get('diamond_amt') or (label.sale_diamond_rate if label else 0),
                'other_weight_amount': new_s.get('other_charge', 0.0),
                'gold_rate': new_s.get('metal_rate') or (label.sale_price_per_gram if label else 0),
                'tax_id': [(6, 0, taxes.ids)] if taxes else [],
            }
            line = env['sale.order.line'].create(line_vals)
            
            # --- Call Onchange ---
            if hasattr(line, '_onchange_label_id'):
                line._onchange_label_id()
                
            # --- Override Math ---
            excel_metal_rate = new_s.get('metal_rate') or line.gold_rate
            excel_metal_amt = new_s.get('metal_amt', 0.0)
            mc_amt = new_s.get('mc_amt', 0.0)
            
            line_updates = {'gold_rate': excel_metal_rate}
            
            if excel_metal_amt > 0:
                pct = (mc_amt / excel_metal_amt) * 100.0
                line_updates['mc_percent_actual'] = pct
                
            line.write(line_updates)
            
            if excel_metal_amt > 0:
                env.cr.execute("UPDATE sale_order_line SET metal_amount = %s WHERE id = %s", (excel_metal_amt, line.id))
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

            
            # Apply Source Location from Excel to the generated stock moves
            loc_name = new_s.get('source_loc')
            if loc_name:
                import re
                loc_pattern = '%' + '%'.join(re.split(r'[^a-zA-Z0-9]', loc_name)) + '%'
                loc = env['stock.location'].search(['|', ('complete_name', 'ilike', loc_pattern), ('name', 'ilike', loc_pattern)], limit=1)
                if loc:
                    for move in line.move_ids:
                        move.location_id = loc.id
                        for ml in move.move_line_ids:
                            ml.location_id = loc.id
                        if move.picking_id:
                            move.picking_id.location_id = loc.id
        # 3b. Try to apply scheme natively (triggers the button logic)
        partner = order.partner_id
        excel_party_name = s_data.get('party_name')
        scheme_partner = partner
        if excel_party_name:
            excel_party = env['res.partner'].search([('name', '=', excel_party_name)], limit=1)
            if not excel_party:
                excel_party = env['res.partner'].search([('name', 'ilike', excel_party_name)], limit=1)
            if excel_party:
                scheme_partner = excel_party

        # Temporarily use scheme_partner so action_apply_scheme can find it
        old_partner = order.partner_id
        if old_partner.id != scheme_partner.id:
            order.partner_id = scheme_partner.id
            
        try:
            if not order.scheme_line_id:
                ticket_no = s_data.get('ticket_no')
                existing_scheme = env['jewellery.scheme.enrollment']
                if ticket_no:
                    existing_scheme = env['jewellery.scheme.enrollment'].search([
                        ('ticket_number', '=', ticket_no)
                    ], limit=1)
                if not existing_scheme:
                    existing_scheme = env['jewellery.scheme.enrollment'].search([
                        ('partner_id', '=', scheme_partner.id),
                    ], order='id desc', limit=1)
                
                if existing_scheme:
                    order.apply_scheme = True
                    order.active_scheme_id = existing_scheme.id
                    order.action_apply_scheme()
        except Exception as e:
            _logger.info("Native scheme application failed for %s: %s", order.name, e)
            
        # Restore partner if changed
        if old_partner.id != order.partner_id.id:
            order.partner_id = old_partner.id

        # Fallback: Apply Gold Scheme manually if specified in SALES sheet but native failed
        gold_scheme_amt = _flt(s_data.get('gold_scheme_amt', 0.0))
        if gold_scheme_amt > 0 and not order.scheme_line_id:
            # Search for ANY scheme enrollment for this customer to force application during migration
            ticket_no = s_data.get('ticket_no')
            existing_scheme = env['jewellery.scheme.enrollment']
            if ticket_no:
                existing_scheme = env['jewellery.scheme.enrollment'].search([
                    ('ticket_number', '=', ticket_no)
                ], limit=1)
            if not existing_scheme:
                existing_scheme = env['jewellery.scheme.enrollment'].search([
                    ('partner_id', '=', scheme_partner.id),
                ], order='id desc', limit=1)
                
            if existing_scheme:
                order.apply_scheme = True
                order.active_scheme_id = existing_scheme.id
                
                try:
                    redeem_amount = gold_scheme_amt
                    product_code = f"SCHEME-{existing_scheme.id}"
                    scheme_product = env['product.product'].search([('default_code', '=', product_code)], limit=1)
                    
                    if not scheme_product:
                        scheme_product = env['product.product'].create({
                            'name': f"{existing_scheme.name} - {partner.name}",
                            'default_code': product_code,
                            'type': 'service',
                            'list_price': 0.0,
                        })

                    line_vals = {
                        'order_id': order.id,
                        'product_id': scheme_product.id,
                        'product_uom_qty': 1,
                        'product_uom': scheme_product.uom_id.id,
                        'name': f"{scheme_product.name} (Scheme Redemption)",
                        'is_scheme_line': True,
                        'price_unit': -redeem_amount,
                        'tax_id': False,
                    }
                    line = env['sale.order.line'].create(line_vals)
                    order.scheme_line_id = line.id
                    existing_scheme.write({
                        'state': 'redeemed',
                        'is_redeemed': True,
                    })
                    if 'scheme.redemption' in env:
                        env['scheme.redemption'].create({
                            'scheme_id': existing_scheme.id,
                            'sale_order_id': order.id,
                            'amount': redeem_amount,
                        })
                    _logger.info("Scheme applied directly from excel amount for order %s, scheme %s", order.name, existing_scheme.id)
                except Exception as e:
                    _logger.warning("Direct scheme apply failed for order %s: %s", order.name, e)
            else:
                _logger.warning("Gold Scheme amt %s found in SALES sheet for %s but no active scheme enrollment found for customer %s",
                                gold_scheme_amt, source_doc, partner.name)

        # 4. New Delivery Validation
        # Refresh order pickings to find the newly generated delivery
        new_pickings = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel') and p.picking_type_code == 'outgoing')
        for picking in new_pickings:
            picking.action_confirm()
            picking.action_assign()
            if s_data.get('vou_date'):
                picking.write({'scheduled_date': s_data.get('vou_date')})
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                if hasattr(move, 'picked'): move.picked = True
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
                        wiz.process_cancel_backorder()
            except Exception as e:
                _logger.warning("New Delivery validate failed for order %s: %s", order.name, str(e))

            # SQL Date Override
            if s_data.get('vou_date'):
                vou_date = s_data.get('vou_date')
                env.cr.execute("UPDATE stock_picking SET date_done = %s, date = %s WHERE id = %s", (vou_date, vou_date, picking.id))
                env.cr.execute("UPDATE stock_move SET date = %s WHERE picking_id = %s", (vou_date, picking.id))
                env.cr.execute("UPDATE stock_move_line SET date = %s WHERE picking_id = %s", (vou_date, picking.id))

        # 5. Create New Invoice
        new_invoice = order._create_invoices()
        if new_invoice:
            if s_data.get('vou_date'):
                v_date = s_data.get('vou_date')
                if isinstance(v_date, str):
                    date_only = datetime.datetime.strptime(v_date[:10], '%Y-%m-%d').date()
                else:
                    date_only = v_date.date() if isinstance(v_date, datetime.datetime) else v_date
                new_invoice.write({
                    'invoice_date': date_only,
                    'date': date_only,
                    'invoice_date_due': date_only,
                    'delivery_date': date_only
                })
            new_invoice.action_post()

            # 6. Apply Credit Note as Outstanding
            if credit_notes:
                # Get the outstanding credit lines
                for cn in credit_notes:
                    for line in cn.line_ids:
                        if line.account_id.account_type == 'asset_receivable' and not line.reconciled:
                            # Apply this line to the new invoice
                            try:
                                new_invoice.js_assign_outstanding_line(line.id)
                            except Exception as e:
                                _logger.warning("Failed to assign outstanding line: %s", e)
            
            # 7. Payments
            branch = order.branch_id
            def _find_branch_journal(jtype, name_hint=''):
                domain = [('type', '=', jtype), ('company_id', '=', env.company.id)]
                if branch:
                    domain.append(('branch_id', '=', branch.id))
                if name_hint:
                    j = env['account.journal'].search(domain + [('name', 'ilike', name_hint)], limit=1)
                    if j: return j
                j = env['account.journal'].search(domain, limit=1)
                return j or env['account.journal'].search([('type', '=', jtype), ('company_id', '=', env.company.id)], limit=1)

            def _pay(amount, jtype, name_hint='', ref=''):
                if amount <= 0: return
                journal = _find_branch_journal(jtype, name_hint)
                if not journal: return
                wiz_ctx = {'active_model': 'account.move', 'active_ids': new_invoice.ids}
                wiz = env['account.payment.register'].with_context(**wiz_ctx).create({
                    'amount': amount,
                    'journal_id': journal.id,
                    'payment_date': rev_date,
                    'communication': ref
                })
                payments = wiz.action_create_payments()
                if ref:
                    try:
                        pay_domain = [('reconciled_invoice_ids', 'in', new_invoice.ids), ('journal_id', '=', journal.id)]
                        pay_rec = env['account.payment'].search(pay_domain, order='id desc', limit=1)
                        if pay_rec and hasattr(pay_rec, 'bank_reference'):
                            pay_rec.bank_reference = ref
                    except Exception:
                        pass
            
            # We pay using the first SALES sheet row's payment data
            try:
                _pay(s_data.get('upi_amt1', 0),  'bank', 'upi',  s_data.get('upi_ref1', ''))
                _pay(s_data.get('upi_amt2', 0),  'bank', 'upi',  s_data.get('upi_ref2', ''))
                _pay(s_data.get('card_amt1', 0), 'bank', 'card', s_data.get('card_ref1', ''))
                _pay(s_data.get('card_amt2', 0), 'bank', 'card', s_data.get('card_ref2', ''))
                _pay(s_data.get('cash_amt', 0),  'cash', '')
            except Exception as e:
                _logger.warning("Payment registration failed: %s", e)

            # 7b. Trigger 'Create Customer Payment' if applicable (e.g. for Scheme/OG refunds)
            try:
                if hasattr(new_invoice, 'custom_total') and getattr(new_invoice, 'custom_total', 0) < 0:
                    if hasattr(new_invoice, 'action_create_old_gold_vendor_payment'):
                        new_invoice.action_create_old_gold_vendor_payment()
                        _logger.info("Triggered action_create_old_gold_vendor_payment for %s", new_invoice.name)
            except Exception as e:
                _logger.warning("Auto-create customer payment failed for %s: %s", new_invoice.name, e)

        # 8. Deactivate Labels
        if labels_to_deactivate:
            try:
                labels_to_deactivate.write({'active': False})
            except Exception as e:
                _logger.warning("Failed to deactivate labels: %s", e)
