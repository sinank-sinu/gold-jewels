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
                if 'branch' in h: c_m['branch'] = i
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
                vou_date = r[c_m.get('vou_date', 3)]
                if isinstance(vou_date, (datetime.datetime, datetime.date)):
                    vou_date = vou_date.date().isoformat() if isinstance(vou_date, datetime.datetime) else vou_date.isoformat()
                elif isinstance(vou_date, (int, float)):
                    try:
                        vou_date = (datetime.datetime(1899, 12, 30) + datetime.timedelta(days=float(vou_date))).date().isoformat()
                    except Exception:
                        vou_date = str(vou_date)
                else:
                    vou_date = _str(vou_date)

                entry = {
                    'row_idx':          row_idx,
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
                rows = sales_data.get(vou_no, [])
                try:
                    with env.cr.savepoint():
                        msg = self._process_sale_voucher(
                            env, vou_no, rows, og_data, scheme_data,
                            cache, skipped_list
                        )
                        logs.append(f"✔ {vou_no}: {msg}")
                    success_count += 1
                except Exception as e:
                    error_log.append(f"✘ Voucher {vou_no}: {e}")
                    _logger.exception("Voucher %s failed: %s", vou_no, e)

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
        partner_names, salesman_names, branch_names = set(), set(), set()
        barcodes, label_names, product_names = set(), set(), set()
        purity_names, location_names = set(), set()

        for vou in chunk:
            for r in sales_data.get(vou, []):
                if r.get('party_name'):       partner_names.add(r['party_name'].strip())
                if r.get('salesman'):         salesman_names.add(r['salesman'].strip())
                if r.get('branch_name'):      branch_names.add(r['branch_name'].strip())
                if r.get('barcode_no'):       barcodes.add(r['barcode_no'].strip())
                if r.get('label_no'):         label_names.add(r['label_no'].strip())
                if r.get('product_var_name'): product_names.add(r['product_var_name'].strip())
                if r.get('purity'):           purity_names.add(r['purity'].strip())
                if r.get('src_loc_name'):     location_names.add(r['src_loc_name'].strip())
            for og in og_data.get(vou, []):
                if og.get('carat'):           purity_names.add(og['carat'].strip())
                if og.get('branch_location'): location_names.add(og['branch_location'].strip())

        partners  = env['res.partner'].search([('name', 'in', list(partner_names))]) if partner_names else env['res.partner'].browse()
        salesmen  = env['res.users'].search([('name', 'in', list(salesman_names))]) if salesman_names else env['res.users'].browse()
        branches  = env['res.branch'].search([('name', 'in', list(branch_names))]) if branch_names else env['res.branch'].browse()
        purities  = env['gold.purity'].search([])
        labels_bc = env['product.label'].search([('barcode', 'in', list(barcodes))]) if barcodes else env['product.label'].browse()
        labels_nm = env['product.label'].search([('name', 'in', list(label_names))]) if label_names else env['product.label'].browse()
        all_labels = labels_bc | labels_nm
        products  = env['product.product'].search([('name', 'in', list(product_names))]) if product_names else env['product.product'].browse()

        return {
            'partners':   {p.name.strip(): p for p in partners},
            'salesmen':   {u.name.strip(): u for u in salesmen},
            'branches':   {b.name.strip(): b for b in branches},
            'purities':   {p.name.strip(): p for p in purities},
            'labels_bc':  {l.barcode: l for l in all_labels if l.barcode},
            'labels_nm':  {l.name: l for l in all_labels},
            'products':   {p.name.strip(): p for p in products},
            'locations':  {},
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
        branch_name     = hdr_row.get('branch_name', '').strip()
        cust_name       = hdr_row.get('party_name', '').strip() or 'Unknown'
        date_str        = next((r.get('vou_date') for r in rows if r.get('vou_date')), '')
        source_loc_name = hdr_row.get('src_loc_name', '').strip()
        salesman_name   = hdr_row.get('salesman', '').strip()

        # 1. Parse Date
        order_date = fields.Datetime.now()
        if date_str:
            try:
                from dateutil import parser
                order_date = parser.parse(date_str, dayfirst=True)
            except Exception:
                order_date = fields.Datetime.now()

        # 2. Header Lookups
        branch = self._find(cache['branches'], branch_name)
        if not branch and branch_name:
            branch = env['res.branch'].search([('name', 'ilike', branch_name)], limit=1)
            if branch:
                cache['branches'][branch_name] = branch

        partner = self._find(cache['partners'], cust_name)
        if not partner and cust_name:
            partner = env['res.partner'].search([('name', '=ilike', cust_name)], limit=1)
            if not partner:
                partner = env['res.partner'].sudo().create({'name': cust_name, 'customer_rank': 1})
            cache['partners'][cust_name] = partner

        salesman = self._find(cache['salesmen'], salesman_name)
        if not salesman and salesman_name:
            salesman = env['res.users'].search([('name', '=ilike', salesman_name)], limit=1)
            if not salesman:
                login = salesman_name.strip().lower().replace(' ', '_')
                if env['res.users'].search([('login', '=', login)]):
                    login = f"{login}_{str(uuid.uuid4())[:4]}"
                salesman = env['res.users'].sudo().create({
                    'name': salesman_name,
                    'login': login,
                })
            cache['salesmen'][salesman_name] = salesman

        source_loc = self._find(cache['locations'], source_loc_name)
        if not source_loc and source_loc_name:
            source_loc = env['stock.location'].search([
                '|', ('complete_name', 'ilike', source_loc_name), ('name', 'ilike', source_loc_name),
                ('usage', '=', 'internal')
            ], limit=1)
            if source_loc:
                cache['locations'][source_loc_name] = source_loc
        if not source_loc and branch:
            source_loc = branch.branch_location_id

        # 3. Create Sale Order
        order_vals = {
            'partner_id': partner.id if partner else False,
            'date_order': order_date,
            'origin':     vou_no,
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

        order = env['sale.order'].sudo().create(order_vals)

        # 4. Create Sale Order Lines
        for row in rows:
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

            label = (cache['labels_bc'].get(barcode_no) or cache['labels_nm'].get(label_ref))
            if not label and label_ref:
                label = env['product.label'].search(['|', ('name', '=ilike', label_ref), ('barcode', '=ilike', label_ref)], limit=1)
                if label:
                    cache['labels_nm'][label_ref] = label

            purity = cache['purities'].get(purity_name)
            if not purity and purity_name:
                purity = env['gold.purity'].search([('name', 'ilike', purity_name)], limit=1)
                if purity:
                    cache['purities'][purity_name] = purity
            if not purity and label:
                purity = label.purity_id

            line_product = None
            if label:
                line_product = label.product_id or (label.product_tmpl_id.product_variant_id if label.product_tmpl_id else None)
            if not line_product and product_var_name:
                line_product = cache['products'].get(product_var_name)
                if not line_product:
                    line_product = env['product.product'].search(['|', ('name', 'ilike', product_var_name), ('display_name', 'ilike', product_var_name)], limit=1)
                    if line_product:
                        cache['products'][product_var_name] = line_product

            if label_ref and not label and not line_product:
                skipped_list.append({
                    'row': row.get('row_idx', 0),
                    'customer': cust_name,
                    'label': label_ref or barcode_no,
                    'reason': 'Label not found'
                })

            if not line_product:
                _logger.warning("Voucher %s row %s: Label %s / product %s could not be resolved", vou_no, row.get('row_idx', 0), label_ref or barcode_no, product_var_name)
                continue

            if label and not label.product_id and line_product:
                try:
                    label.sudo().write({'product_id': line_product.id})
                except Exception:
                    pass

            excel_tax_str = _str(row.get('taxes', ''))
            taxes = env['account.tax']
            if excel_tax_str:
                taxes = env['account.tax'].search([
                    ('name', 'ilike', excel_tax_str),
                    ('type_tax_use', '=', 'sale'),
                    ('company_id', '=', env.company.id)
                ], limit=1)
            if not taxes:
                taxes = line_product.taxes_id.filtered(lambda t: t.company_id == env.company)

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
            line = env['sale.order.line'].sudo().create(line_vals)

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

        # 5. Apply Old Gold
        og_branch_loc_final = source_loc
        if og_amt > 0:
            if not og_infos:
                og_infos = [{'amount': og_amt}]

            first_purity_name = _str(hdr_row.get('purity', ''))
            for og_info in og_infos:
                amt = og_info.get('amount', 0.0)
                if amt <= 0:
                    continue
                og_purity_name = og_info.get('carat', '') or first_purity_name

                og_purity = env['gold.purity']
                if og_purity_name:
                    og_purity = cache['purities'].get(og_purity_name)
                    if not og_purity:
                        og_purity = env['gold.purity'].search([('name', 'ilike', og_purity_name)], limit=1)
                        if og_purity:
                            cache['purities'][og_purity_name] = og_purity
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

                env['sale.old.gold.line'].sudo().create({
                    'sale_id':      order.id,
                    'purity_id':    og_purity.id,
                    'gross_weight': og_gross or (amt / og_rate if og_rate else 0.0),
                    'stone_weight': og_stone,
                    'rate':         og_rate,
                    'amount':       amt,
                })

            try:
                order.with_context(skip_old_gold_amount_compute=True).action_apply_old_gold()
                if order_date:
                    date_only = order_date.date() if isinstance(order_date, datetime.datetime) else order_date
                    if order.purchase_order_id:
                        order.purchase_order_id.sudo().write({
                            'date_order': order_date,
                            'date_approve': order_date,
                        })
                    if hasattr(order, 'old_gold_bill_id') and order.old_gold_bill_id:
                        env.cr.execute("""
                            UPDATE account_move 
                            SET invoice_date = %s, date = %s, invoice_date_due = %s, delivery_date = %s 
                            WHERE id = %s
                        """, (date_only, date_only, date_only, date_only, order.old_gold_bill_id.id))
                    elif order.purchase_order_id and order.purchase_order_id.invoice_ids:
                        for bill in order.purchase_order_id.invoice_ids:
                            env.cr.execute("""
                                UPDATE account_move 
                                SET invoice_date = %s, date = %s, invoice_date_due = %s, delivery_date = %s 
                                WHERE id = %s
                            """, (date_only, date_only, date_only, date_only, bill.id))
            except Exception as e:
                _logger.warning("Voucher %s: Old Gold apply failed: %s", vou_no, e)

        # 6. Apply Scheme
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

        # 7. Confirm Order
        original_date = order.date_order
        order.with_context(mail_notrack=True).action_confirm()
        if original_date:
            order.sudo().write({'date_order': original_date})
            env.cr.execute("UPDATE sale_order SET create_date = %s WHERE id = %s", (original_date, order.id))

        # 8. Validate Stock Delivery
        for picking in order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
            if order_date:
                picking.sudo().write({'scheduled_date': order_date})
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

            if order_date:
                env.cr.execute("UPDATE stock_picking SET date_done = %s, date = %s WHERE id = %s", (order_date, order_date, picking.id))
                env.cr.execute("UPDATE stock_move SET date = %s WHERE picking_id = %s", (order_date, picking.id))
                env.cr.execute("UPDATE stock_move_line SET date = %s WHERE picking_id = %s", (order_date, picking.id))

        # Validate Old Gold Delivery
        if order.purchase_order_id:
            for picking in order.purchase_order_id.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                if order_date:
                    picking.sudo().write({'scheduled_date': order_date})
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

                if order_date:
                    env.cr.execute("UPDATE stock_picking SET date_done = %s, date = %s WHERE id = %s", (order_date, order_date, picking.id))
                    env.cr.execute("UPDATE stock_move SET date = %s WHERE picking_id = %s", (order_date, picking.id))
                    env.cr.execute("UPDATE stock_move_line SET date = %s WHERE picking_id = %s", (order_date, picking.id))

        # 9. Invoice
        if not order.order_line:
            return f"SO {order.name} OK (No Lines)"

        invoice = order._create_invoices()
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

        invoice.action_post()

        if hasattr(invoice, 'custom_total') and invoice.custom_total < 0:
            try:
                invoice.action_create_old_gold_vendor_payment()
            except Exception as e:
                _logger.warning("Voucher %s: Customer Payment creation failed: %s", vou_no, e)

        # 10. Payments
        self._register_payments(env, order, invoice, rows, order_date, cache)

        return f"SO {order.name} OK"

    # ── Payment Helper ────────────────────────────────────────────────────────
    def _register_payments(self, env, order, invoice, rows, pay_date, cache):
        branch = order.branch_id
        journal_cache = cache.setdefault('_journals', {})

        def find_journal(jtype, hint=''):
            key = f"{jtype}_{hint}_{branch.id if branch else 0}"
            if key in journal_cache:
                return journal_cache[key]

            base_domain = [('type', '=', jtype), ('company_id', '=', env.company.id)]
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
                _logger.warning("Voucher %s: Journal not found type=%s hint=%s", invoice.ref, jtype, hint)
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
