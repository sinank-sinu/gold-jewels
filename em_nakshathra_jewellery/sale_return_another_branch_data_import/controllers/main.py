import openpyxl, logging, datetime, traceback, json, os, uuid, gc
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

def _flt(val, default=0.0):
    try: return float(val or default)
    except: return default

def _str(val):
    return str(val).strip() if val is not None else ''


class SaleReturnAnotherBranchController(http.Controller):

    @http.route('/import/sale_return_another_branch/form', type='http', auth='user')
    def import_form(self, **kwargs):
        csrf = request.csrf_token()
        return f"""<!DOCTYPE html><html><head><title>Import Another Branch Sale Return</title>
<style>
body{{font-family:sans-serif;margin:40px;background:#f4f6f9;}}
.box{{max-width:820px;margin:auto;background:#fff;padding:24px;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,.12);}}
h2{{color:#1a237e;}} .btn{{background:#1a237e;color:#fff;padding:10px 22px;border:none;border-radius:4px;cursor:pointer;font-size:15px;}}
.btn:hover{{background:#283593;}} li{{margin:4px 0;}}
</style></head><body><div class="box">
<h2>Import Another Branch Sale Return</h2>
<p>Upload Excel with 2 sheets:</p>
<ul>
<li><b>SALES</b>: Sale order header + lines + payments</li>
<li><b>OTHER SHOP SR</b>: Sale return lines (product/purity/weight/rate)</li>
</ul>
<form action="/import/sale_return_another_branch/process" method="POST" enctype="multipart/form-data">
<input type="hidden" name="csrf_token" value="{csrf}"/>
<input type="file" name="file" accept=".xlsx" required style="margin:16px 0;display:block"/>
<button type="submit" class="btn">Import Data</button>
</form></div></body></html>"""

    @http.route('/import/sale_return_another_branch/process', type='http', auth='user', methods=['POST'], csrf=True)
    def import_process(self, file, **kwargs):
        if not file:
            return "<h1>Error</h1><p>No file uploaded.</p>"
        try:
            wb = openpyxl.load_workbook(file, data_only=True, read_only=True)
            sales_data = {}
            sales_sn = next((s for s in wb.sheetnames if 'SALES' in s.upper() and 'RETURN' not in s.upper()), wb.sheetnames[0])
            for row in wb[sales_sn].iter_rows(min_row=2, values_only=True):
                if not any(row): continue
                vou = _str(row[1])
                if not vou: continue
                vou_date = row[3]
                if isinstance(vou_date, (datetime.datetime, datetime.date)):
                    vou_date = vou_date.date().isoformat() if isinstance(vou_date, datetime.datetime) else vou_date.isoformat()
                r = list(row) + [None]*50
                entry = {
                    'branch_name':_str(r[0]),'party_name':_str(r[2]),'vou_date':vou_date,
                    'label_no':_str(r[4]),'barcode_no':_str(r[5]),'item_name':_str(r[6]),
                    'salesman':_str(r[7]),'purity':_str(r[8]),
                    'gross_wt':_flt(r[10]),'net_wt':_flt(r[11]),'diamond_wt':_flt(r[12]),'stone_wt':_flt(r[13]),
                    'metal_rate':_flt(r[14]),'metal_amt':_flt(r[15]),'mc_amt':_flt(r[16]),'diamond_amt':_flt(r[17]),
                    'stone_amt':_flt(r[18]),'other_charge':_flt(r[19]),'taxes':_str(r[21]),
                    'bill_amount':_flt(r[24]),
                    'bank_amt':_flt(r[26]),'bank_ref':_str(r[27]),
                    'upi_amt1':_flt(r[28]),'upi_ref1':_str(r[29]),
                    'upi_amt2':_flt(r[30]),'upi_ref2':_str(r[31]),
                    'card_amt1':_flt(r[32]),'card_ref1':_str(r[33]),
                    'card_amt2':_flt(r[34]),'card_ref2':_str(r[35]),
                    'card_amt3':_flt(r[36]),'card_ref3':_str(r[37]),
                    'cash_amt':_flt(r[38]),'gold_scheme':_flt(r[39]),'sales_return':_flt(r[42]),
                }
                sales_data.setdefault(vou, []).append(entry)
            sr_data = {}
            sr_sn = next((s for s in wb.sheetnames if 'SR' in s.upper() or ('RETURN' in s.upper() and s != sales_sn)), None)
            if not sr_sn and len(wb.sheetnames) > 1:
                sr_sn = wb.sheetnames[1]
            if sr_sn:
                for row in wb[sr_sn].iter_rows(min_row=2, values_only=True):
                    if not any(row): continue
                    r = list(row) + [None]*10
                    product = _str(r[0])
                    vou = _str(r[7])
                    if not product or not vou: continue
                    sr_date = r[8]
                    if isinstance(sr_date, (datetime.datetime, datetime.date)):
                        sr_date = sr_date.date().isoformat() if isinstance(sr_date, datetime.datetime) else sr_date.isoformat()
                    sr_data.setdefault(vou, []).append({
                        'product':_str(r[0]),'purity':_str(r[1]),
                        'gross_weight':_flt(r[2]),'stone_weight':_flt(r[3]),
                        'net_weight':_flt(r[4]),'rate':_flt(r[5]),'amount':_flt(r[6]),
                        'date':sr_date,'customer':_str(r[9]),
                    })
            wb.close()
            all_vous = list(sales_data.keys())
            file_id = str(uuid.uuid4())
            tmp_path = f'/tmp/odoo_anb_{file_id}.json'
            with open(tmp_path, 'w') as f:
                json.dump({'sales_data': sales_data, 'sr_data': sr_data, 'all_vous': all_vous}, f)
            total = len(all_vous)
            return f"""<!DOCTYPE html><html><head><title>Processing...</title>
<style>
body{{font-family:sans-serif;margin:40px;background:#f4f6f9;}}
.box{{max-width:860px;margin:auto;background:#fff;padding:24px;border-radius:8px;box-shadow:0 4px 8px rgba(0,0,0,.12);}}
.pb{{width:100%;background:#e0e0e0;border-radius:4px;height:22px;overflow:hidden;margin:16px 0;}}
.pf{{width:0%;height:100%;background:#1a237e;transition:width .3s;}}
.log{{max-height:480px;overflow-y:auto;background:#1a1a2e;color:#a5d6a7;padding:12px;font-family:monospace;font-size:12px;line-height:1.5;border-radius:4px;margin-top:12px;}}
.stat{{display:flex;gap:24px;margin:8px 0;font-size:14px;}}
.ok{{color:#4caf50;font-weight:bold;}} .er{{color:#ef5350;font-weight:bold;}}
</style></head><body><div class="box">
<h2 style="color:#1a237e">Processing {total} Vouchers</h2>
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
        log('<br><a href="/import/sale_return_another_branch/skipped_pdf?file_id='+fid+'" target="_blank" style="color:#ffcc80; font-weight:bold; font-size:16px; margin: 10px 0; display: inline-block;">📄 Download Skipped Vouchers PDF ('+window.skipped_count+' skipped)</a>');
    }}
    log('<br><a href="/import/sale_return_another_branch/form" style="color:#80cbc4">← Import Another File</a>');
    upd(); return;
  }}
  fetch('/import/sale_return_another_branch/chunk',{{method:'POST',headers:{{'Content-Type':'application/json'}},
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
            return f"<h1 style='color:red'>Error</h1><pre>{traceback.format_exc()}</pre>"

    @http.route('/import/sale_return_another_branch/chunk', type='json', auth='user', methods=['POST'])
    def import_chunk(self, file_id, offset, limit, **kwargs):
        try:
            tmp_path = f'/tmp/odoo_anb_{file_id}.json'
            if not os.path.exists(tmp_path):
                return {'error': 'Session expired. Please re-upload the file.'}
            with open(tmp_path) as f:
                data = json.load(f)
            all_vous   = data['all_vous']
            sales_data = data['sales_data']
            sr_data    = data['sr_data']
            chunk      = all_vous[offset: offset + limit]
            if not chunk:
                return {'success_count': 0, 'errors': [], 'logs': []}

            # Build per-chunk lookup cache to avoid repeated DB hits
            env = request.env(context={
                'tracking_disable': True,
                'mail_notrack': True,
                'no_recompute': True,
                'mail_create_nosubscribe': True,
            })
            cache = self._build_cache(env, chunk, sales_data, sr_data)

            skipped_labels = data.get('skipped_labels', [])
            has_skipped = False

            success, error_log, logs = 0, [], []
            for vou in chunk:
                try:
                    with env.cr.savepoint():
                        msg = self._process_voucher(
                            env, vou,
                            sales_data.get(vou, []),
                            sr_data.get(vou, []),
                            cache,
                        )
                        logs.append(f"✔ {vou}: {msg}")
                    success += 1
                except ValueError as e:
                    if str(e).startswith("MISSING_LABELS:"):
                        b = sales_data.get(vou, [{}])[0].get('branch_name', '')
                        skipped_labels.append({
                            'vou_no': vou,
                            'branch': b,
                            'labels': str(e).split(":", 1)[1]
                        })
                        has_skipped = True
                        error_log.append(f"Skipped {vou} (Missing Labels: {str(e).split(':', 1)[1]})")
                    else:
                        error_log.append(f"✘ {vou}: {e}")
                        _logger.exception("Voucher %s failed", vou)
                except Exception as e:
                    error_log.append(f"✘ {vou}: {e}")
                    _logger.exception("Voucher %s failed", vou)

            if has_skipped:
                data['skipped_labels'] = skipped_labels
                with open(tmp_path, 'w') as f:
                    json.dump(data, f)

            # Free ORM cache between chunks to prevent memory growth
            env.invalidate_all()
            gc.collect()
            return {'success_count': success, 'errors': error_log, 'logs': logs, 'skipped_count': len(skipped_labels)}
        except Exception as e:
            _logger.exception("Chunk failed")
            return {'error': str(e)}

    # ── Pre-load common records for the whole chunk in bulk ───────────────────
    def _build_cache(self, env, chunk, sales_data, sr_data):
        """
        Collect all unique names/barcodes/etc from chunk rows and fetch them
        in bulk to avoid N+1 queries per voucher.
        """
        partner_names, salesman_names, branch_names = set(), set(), set()
        barcodes, label_names, item_names = set(), set(), set()
        purity_names, product_names = set(), set()

        for vou in chunk:
            for row in sales_data.get(vou, []):
                if row.get('party_name'):   partner_names.add(row['party_name'])
                if row.get('salesman'):     salesman_names.add(row['salesman'])
                if row.get('branch_name'):  branch_names.add(row['branch_name'])
                if row.get('barcode_no'):   barcodes.add(row['barcode_no'])
                if row.get('label_no'):     label_names.add(row['label_no'])
                if row.get('item_name'):    item_names.add(row['item_name'])
                if row.get('purity'):       purity_names.add(row['purity'])
            for rl in sr_data.get(vou, []):
                if rl.get('product'):  product_names.add(rl['product'])
                if rl.get('purity'):   purity_names.add(rl['purity'])

        # Bulk fetch
        partners  = env['res.partner'].search([('name', 'in', list(partner_names))])
        salesmen  = env['res.users'].search([('name', 'in', list(salesman_names))])
        branches  = env['res.branch'].search([('name', 'in', list(branch_names))])
        purities  = env['gold.purity'].search([])  # small table – load all
        labels_bc = env['product.label'].search([('barcode', 'in', list(barcodes))]) if barcodes else env['product.label'].browse()
        labels_nm = env['product.label'].search([('name', 'in', list(label_names))]) if label_names else env['product.label'].browse()
        all_labels = labels_bc | labels_nm
        products  = env['product.product'].search([('name', 'in', list(item_names | product_names))]) if (item_names | product_names) else env['product.product'].browse()

        # Build fast-lookup dicts (lower-case keys for ilike-style matching)
        return {
            'partners':  {p.name.strip(): p for p in partners},
            'salesmen':  {u.name.strip(): u for u in salesmen},
            'branches':  {b.name.strip(): b for b in branches},
            'purities':  {p.name.strip(): p for p in purities},
            'labels_bc': {l.barcode: l for l in all_labels if l.barcode},
            'labels_nm': {l.name: l for l in all_labels},
            'products':  {p.name.strip(): p for p in products},
        }

    # ── Lookup helpers (cache-first, DB fallback) ─────────────────────────────
    @staticmethod
    def _find(cache_dict, key, env_model, domain_field, exact=True):
        if not key: return None
        hit = cache_dict.get(key)
        if hit: return hit
        # Case-insensitive fallback for keys that differ only in case/spaces
        key_l = key.lower()
        for k, v in cache_dict.items():
            if k.lower() == key_l:
                cache_dict[key] = v
                return v
        return None

    # ── Main per-voucher processor ────────────────────────────────────────────
    def _process_voucher(self, env, vou_no, sales_rows, sr_rows, cache):
        if not sales_rows:
            raise UserError(f"No SALES rows for {vou_no}")
        hdr = sales_rows[0]

        # 1. Branch (from cache)
        branch_name = hdr.get('branch_name', '').strip()
        branch = self._find(cache['branches'], branch_name, None, None)
        if not branch and branch_name:
            branch = env['res.branch'].search([('name', 'ilike', branch_name)], limit=1)
            if branch: cache['branches'][branch_name] = branch

        # 2. Customer (from cache, create if missing)
        party_name = hdr.get('party_name', '').strip()
        partner = self._find(cache['partners'], party_name, None, None)
        if not partner and party_name:
            partner = env['res.partner'].search([('name', '=ilike', party_name)], limit=1)
            if not partner:
                partner = env['res.partner'].sudo().create({'name': party_name, 'customer_rank': 1})
            cache['partners'][party_name] = partner

        # 3. Salesman (from cache, create if missing)
        salesman_name = hdr.get('salesman', '').strip()
        salesman = self._find(cache['salesmen'], salesman_name, None, None)
        if not salesman and salesman_name:
            salesman = env['res.users'].search([('name', '=ilike', salesman_name)], limit=1)
            if not salesman:
                # Create a new user so the sale order has the correct salesperson
                login = salesman_name.lower().replace(' ', '')
                if env['res.users'].search([('login', '=', login)]):
                    login = f"{login}_{str(uuid.uuid4())[:4]}"
                salesman = env['res.users'].sudo().create({
                    'name': salesman_name,
                    'login': login,
                })
            cache['salesmen'][salesman_name] = salesman

        # Check for missing labels in sales_rows BEFORE creating the order
        missing = []
        for row in sales_rows:
            barcode   = row.get('barcode_no', '').strip()
            label_ref = row.get('label_no', '').strip()
            
            if not barcode and not label_ref:
                continue
            
            label = cache['labels_bc'].get(barcode) or cache['labels_nm'].get(label_ref)
            if not label and label_ref:
                label = env['product.label'].search([('name', '=ilike', label_ref)], limit=1)
                if label: cache['labels_nm'][label_ref] = label
            
            if not label:
                missing.append(label_ref or barcode)
        
        if missing:
            raise ValueError(f"MISSING_LABELS:{','.join(missing)}")

        # 4. Create Sale Order
        vou_date = hdr.get('vou_date') or fields.Date.today()
        so_vals = {
            'partner_id':     partner.id if partner else False,
            'origin':         vou_no,
            'date_order':     vou_date,
            'is_sale_return': True,
        }
        if branch:   so_vals['branch_id'] = branch.id
        if salesman: so_vals['user_id']    = salesman.id
        order = env['sale.order'].sudo().create(so_vals)

        # 5. Sale Return Lines (SR sheet) – product create if missing
        for rl in sr_rows:
            prod_name = rl.get('product', '').strip()
            if not prod_name: continue
            prod = cache['products'].get(prod_name)
            if not prod:
                prod = env['product.product'].search([('name', 'ilike', prod_name)], limit=1)
                if not prod:
                    tmpl = env['product.template'].sudo().create({
                        'name': prod_name, 'type': 'product',
                        'sale_ok': True, 'purchase_ok': True,
                    })
                    prod = tmpl.product_variant_id
                cache['products'][prod_name] = prod
            purity_key = rl.get('purity', '').strip()
            purity = cache['purities'].get(purity_key)
            env['sale.return.line'].sudo().create({
                'sale_id':      order.id,
                'product_id':   prod.id,
                'purity_id':    purity.id if purity else False,
                'gross_weight': rl.get('gross_weight', 0.0),
                'stone_weight': rl.get('stone_weight', 0.0),
                'rate':         rl.get('rate', 0.0),
            })

        # 6. Sale Order Lines (SALES sheet)
        for row in sales_rows:
            barcode   = row.get('barcode_no', '').strip()
            label_ref = row.get('label_no', '').strip()
            item_name = row.get('item_name', '').strip()
            if not barcode and not label_ref and not item_name:
                continue
            # Label: barcode first → name exact → name ilike
            label = (cache['labels_bc'].get(barcode)
                     or cache['labels_nm'].get(label_ref))
            if not label and label_ref:
                label = env['product.label'].search([('name', 'ilike', label_ref)], limit=1)
                if label: cache['labels_nm'][label_ref] = label
            # Product from label or item name
            line_prod = None
            if label:
                line_prod = label.product_id or (label.product_tmpl_id.product_variant_id if label.product_tmpl_id else None)
            if not line_prod and item_name:
                line_prod = cache['products'].get(item_name)
                if not line_prod:
                    line_prod = env['product.product'].search([('name', 'ilike', item_name)], limit=1)
                    if line_prod: cache['products'][item_name] = line_prod
            if not line_prod:
                _logger.warning("No product for barcode=%s label=%s item=%s – skipped", barcode, label_ref, item_name)
                continue
            purity_key = row.get('purity', '').strip()
            purity = (cache['purities'].get(purity_key)
                      or (label.purity_id if label else None))
            taxes = line_prod.taxes_id.filtered(lambda t: t.company_id == env.company)

            # ── Step 1: create with price_unit=0.0 to satisfy NOT NULL ───────
            gross_wt    = _flt(row.get('gross_wt'))    or (label.sale_gross_weight      if label else 1.0) or 1.0
            stone_wt    = _flt(row.get('stone_wt'))    or (label.sale_stone_weight      if label else 0.0)
            diamond_wt  = _flt(row.get('diamond_wt'))  or (label.sale_diamond_weight_gm if label else 0.0)
            stone_amt   = _flt(row.get('stone_amt'))   or (label.sale_stone_rate        if label else 0.0)
            diamond_amt = _flt(row.get('diamond_amt')) or (label.sale_diamond_rate      if label else 0.0)
            other_amt   = _flt(row.get('other_charge', 0.0))
            mc_amt      = _flt(row.get('mc_amt', 0.0))

            line_vals = {
                'order_id':               order.id,
                'product_id':             line_prod.id,
                'product_uom':            line_prod.uom_id.id,
                'product_uom_qty':        gross_wt,
                'price_unit':             0.0,   # temp – onchange will recalculate
                'sale_stone_weight':      stone_wt,
                'sale_diamond_weight_gm': diamond_wt,
                'sale_stone_rate':        stone_amt,
                'sale_diamond_rate':      diamond_amt,
                'other_weight_amount':    other_amt,
                'tax_id':                 [(6, 0, taxes.ids)] if taxes else [],
            }
            if label:  line_vals['label_id']  = label.id
            if purity: line_vals['purity_id'] = purity.id
            line = env['sale.order.line'].sudo().create(line_vals)

            # ── Step 2: call onchange so purity drives gold_rate / metal_amount ─
            line._onchange_label_id()

            # ── Step 3: write onchange results + Excel MC to DB ───────────────
            excel_metal_rate = _flt(row.get('metal_rate')) or line.gold_rate
            excel_metal_amt  = _flt(row.get('metal_amt')) or line.metal_amount
            
            line.sudo().write({
                'gold_rate':        excel_metal_rate,
                'metal_amount':     excel_metal_amt,
                'mc_amount_actual': mc_amt,   # use Excel MC directly
            })

            # ── Step 4: flush stored computes (price_subtotal, price_unit) ───
            line._compute_subtotal()
            line._compute_price_unit()
            line.flush_recordset(['price_subtotal', 'price_subtotal_actual', 'price_unit'])

        # 7. Gold Scheme
        gold_scheme_amt = _flt(hdr.get('gold_scheme', 0.0))
        if gold_scheme_amt > 0 and partner:
            scheme = env['jewellery.scheme.enrollment'].search(
                [('partner_id', '=', partner.id)], order='id desc', limit=1)
            if scheme:
                order.apply_scheme    = True
                order.active_scheme_id = scheme.id
                try:
                    pcode   = f"SCHEME-{scheme.id}"
                    sprод   = env['product.product'].search([('default_code', '=', pcode)], limit=1)
                    if not sprод:
                        sprод = env['product.product'].sudo().create({
                            'name': f"{scheme.name} - {partner.name}",
                            'default_code': pcode, 'type': 'service', 'list_price': 0.0,
                        })
                    sl = env['sale.order.line'].sudo().create({
                        'order_id': order.id, 'product_id': sprод.id,
                        'product_uom_qty': 1, 'product_uom': sprод.uom_id.id,
                        'name': f"{sprод.name} (Scheme Redemption)",
                        'is_scheme_line': True, 'price_unit': -gold_scheme_amt, 'tax_id': False,
                    })
                    order.scheme_line_id = sl.id
                    scheme.write({'state': 'redeemed', 'is_redeemed': True})
                    if 'scheme.redemption' in env:
                        env['scheme.redemption'].sudo().create(
                            {'scheme_id': scheme.id, 'sale_order_id': order.id, 'amount': gold_scheme_amt})
                except Exception as e:
                    _logger.warning("Scheme apply failed %s: %s", vou_no, e)

        # 8. Confirm
        order.with_context(tracking_disable=True, mail_notrack=True).action_confirm()

        # 9. Validate stock delivery
        for picking in order.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel') and p.picking_type_code == 'outgoing'):
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                if hasattr(move, 'picked'): move.picked = True
            try:
                res = picking.with_context(skip_backorder=True, cancel_backorder=True).button_validate()
                if isinstance(res, dict) and res.get('res_model') == 'stock.immediate.transfer':
                    env['stock.immediate.transfer'].with_context(
                        res.get('context', {})).create({'pick_ids': [(4, picking.id)]}).process()
            except Exception as e:
                _logger.warning("Stock validate %s: %s", vou_no, e)

        # 10. Apply Sale Return
        if order.sale_return_line_ids:
            try:
                order.action_apply_sale_return()
            except Exception as e:
                _logger.warning("Sale return apply %s: %s", vou_no, e)

        # 11. Create & post invoice
        invoice = env['account.move'].browse()
        try:
            invoices = order._create_invoices()
            if invoices:
                invoice = invoices[0]
                invoice.invoice_date = vou_date
                invoice.action_post()
        except Exception as e:
            _logger.warning("Invoice %s: %s", vou_no, e)

        # 12. Payments
        if invoice and invoice.state == 'posted':
            self._register_payments(env, order, invoice, hdr, vou_date, cache)

        return f"SO {order.name} OK"

    # ── Payment helper ────────────────────────────────────────────────────────
    def _register_payments(self, env, order, invoice, hdr, pay_date, cache):
        branch = order.branch_id
        journal_cache = cache.setdefault('_journals', {})

        def find_journal(jtype, hint=''):
            key = f"{jtype}_{hint}_{branch.id if branch else 0}"
            if key in journal_cache:
                return journal_cache[key]
            
            base_domain = [('type', '=', jtype), ('company_id', '=', env.company.id)]
            hint_domain = [('name', 'ilike', hint)] if hint else []
            branch_domain = [('branch_id', '=', branch.id)] if branch else []
            
            # 1. Match Type + Branch + Hint (e.g. Branch A's UPI journal)
            j = env['account.journal'].search(base_domain + branch_domain + hint_domain, limit=1)
            
            # 2. Match Type + Hint ignoring branch (e.g. Global UPI journal)
            if not j and hint:
                j = env['account.journal'].search(base_domain + hint_domain, limit=1)
                
            # 3. Match Type + Branch ignoring hint (e.g. Branch A's generic Bank journal)
            if not j and branch:
                j = env['account.journal'].search(base_domain + branch_domain, limit=1)
                
            # 4. Match Type ignoring both (e.g. First available Bank journal)
            if not j:
                j = env['account.journal'].search(base_domain, limit=1)
                
            journal_cache[key] = j
            return j

        def pay(amount, jtype, hint='', ref=''):
            if not amount or amount <= 0: return
            journal = find_journal(jtype, hint)
            if not journal: return
            try:
                wiz_vals = {'amount': amount, 'journal_id': journal.id,
                            'payment_date': pay_date, 'communication': ref or ''}
                if 'bank_reference' in env['account.payment.register']._fields:
                    wiz_vals['bank_reference'] = ref or ''
                wiz = env['account.payment.register'].with_context(
                    active_model='account.move', active_ids=invoice.ids
                ).create(wiz_vals)
                
                # Odoo automatically recomputes amount to full invoice total based on active_ids
                # We explicitly overwrite it here to the partial Excel amount before generating payment
                wiz.amount = amount
                
                payments = wiz.action_create_payments()
                if payments and hasattr(payments, 'bank_reference'):
                    payments.write({'bank_reference': ref or ''})
            except Exception as e:
                _logger.warning("Payment %s/%s: %s", jtype, hint, e)

        pay(hdr.get('bank_amt',  0), 'bank', 'bank',  hdr.get('bank_ref', ''))
        pay(hdr.get('upi_amt1',  0), 'bank', 'upi',   hdr.get('upi_ref1', ''))
        pay(hdr.get('upi_amt2',  0), 'bank', 'upi',   hdr.get('upi_ref2', ''))
        pay(hdr.get('card_amt1', 0), 'bank', 'card',  hdr.get('card_ref1', ''))
        pay(hdr.get('card_amt2', 0), 'bank', 'card',  hdr.get('card_ref2', ''))
        pay(hdr.get('card_amt3', 0), 'bank', 'card',  hdr.get('card_ref3', ''))
        pay(hdr.get('cash_amt',  0), 'cash', '',      '')

    @http.route('/import/sale_return_another_branch/skipped_pdf', type='http', auth='user')
    def download_skipped_pdf(self, file_id, **kw):
        fpath = f'/tmp/odoo_anb_{file_id}.json'
        if not os.path.exists(fpath):
            return request.not_found("File expired or not found")
        
        with open(fpath, 'r') as f:
            data = json.load(f)
            
        skipped = data.get('skipped_labels', [])
        
        html = """
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                table { width: 100%; border-collapse: collapse; margin-top: 20px; }
                th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
                th { background-color: #f4f4f4; }
                h2 { color: #333; text-align: center; }
            </style>
        </head>
        <body>
            <h2>Import Skipped Vouchers Report</h2>
            <p>The following vouchers were completely skipped because they contain labels or barcodes that do not exist in Odoo.</p>
            <table>
                <tr>
                    <th>Branch</th>
                    <th>Voucher No</th>
                    <th>Missing Label(s)</th>
                </tr>
        """
        for s in skipped:
            html += f"<tr><td>{s.get('branch','')}</td><td>{s.get('vou_no','')}</td><td style='color:red;'>{s.get('labels','')}</td></tr>"
            
        html += """
            </table>
        </body>
        </html>
        """
        
        pdf_content = request.env['ir.actions.report'].sudo()._run_wkhtmltopdf([html])
        
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'attachment; filename="missing_labels_report_{file_id}.pdf"')
        ]
        return request.make_response(pdf_content, headers=headers)
