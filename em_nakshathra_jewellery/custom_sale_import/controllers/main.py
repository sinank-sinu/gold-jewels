import openpyxl
import logging
import base64
from io import BytesIO
import datetime
import json
import os
import uuid
import gc

from odoo import http, fields
from odoo.http import request
from odoo.exceptions import UserError, ValidationError

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

_logger = logging.getLogger(__name__)


def _val(row, idx, default=None):
    if row is not None and 0 <= idx < len(row):
        return row[idx]
    return default


def _flt(val, default=0.0):
    try:
        if val is None or val == '':
            return default
        return float(val)
    except Exception:
        return default


def _str(val):
    return str(val).strip() if val is not None else ''


# Ensure company-aware internal picking type during old gold stock transfer
try:
    from odoo.addons.em_jewellery_management.models.sale_order import SaleOrder
    orig_create_old_gold_stock = getattr(SaleOrder, '_create_old_gold_stock', None)

    def _company_aware_create_old_gold_stock(self, og):
        product = self.env.ref('em_jewellery_management.product_old_gold', raise_if_not_found=False)
        picking_type = (self.warehouse_id and self.warehouse_id.int_type_id) or self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', self.company_id.id),
        ], limit=1) or self.env.ref('stock.picking_type_internal', raise_if_not_found=False)
        
        # Resolve company-scoped source location for old gold
        source_location = self.env['stock.location'].search([
            ('name', 'ilike', 'Old Gold'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not source_location:
            parent_loc = (self.warehouse_id and self.warehouse_id.lot_stock_id) or self.branch_location_id
            if parent_loc:
                source_location = self.env['stock.location'].search([
                    ('name', '=', 'Old Gold'),
                    ('location_id', '=', parent_loc.id),
                    ('company_id', '=', self.company_id.id),
                ], limit=1)
                if not source_location:
                    source_location = self.env['stock.location'].sudo().create({
                        'name': 'Old Gold',
                        'location_id': parent_loc.id,
                        'usage': 'internal',
                        'company_id': self.company_id.id,
                    })
        if not source_location:
            source_location = self.branch_location_id or (self.warehouse_id and self.warehouse_id.lot_stock_id) or self.env.ref('em_jewellery_management.loc_branch_old_gold', raise_if_not_found=False)
        
        uom = self.env.ref('uom.product_uom_gram', raise_if_not_found=False)

        if not product or not picking_type or not source_location or not uom:
            if orig_create_old_gold_stock:
                return orig_create_old_gold_stock(self, og)
            return

        dest_location = self.branch_location_id or (self.warehouse_id and self.warehouse_id.lot_stock_id)
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': source_location.id,
            'location_dest_id': dest_location.id if dest_location else source_location.id,
            'origin': self.name,
            'is_old_gold': True,
            'sale_old_id': self.id,
            'branch_id': self.branch_id.id if (hasattr(self, 'branch_id') and self.branch_id) else False,
            'company_id': self.company_id.id,
        })

        move = self.env['stock.move'].create({
            'product_id': product.id,
            'name': f'Old Gold ({og.purity_id.name})' if og.purity_id else 'Old Gold',
            'quantity': og.net_weight,
            'purity_id': og.purity_id.id if og.purity_id else False,
            'product_uom': uom.id,
            'location_id': source_location.id,
            'location_dest_id': dest_location.id if dest_location else source_location.id,
            'picking_id': picking.id,
            'company_id': self.company_id.id,
        })

        try:
            picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids:
                move.product_uom_qty = og.net_weight
                move.quantity = og.net_weight
                if hasattr(move, 'picked'):
                    move.picked = True
            picking.button_validate()
        except Exception as e:
            _logger.warning("Old gold picking validation warning: %s", e)
        og.stock_move_id = move.id

    SaleOrder._create_old_gold_stock = _company_aware_create_old_gold_stock
except Exception as e:
    _logger.warning("Could not patch SaleOrder._create_old_gold_stock: %s", e)


class SaleImportController(http.Controller):

    @http.route('/import/sales_migration/form', type='http', auth='user')
    def import_form(self, **kwargs):
        csrf = request.csrf_token()
        return f"""<!DOCTYPE html><html><head><title>Import Sales Data</title>
<style>
body{{font-family:sans-serif;margin:40px;background:#f4f6f9;}}
.box{{max-width:820px;margin:auto;background:#fff;padding:24px;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,.12);}}
h2{{color:#1a237e;}} .btn{{background:#1a237e;color:#fff;padding:10px 22px;border:none;border-radius:4px;cursor:pointer;font-size:15px;}}
.btn:hover{{background:#283593;}} li{{margin:4px 0;}}
.instructions{{font-size:14px;color:#555;margin-bottom:20px;}}
</style></head><body><div class="box">
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
<input type="hidden" name="csrf_token" value="{csrf}"/>
<input type="file" name="file" accept=".xlsx" required="1" style="margin:16px 0;display:block"/>
<button type="submit" class="btn">Import Data</button>
</form></div></body></html>"""

    @http.route('/import/sales_migration/process', type='http', auth='user', methods=['POST'], csrf=True)
    def import_process(self, file, **kwargs):
        if not file:
            return "<h1>Error</h1><p>No file uploaded.</p>"
        try:
            wb = openpyxl.load_workbook(file, data_only=True, read_only=True)

            # Locate SALES sheet
            sales_sn = next((s for s in wb.sheetnames if s.strip().upper() == 'SALES' or s.strip().upper().startswith('SALE')), wb.sheetnames[0])
            sales_header_row = next(wb[sales_sn].iter_rows(min_row=1, max_row=1, values_only=True))
            headers = [_str(h).lower().strip().replace(' ', '').replace('.', '').replace('-', '').replace('_', '') for h in sales_header_row]

            c_m = {}
            for i, h in enumerate(headers):
                if 'company' in h: c_m['company'] = i
                elif 'branch' in h: c_m['branch'] = i
                elif 'vou' in h and 'no' in h: c_m['vou_no'] = i
                elif 'party' in h or 'cust' in h: c_m['party'] = i
                elif 'date' in h: c_m['vou_date'] = i
                elif 'source' in h and 'loc' in h: c_m['src_loc'] = i
                elif 'variant' in h or ('prod' in h and 'name' in h) or 'item' in h: c_m['product_var'] = i
                elif 'label' in h: c_m['label'] = i
                elif 'barcode' in h: c_m['barcode'] = i
                elif 'salesman' in h or 'salesperson' in h: c_m['salesman'] = i
                elif 'purity' in h or 'carat' in h: c_m['purity'] = i
                elif 'pcs' in h or 'qty' in h: c_m['pcs'] = i
                elif 'gross' in h: c_m['gross'] = i
                elif 'net' in h: c_m['net'] = i
                elif 'di' in h and 'wt' in h: c_m['dia_wt'] = i
                elif 'st' in h and 'wt' in h: c_m['st_wt'] = i
                elif ('metal' in h and 'rate' in h) or ('gold' in h and 'rate' in h): c_m['m_rate'] = i
                elif ('metal' in h and 'amt' in h) or ('gold' in h and 'amt' in h): c_m['m_amt'] = i
                elif h == 'mc' or ('mc' in h and 'amt' in h) or 'making' in h:
                    if '%' not in h: c_m['mc'] = i
                elif 'di' in h and 'amt' in h: c_m['dia_amt'] = i
                elif 'st' in h and 'amt' in h: c_m['st_amt'] = i
                elif 'other' in h: c_m['other'] = i
                elif 'tax' in h and 'amt' not in h and 'able' not in h: c_m['tax'] = i
                elif 'bank' in h and ('ref' in h or 'reference' in h): c_m['bank_ref'] = i
                elif 'bank' in h: c_m['bank_amt'] = i
                elif 'upi' in h and '2' in h and ('ref' in h or 'reference' in h): c_m['upi_ref2'] = i
                elif 'upi' in h and '2' in h: c_m['upi_amt2'] = i
                elif 'upi' in h and ('ref' in h or 'reference' in h): c_m['upi_ref1'] = i
                elif 'upi' in h: c_m['upi_amt1'] = i
                elif 'card' in h and '3' in h and ('ref' in h or 'reference' in h): c_m['card_ref3'] = i
                elif 'card' in h and '3' in h: c_m['card_amt3'] = i
                elif 'card' in h and '2' in h and ('ref' in h or 'reference' in h): c_m['card_ref2'] = i
                elif 'card' in h and '2' in h: c_m['card_amt2'] = i
                elif 'card' in h and ('ref' in h or 'reference' in h): c_m['card_ref1'] = i
                elif 'card' in h: c_m['card_amt1'] = i
                elif 'cash' in h: c_m['cash_amt'] = i
                elif 'scheme' in h: c_m['gold_scheme_amt'] = i
                elif 'oldgold' in h or 'og' in h: c_m['og_amt'] = i

            sales_data = {}
            for row_idx, row in enumerate(wb[sales_sn].iter_rows(min_row=2, values_only=True), start=2):
                if not any(row):
                    continue
                r = list(row) + [None] * 50
                vou = _str(r[c_m.get('vou_no', 1)])
                if not vou:
                    continue
                raw_excel_val = r[c_m.get('vou_date', 3)]
                _logger.info("[SALE DATE DEBUG] Raw Excel value: %s, Type: %s", raw_excel_val, type(raw_excel_val))
                
                if hasattr(raw_excel_val, "strftime"):
                    vou_date = raw_excel_val.strftime("%Y-%m-%d")
                elif isinstance(raw_excel_val, (int, float)):
                    try:
                        vou_date = (datetime.datetime(1899, 12, 30) + datetime.timedelta(days=float(raw_excel_val))).strftime("%Y-%m-%d")
                    except Exception:
                        vou_date = str(raw_excel_val).strip().split(" ")[0]
                elif raw_excel_val:
                    raw_date_str = str(raw_excel_val).strip().split(" ")[0]
                    vou_date = raw_date_str
                    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d-%m-%y", "%d/%m/%y"):
                        try:
                            vou_date = datetime.datetime.strptime(raw_date_str, fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            pass
                else:
                    vou_date = ""
                
                _logger.info("[SALE DATE DEBUG] Converted value: %s", vou_date)

                entry = {
                    'row_idx':          row_idx,
                    'company_name':     _str(r[c_m.get('company', 38)]),
                    'branch_name':      _str(r[c_m.get('branch', 0)]),
                    'party_name':       _str(r[c_m.get('party', 2)]),
                    'vou_date':         vou_date,
                    'src_loc_name':     _str(r[c_m.get('src_loc', 4)]),
                    'product_var_name': _str(r[c_m.get('product_var', 5)]),
                    'label_no':         _str(r[c_m.get('label', 6)]),
                    'barcode_no':       _str(r[c_m.get('barcode', 7)]),
                    'salesman':         _str(r[c_m.get('salesman', 8)]),
                    'purity':           _str(r[c_m.get('purity', 9)]),
                    'pcs':              _flt(r[c_m.get('pcs', 10)]),
                    'gross_wt':         _flt(r[c_m.get('gross', 11)]),
                    'net_wt':           _flt(r[c_m.get('net', 12)]),
                    'diamond_wt':       _flt(r[c_m.get('dia_wt', 13)]),
                    'stone_wt':         _flt(r[c_m.get('st_wt', 14)]),
                    'metal_rate':       _flt(r[c_m.get('m_rate', 15)]),
                    'metal_amt':        _flt(r[c_m.get('m_amt', 16)]),
                    'mc_amt':           _flt(r[c_m.get('mc', 17)]),
                    'diamond_amt':      _flt(r[c_m.get('dia_amt', 18)]),
                    'stone_amt':        _flt(r[c_m.get('st_amt', 19)]),
                    'other_charge':     _flt(r[c_m.get('other', 20)]),
                    'taxes':            _str(r[c_m.get('tax', 22)]),
                    'bank_amt':         _flt(r[c_m.get('bank_amt', 25)]),
                    'bank_ref':         _str(r[c_m.get('bank_ref', 26)]),
                    'upi_amt1':         _flt(r[c_m.get('upi_amt1', 27)]),
                    'upi_ref1':         _str(r[c_m.get('upi_ref1', 28)]),
                    'upi_amt2':         _flt(r[c_m.get('upi_amt2', 29)]),
                    'upi_ref2':         _str(r[c_m.get('upi_ref2', 30)]),
                    'card_amt1':        _flt(r[c_m.get('card_amt1', 31)]),
                    'card_ref1':        _str(r[c_m.get('card_ref1', 32)]),
                    'card_amt2':        _flt(r[c_m.get('card_amt2', 33)]),
                    'card_ref2':        _str(r[c_m.get('card_ref2', 34)]),
                    'cash_amt':         _flt(r[c_m.get('cash_amt', 35)]),
                    'gold_scheme':      _flt(r[c_m.get('gold_scheme_amt', 36)]),
                    'og_amt':           _flt(r[c_m.get('og_amt', 37)]),
                }
                sales_data.setdefault(vou, []).append(entry)

            # Pre-parse OG sheet
            og_data = {}
            og_sheet_name = next((s for s in wb.sheetnames if s.strip().upper() in ('OG', 'OLD GOLD', 'OLD_GOLD')), None)
            if og_sheet_name:
                for row in wb[og_sheet_name].iter_rows(min_row=2, values_only=True):
                    if not any(row):
                        continue
                    r = list(row) + [None] * 20
                    vou = _str(r[2])  # col C = Sales Voucher No
                    if vou:
                        og_data.setdefault(vou, []).append({
                            'item_name':       _str(r[4]),
                            'carat':           _str(r[5]),
                            'gross_wt':        _flt(r[6]),
                            'net_wt':          _flt(r[7]),
                            'di_wt':           _flt(r[8]),
                            'di_amt':          _flt(r[9]),
                            'metal_rate':      _flt(r[10]),
                            'amount':          _flt(r[11]),
                            'branch_location': _str(r[12]),
                        })

            # Pre-parse GOLD SCHEME sheet
            scheme_data = {}
            scheme_sheet_name = next((s for s in wb.sheetnames if any(k in s.strip().upper() for k in ('GOLD SCHEME', 'GOLD_SCHEME', 'GOLDSCHEME', 'SCHEME'))), None)
            if scheme_sheet_name:
                for row in wb[scheme_sheet_name].iter_rows(min_row=2, values_only=True):
                    if not any(row):
                        continue
                    r = list(row) + [None] * 10
                    vou = _str(r[2])  # col C = Voucher No
                    if vou:
                        scheme_data[vou] = {
                            'customer':  _str(r[1]),
                            'ticket_no': _str(r[3]),
                            'amount':    _flt(r[4]),
                        }

            wb.close()

            all_vous = list(sales_data.keys())
            file_id = str(uuid.uuid4())
            tmp_path = f'/tmp/odoo_sale_{file_id}.json'
            with open(tmp_path, 'w') as f:
                json.dump({
                    'sales_data': sales_data,
                    'og_data': og_data,
                    'scheme_data': scheme_data,
                    'all_vous': all_vous,
                    'skipped_list': [],
                }, f)

            total = len(all_vous)
            return f"""<!DOCTYPE html><html><head><title>Processing Sales Import...</title>
<style>
body{{font-family:sans-serif;margin:40px;background:#f4f6f9;}}
.box{{max-width:860px;margin:auto;background:#fff;padding:24px;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,.12);}}
.pb{{width:100%;background:#e0e0e0;border-radius:4px;height:22px;overflow:hidden;margin:16px 0;}}
.pf{{width:0%;height:100%;background:#1a237e;transition:width .3s;}}
.log{{max-height:480px;overflow-y:auto;background:#1a1a2e;color:#a5d6a7;padding:12px;font-family:monospace;font-size:12px;line-height:1.5;border-radius:4px;margin-top:12px;}}
.stat{{display:flex;gap:24px;margin:8px 0;font-size:14px;}}
.ok{{color:#4caf50;font-weight:bold;}} .er{{color:#ef5350;font-weight:bold;}}
</style></head><body><div class="box">
<h2 style="color:#1a237e">Processing {total} Sale Vouchers</h2>
<p>Do NOT close this window. Processing in background batches.</p>
<div class="pb"><div class="pf" id="pf"></div></div>
<div class="stat"><span id="st">0 / {total}</span><span class="ok" id="ok_c">✔ 0</span><span class="er" id="er_c">✘ 0</span><span id="rate"></span></div>
<div class="log" id="log"></div>
<script>
let offset=0,lim=10,tot={total},fid='{file_id}',ok=0,errs=0,t0=Date.now();
function log(m){{let d=document.getElementById('log');d.innerHTML+='<div>'+m+'</div>';d.scrollTop=d.scrollHeight;}}
function upd(){{
  let pct=Math.min(100,Math.round(offset/tot*100));
  document.getElementById('pf').style.width=pct+'%';
  document.getElementById('st').innerText=Math.min(offset,tot)+' / '+tot;
  document.getElementById('ok_c').innerText='✔ '+ok;
  document.getElementById('er_c').innerText='✘ '+errs;
  let secs=((Date.now()-t0)/1000).toFixed(0);
  let rps=offset>0?(offset/((Date.now()-t0)/1000)).toFixed(1):'...';
  document.getElementById('rate').innerText=secs+'s | '+rps+'/s';
}}
function run(){{
  if(offset>=tot){{
    log('<br><b style="color:#80cbc4">✅ DONE! Success:'+ok+' Errors:'+errs+'</b>');
    if (window.skipped_count && window.skipped_count > 0) {{
        log('<br><a href="/import/sales_migration/skipped_pdf?file_id='+fid+'" target="_blank" style="background:#E53935;color:white;padding:10px 16px;text-decoration:none;font-weight:bold;border-radius:4px;display:inline-block;margin:10px 0;">📄 Download Unimported Sales Report ('+window.skipped_count+' skipped)</a>');
    }}
    log('<br><a href="/import/sales_migration/form" style="color:#80cbc4;font-weight:bold;">← Import Another File</a>');
    upd(); return;
  }}
  fetch('/import/sales_migration/chunk',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{params:{{file_id:fid,offset:offset,limit:lim}}}})
  }}).then(r=>r.json()).then(res=>{{
    if(res.error){{log('<span style="color:#ef9a9a">Server error: '+JSON.stringify(res.error)+'</span>');return;}}
    let d=res.result;
    ok+=(d.success_count||0);
    errs+=(d.errors||[]).length;
    window.skipped_count = d.skipped_count || window.skipped_count || 0;
    (d.errors||[]).forEach(e=>log('<span style="color:#ef9a9a">'+e+'</span>'));
    (d.logs||[]).forEach(m=>log(m));
    offset+=lim; upd();
    setTimeout(run, 50);
  }}).catch(e=>{{log('<span style="color:#ef9a9a">Network error: '+e+'</span>');setTimeout(run,3000);}});
}}
if(tot>0)run(); else log('No records found.');
</script></div></body></html>"""

        except Exception as e:
            _logger.exception("Import process initialization failed")
            return f"<h1 style='color:red'>Fatal Error</h1><pre>{e}</pre>"

    @http.route('/import/sales_migration/chunk', type='json', auth='user', methods=['POST'])
    def import_chunk(self, file_id, offset, limit, **kwargs):
        try:
            tmp_path = f'/tmp/odoo_sale_{file_id}.json'
            if not os.path.exists(tmp_path):
                return {'error': 'Session expired. Please re-upload the file.'}
            with open(tmp_path) as f:
                data = json.load(f)

            all_vous     = data['all_vous']
            sales_data   = data['sales_data']
            og_data      = data['og_data']
            scheme_data  = data['scheme_data']
            skipped_list = data.get('skipped_list', [])

            chunk = all_vous[offset: offset + limit]
            if not chunk:
                return {'success_count': 0, 'errors': [], 'logs': [], 'skipped_count': len(skipped_list)}

            env = request.env(context={
                'tracking_disable': True,
                'mail_notrack': True,
                'no_recompute': True,
                'mail_create_nosubscribe': True,
            })

            cache = self._build_cache(env, chunk, sales_data, og_data)

            success_count, error_log, logs = 0, [], []
            has_new_skipped = False

            for vou_no in chunk:
                _logger.info("[SALE IMPORT] Processing voucher: %s", vou_no)
                rows = sales_data.get(vou_no, [])
                try:
                    with env.cr.savepoint():
                        msg = self._process_sale_voucher(
                            env, vou_no, rows, og_data, scheme_data,
                            cache, skipped_list
                        )
                        logs.append(f"✔ {vou_no}: {msg}")
                        _logger.info("[SALE IMPORT] Voucher %s completed successfully", vou_no)
                    success_count += 1
                except Exception as e:
                    error_log.append(f"✘ Voucher {vou_no}: {e}")
                    _logger.error("[SALE IMPORT] Voucher %s failed: %s", vou_no, e, exc_info=True)
                    _logger.info("[SALE IMPORT] Rolled back voucher %s savepoint", vou_no)
                    _logger.info("[SALE IMPORT] Continuing with next voucher")

            # Persist skipped list changes if any
            if skipped_list != data.get('skipped_list', []):
                data['skipped_list'] = skipped_list
                with open(tmp_path, 'w') as f:
                    json.dump(data, f)

            # Free ORM cache between chunks to prevent memory bloat and connection issues
            env.invalidate_all()
            gc.collect()

            return {
                'success_count': success_count,
                'errors': error_log,
                'logs': logs,
                'skipped_count': len(skipped_list),
            }

        except Exception as e:
            _logger.exception("Chunk processing failed")
            return {'error': str(e)}

    # ── Bulk Lookup Cache ────────────────────────────────────────────────────
    def _build_cache(self, env, chunk, sales_data, og_data):
        companies = env['res.company'].search([])
        purities  = env['gold.purity'].search([])

        return {
            'companies':  {c.name.strip(): c for c in companies},
            'purities':   {p.name.strip(): p for p in purities},
            '_journals':  {},
        }

    @staticmethod
    def _find(cache_dict, key):
        if not key:
            return None
        hit = cache_dict.get(key)
        if hit:
            return hit
        key_l = key.lower()
        for k, v in cache_dict.items():
            if k.lower() == key_l:
                cache_dict[key] = v
                return v
        return None

    # ── Main Voucher Processor ───────────────────────────────────────────────
    def _process_sale_voucher(self, env, vou_no, rows, og_data, scheme_data, cache, skipped_list):
        if not rows:
            raise UserError(f"No SALES rows for voucher {vou_no}")

        hdr_row = rows[0]
        company_name    = hdr_row.get('company_name', '').strip()
        branch_name     = hdr_row.get('branch_name', '').strip()
        cust_name       = hdr_row.get('party_name', '').strip() or 'Unknown'
        date_str        = next((r.get('vou_date') for r in rows if r.get('vou_date')), '')
        source_loc_name = hdr_row.get('src_loc_name', '').strip()
        salesman_name   = hdr_row.get('salesman', '').strip()

        # 1. Resolve Company from Excel
        excel_company = self._find(cache['companies'], company_name)
        if not excel_company and company_name:
            excel_company = env['res.company'].search([
                '|', ('name', '=ilike', company_name), ('name', 'ilike', company_name)
            ], limit=1)
            if excel_company:
                cache['companies'][company_name] = excel_company

        if not excel_company:
            _logger.error("Voucher %s: Company '%s' could not be resolved in database. Voucher skipped.", vou_no, company_name)
            skipped_list.append({
                'row': hdr_row.get('row_idx', 0),
                'customer': cust_name,
                'label': vou_no,
                'reason': f"Company '{company_name}' not found"
            })
            raise ValidationError(f"Company '{company_name}' not found in database for voucher {vou_no}")

        # Set environment with the resolved company context
        c_env = excel_company.with_company(excel_company).with_context(
            allowed_company_ids=[excel_company.id],
            company_id=excel_company.id,
            default_company_id=excel_company.id,
        ).env

        # 2. Parse Date
        order_date = None
        if hasattr(date_str, "strftime"):
            order_date = date_str.strftime("%Y-%m-%d")
        elif date_str:
            raw_date = str(date_str).strip().split(" ")[0]
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d-%m-%y", "%d/%m/%y"):
                try:
                    order_date = datetime.datetime.strptime(raw_date, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    pass

        if not order_date:
            reason = "Effective Date is missing" if not date_str else f"Effective Date '{date_str}' is invalid"
            _logger.error("Voucher %s: %s. Voucher skipped.", vou_no, reason)
            skipped_list.append({
                'row': hdr_row.get('row_idx', 0),
                'customer': cust_name,
                'label': vou_no,
                'reason': reason
            })
            raise ValidationError(f"{reason} for voucher {vou_no}")

        # 3. Company-Dependent Header Lookups
        # Branch
        branch = None
        if branch_name:
            branch_cache = cache.setdefault(f'branches_{excel_company.id}', {})
            branch = self._find(branch_cache, branch_name)
            if not branch:
                branch = c_env['res.branch'].search([
                    ('name', '=ilike', branch_name),
                    ('company_id', '=', excel_company.id)
                ], limit=1)
                if not branch:
                    branch = c_env['res.branch'].search([
                        ('name', 'ilike', branch_name),
                        ('company_id', '=', excel_company.id)
                    ], limit=1)
                if branch:
                    branch_cache[branch_name] = branch

        # Warehouse
        warehouse = None
        if branch:
            warehouse = c_env['stock.warehouse'].sudo().search([
                ('branch_id', '=', branch.id),
                ('company_id', '=', excel_company.id),
            ], limit=1)
        if not warehouse:
            warehouse = c_env['stock.warehouse'].sudo().search([
                ('company_id', '=', excel_company.id),
            ], limit=1)

        # Partner
        partner_cache = cache.setdefault(f'partners_{excel_company.id}', {})
        partner = self._find(partner_cache, cust_name)
        if partner:
            partner = partner.with_env(c_env)
            if not partner.exists():
                partner = None
        if not partner and cust_name:
            partner = c_env['res.partner'].search([
                ('name', '=ilike', cust_name),
                ('company_id', 'in', [excel_company.id, False])
            ], limit=1)
            if not partner:
                partner = c_env['res.partner'].sudo().create({
                    'name': cust_name,
                    'customer_rank': 1,
                    'company_id': False
                })
            partner_cache[cust_name] = partner

        # Salesman
        salesman_cache = cache.setdefault(f'salesmen_{excel_company.id}', {})
        salesman = self._find(salesman_cache, salesman_name)
        if salesman:
            salesman = salesman.with_env(c_env)
            if not salesman.exists():
                salesman = None
        if not salesman and salesman_name:
            salesman = c_env['res.users'].search([
                ('name', '=ilike', salesman_name),
                ('company_ids', 'in', [excel_company.id])
            ], limit=1)
            if not salesman:
                salesman = c_env['res.users'].search([('name', '=ilike', salesman_name)], limit=1)
                if salesman:
                    if excel_company.id not in salesman.company_ids.ids:
                        salesman.sudo().write({'company_ids': [(4, excel_company.id)]})
                else:
                    login = salesman_name.strip().lower().replace(' ', '_')
                    if c_env['res.users'].search([('login', '=', login)]):
                        login = f"{login}_{str(uuid.uuid4())[:4]}"
                    salesman = c_env['res.users'].sudo().create({
                        'name': salesman_name,
                        'login': login,
                        'company_id': excel_company.id,
                        'company_ids': [(4, excel_company.id)],
                    })
            salesman_cache[salesman_name] = salesman

        # Source Location
        loc_cache = cache.setdefault(f'locations_{excel_company.id}', {})
        source_loc = self._find(loc_cache, source_loc_name)
        if not source_loc and source_loc_name:
            source_loc = c_env['stock.location'].search([
                ('complete_name', '=ilike', source_loc_name),
                ('usage', '=', 'internal'),
                ('company_id', '=', excel_company.id)
            ], limit=1)
            if not source_loc:
                source_loc = c_env['stock.location'].search([
                    ('name', '=ilike', source_loc_name),
                    ('usage', '=', 'internal'),
                    ('company_id', '=', excel_company.id)
                ], limit=1)
            if not source_loc:
                source_loc = c_env['stock.location'].search([
                    '|', ('complete_name', 'ilike', source_loc_name), ('name', 'ilike', source_loc_name),
                    ('usage', '=', 'internal'),
                    ('company_id', '=', excel_company.id)
                ], limit=1)
            if not source_loc:
                source_loc = c_env['stock.location'].search([
                    '|', ('complete_name', 'ilike', source_loc_name), ('name', 'ilike', source_loc_name),
                    ('usage', '=', 'internal'),
                    ('company_id', '=', False)
                ], limit=1)
            if source_loc:
                loc_cache[source_loc_name] = source_loc

        if not source_loc and branch and branch.branch_location_id:
            if not branch.branch_location_id.company_id or branch.branch_location_id.company_id.id == excel_company.id:
                source_loc = branch.branch_location_id

        if not source_loc and warehouse and warehouse.lot_stock_id:
            source_loc = warehouse.lot_stock_id

        # 4. Create Sale Order
        existing_order = c_env['sale.order'].sudo().search([
            ('origin', '=', vou_no),
            ('company_id', '=', excel_company.id)
        ], limit=1)

        if existing_order:
            _logger.info("[SALE IMPORT] Voucher: %s", vou_no)
            _logger.info("[SALE IMPORT] Searching existing sale order...")
            _logger.info("[SALE IMPORT] Existing sale order found: %s", existing_order.name)
            order = existing_order
            has_lines = bool(order.order_line)
            has_og_lines = bool(c_env['sale.old.gold.line'].sudo().search([('sale_id', '=', order.id)], limit=1))
        else:
            order_vals = {
                'partner_id':  partner.id if partner else False,
                'date_order':  order_date,
                'origin':      vou_no,
                'company_id':  excel_company.id,
            }
            if branch:
                order_vals['branch_id'] = branch.id
            if warehouse:
                order_vals['warehouse_id'] = warehouse.id
            if salesman:
                order_vals['user_id'] = salesman.id
            if source_loc:
                order_vals['branch_location_id'] = source_loc.id

            og_amt = max([_flt(r.get('og_amt', 0.0)) for r in rows] or [0.0])
            scheme_amt = max([_flt(r.get('gold_scheme', 0.0)) for r in rows] or [0.0])

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
                
            if scheme_amt > 0:
                order_vals['apply_scheme'] = True

            order = c_env['sale.order'].sudo().create(order_vals)
            has_lines = False
            has_og_lines = False

        # 5. Create Sale Order Lines
        label_bc_cache = cache.setdefault(f'labels_bc_{excel_company.id}', {})
        label_nm_cache = cache.setdefault(f'labels_nm_{excel_company.id}', {})
        prod_cache = cache.setdefault(f'products_{excel_company.id}', {})

        for row in rows:
            if has_lines:
                break
            product_var_name = row.get('product_var_name', '').strip()
            label_ref        = row.get('label_no', '').strip()
            barcode_no       = row.get('barcode_no', '').strip()
            purity_name      = row.get('purity', '').strip()
            gross_wt         = row.get('gross_wt', 0.0)
            diamond_wt       = row.get('diamond_wt', 0.0)
            stone_wt         = row.get('stone_wt', 0.0)
            metal_rate       = row.get('metal_rate', 0.0)
            metal_amt        = row.get('metal_amt', 0.0)
            mc_amt           = row.get('mc_amt', 0.0)
            diamond_amt      = row.get('diamond_amt', 0.0)
            stone_amt        = row.get('stone_amt', 0.0)
            other_charge     = row.get('other_charge', 0.0)

            if not label_ref and not barcode_no and not product_var_name:
                continue

            # Search Label scoped to excel_company
            label = None
            if barcode_no:
                label = label_bc_cache.get(barcode_no)
                if not label:
                    label = c_env['product.label'].search([
                        ('barcode', '=', barcode_no),
                        ('company_id', 'in', [excel_company.id, False])
                    ], limit=1)
                    if label:
                        label_bc_cache[barcode_no] = label

            if not label and label_ref:
                label = label_nm_cache.get(label_ref)
                if not label:
                    label = c_env['product.label'].search([
                        ('name', '=ilike', label_ref),
                        ('company_id', 'in', [excel_company.id, False])
                    ], limit=1)
                    if not label:
                        label = c_env['product.label'].search([
                            ('barcode', '=ilike', label_ref),
                            ('company_id', 'in', [excel_company.id, False])
                        ], limit=1)
                    if label:
                        label_nm_cache[label_ref] = label

            purity = cache['purities'].get(purity_name)
            if not purity and purity_name:
                purity = c_env['gold.purity'].search([('name', 'ilike', purity_name)], limit=1)
                if purity:
                    cache['purities'][purity_name] = purity
            if not purity and label:
                purity = label.purity_id

            # Resolve product strictly scoped to excel_company
            line_product = None
            if label and label.product_id:
                if not label.product_id.company_id or label.product_id.company_id.id == excel_company.id:
                    line_product = label.product_id
            if not line_product and label and label.product_tmpl_id:
                var = label.product_tmpl_id.product_variant_id
                if var and (not var.company_id or var.company_id.id == excel_company.id):
                    line_product = var

            if not line_product and product_var_name:
                line_product = self._find(prod_cache, product_var_name)
                if not line_product:
                    line_product = c_env['product.product'].search([
                        ('name', '=ilike', product_var_name),
                        ('company_id', 'in', [excel_company.id, False])
                    ], limit=1)
                    if not line_product:
                        line_product = c_env['product.product'].search([
                            ('default_code', '=ilike', product_var_name),
                            ('company_id', 'in', [excel_company.id, False])
                        ], limit=1)
                    if not line_product:
                        line_product = c_env['product.product'].search([
                            '|', ('name', 'ilike', product_var_name), ('default_code', 'ilike', product_var_name),
                            ('company_id', 'in', [excel_company.id, False])
                        ], limit=1)
                    if line_product:
                        prod_cache[product_var_name] = line_product

            if not line_product and label:
                prod_name_to_search = label.product_id.name if label.product_id else (label.product_tmpl_id.name if label.product_tmpl_id else None)
                if prod_name_to_search:
                    line_product = c_env['product.product'].search([
                        ('name', '=ilike', prod_name_to_search),
                        ('company_id', 'in', [excel_company.id, False])
                    ], limit=1)

            if label_ref and not label and not line_product:
                skipped_list.append({
                    'row': row.get('row_idx', 0),
                    'customer': cust_name,
                    'label': label_ref or barcode_no,
                    'reason': 'Label not found'
                })

            if not line_product:
                _logger.warning("Voucher %s row %s: Label %s / product %s could not be resolved for Company %s", vou_no, row.get('row_idx', 0), label_ref or barcode_no, product_var_name, excel_company.id)
                continue

            if label and not label.product_id and line_product:
                try:
                    label.sudo().write({'product_id': line_product.id})
                except Exception:
                    pass

            excel_tax_str = _str(row.get('taxes', ''))
            taxes = c_env['account.tax']
            if excel_tax_str:
                taxes = c_env['account.tax'].search([
                    ('name', 'ilike', excel_tax_str),
                    ('type_tax_use', '=', 'sale'),
                    ('company_id', '=', excel_company.id)
                ], limit=1)
            if not taxes:
                taxes = line_product.taxes_id.filtered(lambda t: t.company_id.id in (excel_company.id, False))

            line_vals = {
                'order_id':               order.id,
                'product_id':             line_product.id,
                'label_id':               label.id if label else False,
                'purity_id':              purity.id if purity else False,
                'product_uom_qty':        gross_wt or (label.sale_gross_weight if label else 0.0) or 1.0,
                'product_uom':            line_product.uom_id.id,
                'price_unit':             0.0,
                'sale_stone_weight':      stone_wt or (label.sale_stone_weight if label else 0.0),
                'sale_stone_weight_ct':   label.sale_stone_weight_ct if label else 0.0,
                'sale_diamond_weight_gm': diamond_wt or (label.sale_diamond_weight_gm if label else 0.0),
                'sale_diamond_weight_ct': label.sale_diamond_weight_ct if label else 0.0,
                'sale_stone_rate':        stone_amt or (label.sale_stone_rate if label else 0.0),
                'sale_diamond_rate':      diamond_amt or (label.sale_diamond_rate if label else 0.0),
                'other_weight_amount':    other_charge,
                'tax_id':                 [(6, 0, taxes.ids)] if taxes else [],
            }
            line = c_env['sale.order.line'].sudo().create(line_vals)

            if hasattr(line, '_onchange_label_id'):
                line._onchange_label_id()

            line_updates = {}
            if metal_rate > 0:
                line_updates['gold_rate'] = metal_rate

            target_metal = metal_amt if metal_amt > 0 else (metal_rate * (gross_wt or 1.0) if metal_rate else 0.0)
            if mc_amt > 0 and target_metal > 0:
                pct = (mc_amt / target_metal) * 100.0
                line_updates['mc_percent_actual'] = pct

            if line_updates:
                line.sudo().write(line_updates)

            if metal_amt > 0:
                c_env.cr.execute("UPDATE sale_order_line SET metal_amount = %s WHERE id = %s", (metal_amt, line.id))
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

        # 6. Apply Old Gold
        og_branch_loc_final = source_loc
        if og_amt > 0 and not has_og_lines:
            if not og_infos:
                og_infos = [{'amount': og_amt}]

            first_purity_name = _str(hdr_row.get('purity', ''))
            for og_info in og_infos:
                amt = og_info.get('amount', 0.0)
                if amt <= 0:
                    continue
                og_purity_name = og_info.get('carat', '') or first_purity_name

                og_purity = c_env['gold.purity']
                if og_purity_name:
                    og_purity = cache['purities'].get(og_purity_name)
                    if not og_purity:
                        og_purity = c_env['gold.purity'].search([('name', 'ilike', og_purity_name)], limit=1)
                        if og_purity:
                            cache['purities'][og_purity_name] = og_purity
                if not og_purity and order.order_line:
                    og_purity = order.order_line[0].purity_id
                if not og_purity:
                    og_purity = c_env['gold.purity'].search([], limit=1)

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
                og_branch_loc = c_env['stock.location']
                if og_branch_loc_name:
                    og_branch_loc = c_env['stock.location'].search([
                        ('complete_name', 'ilike', og_branch_loc_name),
                        ('usage', '=', 'internal'),
                        ('company_id', '=', excel_company.id),
                    ], limit=1)
                    if not og_branch_loc:
                        og_branch_loc = c_env['stock.location'].search([
                            ('complete_name', 'ilike', og_branch_loc_name),
                            ('usage', '=', 'internal'),
                            ('company_id', '=', False),
                        ], limit=1)
                if not og_branch_loc and source_loc:
                    og_branch_loc = source_loc
                if not og_branch_loc and warehouse and warehouse.lot_stock_id:
                    og_branch_loc = warehouse.lot_stock_id

                if og_branch_loc:
                    og_branch_loc_final = og_branch_loc
                    order.branch_location_id = og_branch_loc.id

                c_env['sale.old.gold.line'].sudo().create({
                    'sale_id':      order.id,
                    'purity_id':    og_purity.id,
                    'gross_weight': og_gross or (amt / og_rate if og_rate else 0.0),
                    'stone_weight': og_stone,
                    'rate':         og_rate,
                    'amount':       amt,
                })

            try:
                if not order.purchase_order_id:
                    order.with_company(excel_company).with_context(
                        skip_old_gold_amount_compute=True,
                        default_company_id=excel_company.id,
                        company_id=excel_company.id,
                        allowed_company_ids=[excel_company.id],
                    ).action_apply_old_gold()
                if order_date:
                    date_only = order_date.date() if isinstance(order_date, datetime.datetime) else order_date
                    order.invalidate_recordset(['purchase_order_id', 'old_gold_bill_id'])
                    po = order.purchase_order_id
                    if po:
                        c_env.flush_all()
                        c_env.cr.execute("UPDATE purchase_order SET date_order = %s, date_approve = %s, date_planned = %s, effective_date = %s WHERE id = %s", (order_date, order_date, order_date, order_date, po.id))
                        c_env.cr.execute("UPDATE purchase_order_line SET date_planned = %s WHERE order_id = %s", (order_date, po.id))
                        po.invalidate_recordset(['date_order', 'date_approve', 'date_planned', 'effective_date'])
                        po.order_line.invalidate_recordset(['date_planned'])
                        
                        bills = po.invoice_ids
                        if hasattr(order, 'old_gold_bill_id') and order.old_gold_bill_id:
                            bills |= order.old_gold_bill_id
                        for bill in bills:
                            c_env.cr.execute("UPDATE account_move SET invoice_date = %s, invoice_date_due = %s, date = %s WHERE id = %s", (date_only, date_only, date_only, bill.id))
                            bill.invalidate_recordset(['invoice_date', 'invoice_date_due', 'date'])
            except Exception as e:
                _logger.warning("Voucher %s: Old Gold apply failed: %s", vou_no, e)
                raise


        # 8. Strict Pre-Confirmation Company Validation & Logging
        order_comp = order.company_id.id
        wh_comp = order.warehouse_id.company_id.id if order.warehouse_id else None
        picking_type = order.warehouse_id.out_type_id if order.warehouse_id else None
        picking_type_comp = picking_type.company_id.id if (picking_type and picking_type.company_id) else None
        src_loc = order.branch_location_id or (order.warehouse_id.lot_stock_id if order.warehouse_id else None)
        src_loc_comp = src_loc.company_id.id if (src_loc and src_loc.company_id) else None
        dest_loc = (order.partner_id.property_stock_customer if order.partner_id else None) or c_env.ref('stock.stock_location_customers', raise_if_not_found=False)
        dest_loc_comp = dest_loc.company_id.id if (dest_loc and dest_loc.company_id) else None
        branch_comp = order.branch_id.company_id.id if (order.branch_id and order.branch_id.company_id) else None

        invalid_prod_msgs = []
        prod_names = []
        for line in order.order_line:
            p = line.product_id
            if p:
                prod_names.append(p.display_name)
                if p.company_id and p.company_id.id != excel_company.id:
                    invalid_prod_msgs.append(f"Product '{p.display_name}' belongs to Company '{p.company_id.name}' (ID: {p.company_id.id})")

        # Logging as strictly required
        _logger.info(
            "Voucher: %s\n"
            "Company from Excel: %s\n"
            "Sale Order Company: %s\n"
            "Warehouse: %s\n"
            "Picking Type: %s\n"
            "Source Location: %s\n"
            "Destination Location: %s\n"
            "Product: %s\n"
            "Current Context Company: %s\n"
            "Allowed Companies: %s",
            vou_no,
            excel_company.name,
            order.company_id.name if order.company_id else 'None',
            order.warehouse_id.name if order.warehouse_id else 'None',
            picking_type.name if picking_type else 'None',
            src_loc.complete_name if src_loc else 'None',
            dest_loc.complete_name if dest_loc else 'None',
            ', '.join(prod_names) if prod_names else 'None',
            c_env.company.name if c_env.company else 'None',
            c_env.context.get('allowed_company_ids', [])
        )

        mismatches = []
        if not order.warehouse_id:
            mismatches.append(f"No warehouse found for Company '{excel_company.name}' (ID: {excel_company.id})")
        elif wh_comp != excel_company.id:
            mismatches.append(f"Warehouse '{order.warehouse_id.name}' belongs to Company ID {wh_comp}, expected {excel_company.id}")

        if picking_type_comp and picking_type_comp != excel_company.id:
            mismatches.append(f"Picking Type '{picking_type.name}' belongs to Company ID {picking_type_comp}, expected {excel_company.id}")

        if src_loc_comp and src_loc_comp != excel_company.id:
            mismatches.append(f"Source Location '{src_loc.complete_name}' belongs to Company ID {src_loc_comp}, expected {excel_company.id}")

        if dest_loc_comp and dest_loc_comp != excel_company.id:
            mismatches.append(f"Destination Location '{dest_loc.complete_name}' belongs to Company ID {dest_loc_comp}, expected {excel_company.id}")

        if branch_comp and branch_comp != excel_company.id:
            mismatches.append(f"Branch '{order.branch_id.name}' belongs to Company ID {branch_comp}, expected {excel_company.id}")

        if invalid_prod_msgs:
            mismatches.extend(invalid_prod_msgs)

        if mismatches:
            error_details = "\n".join(mismatches)
            _logger.error(
                "Company mismatch detected for voucher %s:\n%s\nVoucher skipped.",
                vou_no, error_details
            )
            skipped_list.append({
                'row': hdr_row.get('row_idx', 0),
                'customer': cust_name,
                'label': vou_no,
                'reason': f"Company mismatch: {'; '.join(mismatches)}"
            })
            raise ValidationError(f"Company mismatch on voucher {vou_no}:\n{error_details}")

        # 9. Confirm Order
        order.with_company(excel_company).with_context(
            mail_notrack=True,
            default_company_id=excel_company.id,
            company_id=excel_company.id,
            allowed_company_ids=[excel_company.id],
        ).action_confirm()
        if order_date:
            order.sudo().write({'date_order': order_date})
            c_env.cr.execute("UPDATE sale_order SET create_date = %s WHERE id = %s", (order_date, order.id))

        # 10. Validate Stock Delivery
        for picking in order.picking_ids:
            if picking.state == 'cancel':
                continue
            if order_date:
                c_env.flush_all()
                c_env.cr.execute("UPDATE stock_picking SET scheduled_date = %s WHERE id = %s", (order_date, picking.id))
                picking.invalidate_recordset(['scheduled_date'])

            if picking.state != 'done':
                if picking.picking_type_code == 'outgoing' and source_loc:
                    picking.location_id = source_loc.id
                    for move in picking.move_ids:
                        move.location_id = source_loc.id
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    if hasattr(move, 'picked'):
                        move.picked = True
                try:
                    res = picking.with_company(excel_company).with_context(
                        skip_backorder=True,
                        cancel_backorder=True,
                        skip_sms=True,
                        default_company_id=excel_company.id,
                        company_id=excel_company.id,
                        allowed_company_ids=[excel_company.id],
                    ).button_validate()
                    if isinstance(res, dict):
                        model = res.get('res_model', '')
                        ctx = res.get('context', {})
                        if model == 'stock.immediate.transfer':
                            wiz = c_env['stock.immediate.transfer'].with_context(ctx).create({'pick_ids': [(4, picking.id)]})
                            wiz.process()
                        elif model == 'stock.backorder.confirmation':
                            wiz = c_env['stock.backorder.confirmation'].with_context(ctx).create({'pick_ids': [(4, picking.id)]})
                            wiz.process()
                except Exception as e:
                    _logger.warning("Voucher %s: Delivery validate failed: %s", vou_no, e)
                    raise

            if order_date:
                c_env.flush_all()
                c_env.cr.execute("UPDATE stock_picking SET date_done = %s, date = %s WHERE id = %s", (order_date, order_date, picking.id))
                c_env.cr.execute("UPDATE stock_move SET date = %s WHERE picking_id = %s", (order_date, picking.id))
                c_env.cr.execute("UPDATE stock_move_line SET date = %s WHERE picking_id = %s", (order_date, picking.id))
                picking.invalidate_recordset(['date_done', 'date'])
                picking.move_ids.invalidate_recordset(['date'])
                picking.move_line_ids.invalidate_recordset(['date'])
                order.sudo().write({'effective_date': order_date})

        # Validate Old Gold Delivery
        if order.purchase_order_id:
            for picking in order.purchase_order_id.picking_ids:
                if picking.state == 'cancel':
                    continue
                if order_date:
                    c_env.flush_all()
                    c_env.cr.execute("UPDATE stock_picking SET scheduled_date = %s WHERE id = %s", (order_date, picking.id))
                    picking.invalidate_recordset(['scheduled_date'])

                if picking.state != 'done':
                    if og_branch_loc_final:
                        picking.location_dest_id = og_branch_loc_final.id
                        for move in picking.move_ids:
                            move.location_dest_id = og_branch_loc_final.id
                    for move in picking.move_ids:
                        move.quantity = move.product_uom_qty
                        if hasattr(move, 'picked'):
                            move.picked = True
                    try:
                        res = picking.with_company(excel_company).with_context(
                            skip_backorder=True,
                            cancel_backorder=True,
                            skip_sms=True,
                            default_company_id=excel_company.id,
                            company_id=excel_company.id,
                            allowed_company_ids=[excel_company.id],
                        ).button_validate()
                        if isinstance(res, dict):
                            model = res.get('res_model', '')
                            ctx = res.get('context', {})
                            if model == 'stock.immediate.transfer':
                                wiz = c_env['stock.immediate.transfer'].with_context(ctx).create({'pick_ids': [(4, picking.id)]})
                                wiz.process()
                            elif model == 'stock.backorder.confirmation':
                                wiz = c_env['stock.backorder.confirmation'].with_context(ctx).create({'pick_ids': [(4, picking.id)]})
                                wiz.process()
                    except Exception as e:
                        _logger.warning("Voucher %s: Old Gold Delivery validate failed: %s", vou_no, e)
                        raise

                if order_date:
                    c_env.flush_all()
                    c_env.cr.execute("UPDATE stock_picking SET date_done = %s, date = %s WHERE id = %s", (order_date, order_date, picking.id))
                    c_env.cr.execute("UPDATE stock_move SET date = %s WHERE picking_id = %s", (order_date, picking.id))
                    c_env.cr.execute("UPDATE stock_move_line SET date = %s WHERE picking_id = %s", (order_date, picking.id))
                    picking.invalidate_recordset(['date_done', 'date'])
                    picking.move_ids.invalidate_recordset(['date'])
                    picking.move_line_ids.invalidate_recordset(['date'])

        # 11. Invoice
        if not order.order_line:
            return f"SO {order.name} OK (No Lines)"

        _logger.info("[SALE IMPORT] Voucher: %s", vou_no)
        _logger.info("[SALE IMPORT] Searching existing accounting move...")
        
        existing_move = order.invoice_ids.filtered(lambda inv: inv.move_type in ('out_invoice', 'out_refund') and inv.state != 'cancel')
        if not existing_move:
            existing_move = c_env['account.move'].search([
                ('ref', '=', vou_no),
                ('company_id', '=', excel_company.id),
                ('move_type', 'in', ['out_invoice', 'out_refund', 'in_invoice', 'in_refund'])
            ], limit=1)

        if existing_move:
            invoice = existing_move[0]
            _logger.info("[SALE IMPORT] Journal: %s", invoice.journal_id.id if invoice.journal_id else 'None')
            _logger.info("[SALE IMPORT] Existing move found: %s", invoice.name)
            _logger.info("[SALE IMPORT] Reusing existing move. No duplicate created.")
        else:
            _logger.info("[SALE IMPORT] No existing move found; using existing Odoo creation logic")
            invoice = order.with_company(excel_company).with_context(
                default_company_id=excel_company.id,
                company_id=excel_company.id,
                allowed_company_ids=[excel_company.id],
            )._create_invoices()
            _logger.info("[SALE IMPORT] Accounting move created: %s", invoice.name if invoice else 'None')

        if not invoice:
            return f"SO {order.name} OK (No Invoice)"

        inv_vals = {}
        if order_date:
            date_only = order_date.date() if isinstance(order_date, datetime.datetime) else order_date
            inv_vals['invoice_date'] = date_only
            inv_vals['invoice_date_due'] = date_only
            inv_vals['date'] = date_only
            inv_vals['delivery_date'] = date_only
        if vou_no:
            inv_vals['ref'] = vou_no

        if inv_vals:
            invoice.write(inv_vals)

        if invoice.state == 'draft':
            try:
                invoice.with_company(excel_company).with_context(
                    default_company_id=excel_company.id,
                    company_id=excel_company.id,
                    allowed_company_ids=[excel_company.id],
                ).action_post()
                _logger.info("[SALE IMPORT] Voucher %s: Successfully posted invoice %s", vou_no, invoice.name)
            except Exception as e:
                _logger.error("[SALE IMPORT] Voucher %s: Failed to post invoice %s for customer %s. Error: %s", vou_no, invoice.name, invoice.partner_id.name, e)
                raise

        if hasattr(invoice, 'custom_total') and invoice.custom_total < 0:
            try:
                invoice.action_create_old_gold_vendor_payment()
            except Exception as e:
                _logger.warning("Voucher %s: Customer Payment creation failed: %s", vou_no, e)
                raise

        # Fetch all companies to mimic Administrator UI visibility for cross-company schemes
        all_company_ids = c_env['res.company'].sudo().search([]).ids
        
        # Check if the invoice actually has an outstanding scheme payment credit (matching UI visibility)
        outstanding_scheme_lines = invoice.sudo().with_company(excel_company).with_context(
            allowed_company_ids=all_company_ids,
        )._get_outstanding_scheme_payment_lines()
        
        has_outstanding = bool(outstanding_scheme_lines)
        
        if scheme_amt > 0:
            try:
                if has_outstanding:
                    _logger.info("Voucher %s: Detected outstanding scheme credit for customer %s. Automatically redeeming...", vou_no, invoice.partner_id.name)
                else:
                    _logger.warning("Voucher %s: Excel specifies scheme amount, but no eligible outstanding scheme credit was found for customer %s.", vou_no, invoice.partner_id.name)

                # Execute redemption with sudo and all companies to match UI visibility and cross-company branch rules
                invoice.sudo().with_company(excel_company).with_context(
                    default_company_id=excel_company.id,
                    company_id=excel_company.id,
                    allowed_company_ids=all_company_ids,
                ).action_redeem_outstanding_schemes()
                
            except UserError as e:
                _logger.error("Voucher %s: UserError during scheme redemption: %s. Customer: %s, Invoice: %s", vou_no, e, invoice.partner_id.name, invoice.name)
                # DO NOT raise here. We want the migration to proceed and not fail the voucher!
            except Exception as e:
                _logger.error("Voucher %s: Unexpected error during scheme redemption: %s", vou_no, e, exc_info=True)
                # DO NOT raise here. We want the migration to proceed and not fail the voucher!

        # 12. Payments
        self._register_payments(c_env, order, invoice, rows, order_date, cache, excel_company)

        return f"SO {order.name} OK"

    # ── Payment Helper ────────────────────────────────────────────────────────
    def _register_payments(self, env, order, invoice, rows, pay_date, cache, excel_company):
        branch = order.branch_id
        journal_cache = cache.setdefault('_journals', {})

        def find_journal(jtype, hint=''):
            key = f"{excel_company.id}_{jtype}_{hint}_{branch.id if branch else 0}"
            if key in journal_cache:
                return journal_cache[key]

            base_domain = [('type', '=', jtype), ('company_id', '=', excel_company.id)]
            hint_domain = [('name', 'ilike', hint)] if hint else []
            branch_domain = [('branch_id', '=', branch.id)] if branch else []

            # 1. Match Type + Branch + Hint
            j = env['account.journal'].search(base_domain + branch_domain + hint_domain, limit=1)
            # 2. Match Type + Hint
            if not j and hint:
                j = env['account.journal'].search(base_domain + hint_domain, limit=1)
            # 3. Match Type + Branch
            if not j and branch:
                j = env['account.journal'].search(base_domain + branch_domain, limit=1)
            # 4. Match Type
            if not j:
                j = env['account.journal'].search(base_domain, limit=1)

            journal_cache[key] = j
            return j

        def pay(amount, jtype, hint='', ref=''):
            if not amount or amount <= 0:
                return
            journal = find_journal(jtype, hint)
            if not journal:
                _logger.warning("Voucher %s: Journal not found type=%s hint=%s for Company %s", invoice.ref, jtype, hint, excel_company.id)
                return
            try:
                wiz_vals = {
                    'amount': amount,
                    'journal_id': journal.id,
                    'payment_date': pay_date,
                }
                if ref:
                    wiz_vals['communication'] = ref
                if 'bank_reference' in env['account.payment.register']._fields and ref:
                    wiz_vals['bank_reference'] = ref

                wiz = env['account.payment.register'].with_context(
                    active_model='account.move', active_ids=invoice.ids
                ).create(wiz_vals)

                # Overwrite amount before generating payment
                wiz.amount = amount
                payments = wiz.action_create_payments()
                if payments and hasattr(payments, 'bank_reference') and ref:
                    payments.write({'bank_reference': ref})
            except Exception as e:
                _logger.warning("Voucher %s: Payment failed %s/%s: %s", invoice.ref, jtype, hint, e)
                raise

        try:
            bank_amt  = max([_flt(r.get('bank_amt', 0)) for r in rows] or [0])
            bank_ref  = next((_str(r.get('bank_ref', '')) for r in rows if _str(r.get('bank_ref', ''))), '')
            upi_amt1  = max([_flt(r.get('upi_amt1', 0)) for r in rows] or [0])
            upi_ref1  = next((_str(r.get('upi_ref1', '')) for r in rows if _str(r.get('upi_ref1', ''))), '')
            upi_amt2  = max([_flt(r.get('upi_amt2', 0)) for r in rows] or [0])
            upi_ref2  = next((_str(r.get('upi_ref2', '')) for r in rows if _str(r.get('upi_ref2', ''))), '')
            card_amt1 = max([_flt(r.get('card_amt1', 0)) for r in rows] or [0])
            card_ref1 = next((_str(r.get('card_ref1', '')) for r in rows if _str(r.get('card_ref1', ''))), '')
            card_amt2 = max([_flt(r.get('card_amt2', 0)) for r in rows] or [0])
            card_ref2 = next((_str(r.get('card_ref2', '')) for r in rows if _str(r.get('card_ref2', ''))), '')
            cash_amt  = max([_flt(r.get('cash_amt', 0)) for r in rows] or [0])

            pay(bank_amt,  'bank', 'bank', bank_ref)
            pay(upi_amt1,  'bank', 'upi',  upi_ref1)
            pay(upi_amt2,  'bank', 'upi',  upi_ref2)
            pay(card_amt1, 'bank', 'card', card_ref1)
            pay(card_amt2, 'bank', 'card', card_ref2)
            pay(cash_amt,  'cash', '',     '')
        except Exception as e:
            _logger.warning("Voucher %s: Register payments exception: %s", invoice.ref, e)
            raise

    # ── Skipped PDF Download Route ────────────────────────────────────────────
    @http.route('/import/sales_migration/skipped_pdf', type='http', auth='user')
    def download_skipped_pdf(self, file_id, **kw):
        fpath = f'/tmp/odoo_sale_{file_id}.json'
        if not os.path.exists(fpath):
            return request.not_found("File expired or not found")

        with open(fpath, 'r') as f:
            data = json.load(f)

        skipped_list = data.get('skipped_list', [])
        pdf = self._generate_skipped_pdf(skipped_list)

        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'attachment; filename="unimported_sales_{file_id}.pdf"')
        ]
        return request.make_response(pdf, headers=headers)

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
            data.append([Paragraph(str(item.get('row', '')), ns), Paragraph(str(item.get('customer') or ''), ns),
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
