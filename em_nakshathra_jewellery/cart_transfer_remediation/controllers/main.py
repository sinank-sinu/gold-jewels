# -*- coding: utf-8 -*-
import json
import logging
import threading
import time
from collections import defaultdict

import odoo
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

_PROGRESS = {
    'status': 'IDLE',
    'percent': 0,
    'current_step': 'Ready',
    'logs': [],
    'is_dry_run': False,
    'action': 'audit_scan',
}


def log(msg, percent=None):
    if percent is not None:
        _PROGRESS['percent'] = percent
    _PROGRESS['logs'].append(msg)
    _logger.info(f"[{_PROGRESS['percent']}%] {msg}")


def analyze_database(cr):
    """Deep analysis of transfers, duplicate cart scans, and header mismatches."""
    # 1. Total cart pickings
    cr.execute("SELECT count(*) as cnt FROM stock_picking WHERE origin LIKE 'Salesman Cart%';")
    total_cart_pickings = cr.dictfetchone()['cnt']

    # 2. DMD/Stock/M headers to SM counters
    cr.execute("""
        SELECT count(*) as cnt
        FROM stock_picking sp
        JOIN stock_location src ON sp.location_id = src.id
        JOIN stock_location dst ON sp.location_dest_id = dst.id
        WHERE src.complete_name = 'DMD/Stock/M' AND dst.complete_name LIKE '%/SM/C%';
    """)
    dmd_headers = cr.dictfetchone()['cnt']

    # 3. All label move events into SM counters
    cr.execute("""
        WITH move_events AS (
            SELECT 
                sml.label_id,
                pl.name as label_name,
                sp.id as picking_id,
                sp.name as picking_name,
                sp.origin,
                sml.id as move_line_id,
                sm.id as move_id,
                sm.location_id as src_loc_id,
                loc_src.complete_name as src_loc,
                sm.location_dest_id as dst_loc_id,
                loc_dst.complete_name as dst_loc,
                sp.location_id as pick_header_src_id,
                loc_psrc.complete_name as pick_header_src,
                sml.quantity,
                sp.create_date
            FROM stock_move_line sml
            JOIN stock_move sm ON sml.move_id = sm.id
            JOIN stock_picking sp ON sm.picking_id = sp.id
            JOIN product_label pl ON sml.label_id = pl.id
            LEFT JOIN stock_location loc_src ON sm.location_id = loc_src.id
            LEFT JOIN stock_location loc_dst ON sm.location_dest_id = loc_dst.id
            LEFT JOIN stock_location loc_psrc ON sp.location_id = loc_psrc.id
            WHERE sml.state = 'done'
              AND sm.state = 'done'
              AND sml.label_id IS NOT NULL
            ORDER BY sml.label_id, sp.id ASC
        )
        SELECT * FROM move_events;
    """)
    all_events = cr.dictfetchall()

    label_events = defaultdict(list)
    for ev in all_events:
        label_events[ev['label_id']].append(ev)

    duplicate_pickings = []
    dup_weight = 0.0

    for lid, events in label_events.items():
        sm_transfers_in_stretch = []
        for ev in events:
            is_to_sm = '/SM/C' in (ev['dst_loc'] or '')
            is_from_sm = '/SM/C' in (ev['src_loc'] or '')
            is_out = ev['dst_loc'] == 'Partners/Customers'

            if is_to_sm and ev['origin'] and 'Salesman Cart' in ev['origin']:
                sm_transfers_in_stretch.append(ev)
            elif is_from_sm or is_out:
                if len(sm_transfers_in_stretch) > 1:
                    for dup in sm_transfers_in_stretch[:-1]:
                        duplicate_pickings.append(dup)
                        dup_weight += float(dup['quantity'] or 0.0)
                sm_transfers_in_stretch = []

        if len(sm_transfers_in_stretch) > 1:
            for dup in sm_transfers_in_stretch[:-1]:
                duplicate_pickings.append(dup)
                dup_weight += float(dup['quantity'] or 0.0)

    # 4. Header mismatches on pickings
    cr.execute("""
        SELECT count(DISTINCT sp.id) as cnt
        FROM stock_picking sp
        JOIN stock_move sm ON sm.picking_id = sp.id
        WHERE sp.origin LIKE 'Salesman Cart%'
          AND sp.location_id != sm.location_id;
    """)
    total_header_mismatches = cr.dictfetchone()['cnt']

    # 5. Non-vault quants currently in SM counters
    cr.execute("""
        SELECT count(*) as cnt, COALESCE(sum(sq.quantity), 0.0) as wt
        FROM stock_quant sq
        JOIN stock_location sl ON sq.location_id = sl.id
        JOIN product_product pp ON sq.product_id = pp.id
        JOIN product_template pt ON pp.product_tmpl_id = pt.id
        WHERE sl.complete_name LIKE '%/SM/C%'
          AND sq.quantity > 0.001
          AND (pt.is_vault_item IS NULL OR pt.is_vault_item = FALSE);
    """)
    sm_quants = cr.dictfetchone()

    return {
        'total_cart_pickings': total_cart_pickings,
        'dmd_headers': dmd_headers,
        'duplicate_pickings_count': len(duplicate_pickings),
        'duplicate_pickings': duplicate_pickings,
        'duplicate_weight': round(dup_weight, 3),
        'header_mismatches': total_header_mismatches,
        'sm_non_vault_quants_count': sm_quants['cnt'],
        'sm_non_vault_quants_weight': round(float(sm_quants['wt']), 3),
        'clean_pickings': total_cart_pickings - len(duplicate_pickings),
    }


def execute_action_worker(db_name, action_type, commit=False):
    global _PROGRESS
    _PROGRESS['status'] = 'RUNNING'
    _PROGRESS['percent'] = 5
    _PROGRESS['current_step'] = 'Connecting to Database'
    _PROGRESS['logs'] = []
    _PROGRESS['is_dry_run'] = not commit
    _PROGRESS['action'] = action_type

    registry = odoo.registry(db_name)
    with registry.cursor() as cr:
        try:
            mode_str = "*** LIVE COMMIT (Writing changes to DB) ***" if commit else "*** DRY RUN (Simulation only, will ROLLBACK) ***"
            log("=" * 70, 5)
            log(f" STARTING: {action_type.upper()}", 5)
            log(f" Database: {db_name}", 5)
            log(f" Mode: {mode_str}", 5)
            log("=" * 70, 5)

            # Step 1: Run Diagnostic
            log("[Step 1] Analyzing stock transfers, labels, and salesman counters...", 10)
            metrics = analyze_database(cr)
            log(f"  • Total Salesman Cart Pickings: {metrics['total_cart_pickings']:,}", 15)
            log(f"  • Duplicate Cart Pickings to Purge: {metrics['duplicate_pickings_count']:,} ({metrics['duplicate_weight']}g)", 20)
            log(f"  • Pickings with Wrong Header (DMD/Stock/M): {metrics['dmd_headers']:,}", 25)
            log(f"  • Header Location Mismatches: {metrics['header_mismatches']:,}", 30)

            # ACTION: AUDIT ONLY
            if action_type == 'audit_scan':
                log("\n--- Sample Duplicate Transfers Detected ---", 35)
                for dup in metrics['duplicate_pickings'][:10]:
                    log(f"  [DUP] Label: {dup['label_name']:12} | Picking: {dup['picking_name']} ({dup['origin']}) | Header: {dup['pick_header_src']} -> Move: {dup['src_loc']} to {dup['dst_loc']} ({dup['quantity']}g)", 40)
                if len(metrics['duplicate_pickings']) > 10:
                    log(f"  ... and {len(metrics['duplicate_pickings']) - 10} more duplicate transfers.", 45)
                log("\n[Audit Result] System is ready for remediation.", 90)

            # ACTION: PURGE DUPLICATES (or FULL)
            if action_type in ('purge_duplicates', 'full_cleanup'):
                dup_pickings = metrics['duplicate_pickings']
                if not dup_pickings:
                    log("No duplicate transfers found to purge!", 50)
                else:
                    log(f"\n[Step 2] Reversing stock balances for {len(dup_pickings)} duplicate transfers...", 40)
                    dup_picking_ids = [d['picking_id'] for d in dup_pickings]

                    reversed_count = 0
                    for idx, dup in enumerate(dup_pickings):
                        cr.execute("""
                            SELECT sml.product_id, sml.quantity, sml.location_id, sml.location_dest_id, sml.lot_id
                            FROM stock_move_line sml
                            JOIN stock_move sm ON sml.move_id = sm.id
                            WHERE sm.picking_id = %s;
                        """, (dup['picking_id'],))
                        mls = cr.dictfetchall()

                        for ml in mls:
                            # 1. Deduct from counter (location_dest_id)
                            cr.execute("""
                                UPDATE stock_quant
                                SET quantity = quantity - %s
                                WHERE product_id = %s AND location_id = %s;
                            """, (ml['quantity'], ml['product_id'], ml['location_dest_id']))

                            # 2. Restore to FINAL (location_id)
                            cr.execute("""
                                UPDATE stock_quant
                                SET quantity = quantity + %s
                                WHERE product_id = %s AND location_id = %s;
                            """, (ml['quantity'], ml['product_id'], ml['location_id']))
                            reversed_count += 1

                        if (idx + 1) % 25 == 0 or idx == len(dup_pickings) - 1:
                            progress_pct = 40 + int(20 * (idx + 1) / len(dup_pickings))
                            log(f"  Processed {idx + 1}/{len(dup_pickings)} duplicate transfers ({reversed_count} quant moves reversed)...", progress_pct)

                    # Clean zero quants
                    cr.execute("DELETE FROM stock_quant WHERE quantity <= 0.0001 AND reserved_quantity = 0;")
                    log("  ✓ Stock balances restored to FINAL and phantom stock removed from counters.", 60)

                    # Delete picking records
                    log(f"\n[Step 3] Purging {len(dup_picking_ids)} duplicate stock.picking records from database...", 62)
                    cr.execute("UPDATE salesman_cart_line SET picking_id = NULL WHERE picking_id IN %s;", (tuple(dup_picking_ids),))
                    cr.execute("DELETE FROM mail_message WHERE model = 'stock.picking' AND res_id IN %s;", (tuple(dup_picking_ids),))
                    cr.execute("DELETE FROM stock_move_line WHERE picking_id IN %s;", (tuple(dup_picking_ids),))
                    cr.execute("DELETE FROM stock_move WHERE picking_id IN %s;", (tuple(dup_picking_ids),))
                    cr.execute("DELETE FROM stock_picking WHERE id IN %s;", (tuple(dup_picking_ids),))
                    log(f"  ✓ Completely purged {len(dup_picking_ids)} pickings from Transfers and Move History.", 70)

            # ACTION: FIX HEADERS (or FULL)
            if action_type in ('fix_headers', 'full_cleanup'):
                log("\n[Step 4] Aligning picking headers and operation types for legitimate transfers...", 75)
                cr.execute("""
                    SELECT spt.id as pt_id, sw.branch_id
                    FROM stock_picking_type spt
                    JOIN stock_warehouse sw ON spt.warehouse_id = sw.id
                    WHERE spt.code = 'internal' 
                      AND spt.sequence_code = 'INT'
                      AND sw.branch_id IS NOT NULL;
                """)
                branch_to_pt = {r['branch_id']: r['pt_id'] for r in cr.dictfetchall()}

                # Align header location_id to match move.location_id (FINAL)
                cr.execute("""
                    UPDATE stock_picking sp
                    SET location_id = sm.location_id
                    FROM stock_move sm
                    WHERE sm.picking_id = sp.id
                      AND sp.origin LIKE 'Salesman Cart%'
                      AND sp.location_id != sm.location_id;
                """)
                locs_updated = cr.rowcount
                log(f"  ✓ Aligned {locs_updated:,} picking header Source Locations to true move source.", 85)

                # Align operation types to match destination branch
                type_updates = 0
                for branch_id, pt_id in branch_to_pt.items():
                    cr.execute("""
                        UPDATE stock_picking sp
                        SET picking_type_id = %s
                        FROM stock_location sl
                        WHERE sp.location_dest_id = sl.id
                          AND sl.branch_id = %s
                          AND sp.origin LIKE 'Salesman Cart%%'
                          AND sp.picking_type_id != %s;
                    """, (pt_id, branch_id, pt_id))
                    type_updates += cr.rowcount
                log(f"  ✓ Aligned {type_updates:,} picking Operation Types to matching branch warehouses.", 90)

            # ACTION: ZERO-OUT REMAINING PHANTOM QUANTS
            if action_type in ('cleanup_quants', 'full_cleanup'):
                log("\n[Step 5] Checking for any remaining phantom stock in Salesman Counters...", 92)
                cr.execute("""
                    SELECT sq.id, sq.product_id, sq.location_id, sq.quantity, sl.complete_name
                    FROM stock_quant sq
                    JOIN stock_location sl ON sq.location_id = sl.id
                    JOIN product_product pp ON sq.product_id = pp.id
                    JOIN product_template pt ON pp.product_tmpl_id = pt.id
                    WHERE sl.complete_name LIKE '%/SM/C%'
                      AND sq.quantity > 0.001
                      AND (pt.is_vault_item IS NULL OR pt.is_vault_item = FALSE);
                """)
                remaining = cr.dictfetchall()
                if remaining:
                    log(f"  Found {len(remaining)} stray quants in counters without vault tag.", 94)
                else:
                    log("  ✓ No orphaned non-vault quants found in salesman counters.", 95)

            if commit:
                cr.commit()
                log("\n" + "=" * 70, 98)
                log(" SUCCESS: All changes successfully COMMITTED to the database!", 100)
                log("=" * 70, 100)
                _PROGRESS['status'] = 'DONE'
                _PROGRESS['current_step'] = 'Completed (Committed)'
            else:
                cr.rollback()
                log("\n" + "=" * 70, 98)
                log(" DRY RUN COMPLETE: All changes were simulated and SAFELY ROLLED BACK.", 100)
                log(" Check the box and click 'Execute Live' when you are ready to write to DB.", 100)
                log("=" * 70, 100)
                _PROGRESS['status'] = 'DONE'
                _PROGRESS['current_step'] = 'Completed (Dry Run)'

        except Exception as e:
            import traceback
            traceback.print_exc()
            cr.rollback()
            log(f"\nFATAL ERROR: {str(e)}", 100)
            _PROGRESS['status'] = 'ERROR'
            _PROGRESS['current_step'] = f'ERROR: {str(e)}'


class CartRemediationController(http.Controller):

    @http.route(['/cart_cleanup', '/cart_remediation'], type='http', auth='user', website=False, csrf=False)
    def render_cart_cleanup(self, **kw):
        """Renders the remediation console directly inside Odoo on port 8019."""
        cr = request.env.cr
        db_name = cr.dbname
        metrics = analyze_database(cr)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Salesman Cart Transfer Remediation Console</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-body: #090d16;
            --card-bg: #111827;
            --card-border: #1f293d;
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --accent-amber: #f59e0b;
            --accent-red: #ef4444;
            --text-primary: #f8fafc;
            --text-muted: #94a3b8;
            --terminal-bg: #030712;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg-body);
            color: var(--text-primary);
            padding: 30px 20px;
            min-height: 100vh;
        }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 25px; position: relative; }}
        .badge {{
            display: inline-flex; align-items: center; gap: 6px;
            background: rgba(6, 182, 212, 0.12); color: var(--accent-cyan);
            border: 1px solid rgba(6, 182, 212, 0.3); border-radius: 9999px;
            padding: 4px 14px; font-size: 13px; font-weight: 600; margin-bottom: 10px;
        }}
        .header h1 {{
            font-size: 26px; font-weight: 700;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 6px;
        }}
        .header p {{ color: var(--text-muted); font-size: 14px; }}
        .back-link {{ position: absolute; left: 0; top: 10px; color: var(--accent-cyan); text-decoration: none; font-size: 13px; font-weight: 600; }}
        .back-link:hover {{ text-decoration: underline; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 20px; }}
        .card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 18px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3); }}
        .card-title {{ font-size: 13px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 8px; }}
        .stat-main {{ font-size: 26px; font-weight: 700; font-family: 'JetBrains Mono', monospace; margin-bottom: 4px; }}
        .stat-main.amber {{ color: var(--accent-amber); }}
        .stat-main.red {{ color: var(--accent-red); }}
        .stat-main.cyan {{ color: var(--accent-cyan); }}
        .stat-main.green {{ color: var(--accent-green); }}
        .stat-sub {{ font-size: 12px; color: var(--text-muted); }}

        .controls {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; margin-bottom: 20px; display: flex; flex-wrap: wrap; gap: 15px; align-items: center; justify-content: space-between; }}
        .action-group {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
        select.custom-select {{ background: #1e293b; color: #fff; border: 1px solid #334155; padding: 10px 14px; border-radius: 8px; font-size: 14px; outline: none; cursor: pointer; }}
        .btn {{ padding: 10px 20px; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; border: none; display: inline-flex; align-items: center; gap: 8px; }}
        .btn-dry {{ background: rgba(6, 182, 212, 0.15); color: var(--accent-cyan); border: 1px solid rgba(6, 182, 212, 0.4); }}
        .btn-dry:hover {{ background: rgba(6, 182, 212, 0.25); }}
        .btn-exec {{ background: linear-gradient(135deg, #059669, #10b981); color: #fff; }}
        .btn-exec:hover {{ background: linear-gradient(135deg, #047857, #059669); }}
        .btn:disabled {{ opacity: 0.4; cursor: not-allowed; }}
        .confirm-wrapper {{ display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-muted); }}
        .confirm-wrapper input[type="checkbox"] {{ accent-color: var(--accent-green); width: 16px; height: 16px; cursor: pointer; }}

        .terminal-box {{ background: var(--terminal-bg); border: 1px solid var(--card-border); border-radius: 12px; overflow: hidden; }}
        .terminal-header {{ background: #111827; padding: 10px 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--card-border); }}
        .terminal-dots {{ display: flex; gap: 6px; }}
        .dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
        .dot-red {{ background: #ef4444; }}
        .dot-yellow {{ background: #f59e0b; }}
        .dot-green {{ background: #10b981; }}
        .terminal-title {{ font-size: 12px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }}
        .progress-bar-container {{ background: #1e293b; height: 5px; width: 100%; }}
        .progress-bar {{ height: 100%; width: 0%; background: linear-gradient(90deg, #06b6d4, #10b981); transition: width 0.3s; }}
        .terminal-content {{ padding: 16px; font-family: 'JetBrains Mono', monospace; font-size: 13px; line-height: 1.6; height: 420px; overflow-y: auto; color: #d1d5db; }}
        .log-entry {{ margin-bottom: 2px; white-space: pre-wrap; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <a href="/web" class="back-link">← Back to Odoo</a>
            <div class="badge"><span>⚡</span> Odoo Live Cart Remediation Console</div>
            <h1>Salesman Cart Transfer & Phantom Stock Remediation</h1>
            <p>Target Database: <strong>{db_name}</strong> | Connected via Odoo Session</p>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-title">Duplicate Cart Pickings</div>
                <div class="stat-main amber" id="statDupCount">{metrics['duplicate_pickings_count']}</div>
                <div class="stat-sub">Weight: <strong>{metrics['duplicate_weight']}g</strong> across SM counters</div>
            </div>
            <div class="card">
                <div class="card-title">Wrong Header (DMD/Stock/M)</div>
                <div class="stat-main red" id="statDmdCount">{metrics['dmd_headers']}</div>
                <div class="stat-sub">Header source set to HO instead of FINAL</div>
            </div>
            <div class="card">
                <div class="card-title">Location Mismatches</div>
                <div class="stat-main cyan" id="statMismatches">{metrics['header_mismatches']}</div>
                <div class="stat-sub">Header location != Physical move location</div>
            </div>
            <div class="card">
                <div class="card-title">Total Cart Pickings</div>
                <div class="stat-main green" id="statTotalPickings">{metrics['total_cart_pickings']}</div>
                <div class="stat-sub">Legitimate to preserve: <strong>{metrics['clean_pickings']}</strong></div>
            </div>
        </div>

        <div class="controls">
            <div class="action-group">
                <label style="font-size:13px; color:var(--text-muted); font-weight:600;">Remediation Action:</label>
                <select id="actionSelect" class="custom-select">
                    <option value="audit_scan">1. [Audit & Preview] Scan All Issues & Labels (Read-Only)</option>
                    <option value="purge_duplicates">2. [Step 1] Purge Duplicate Cart Pickings (Reverses Quants in FINAL & SM/C)</option>
                    <option value="fix_headers">3. [Step 2] Fix Legitimate Picking Headers & Types (FINAL & Branch Warehouse)</option>
                    <option value="full_cleanup" selected>4. [Full Cleanup] Purge Duplicates + Fix Headers (Recommended)</option>
                </select>
            </div>
            <div class="action-group">
                <button class="btn btn-dry" id="btnDryRun" onclick="startExecution(false)"><span>🧪</span> Simulate (Dry Run)</button>
                <div class="confirm-wrapper">
                    <input type="checkbox" id="chkConfirm">
                    <label for="chkConfirm">I confirm live DB update</label>
                </div>
                <button class="btn btn-exec" id="btnExecute" onclick="startExecution(true)" disabled><span>⚡</span> Execute Live</button>
            </div>
        </div>

        <div class="terminal-box">
            <div class="terminal-header">
                <div class="terminal-dots"><span class="dot dot-red"></span><span class="dot dot-yellow"></span><span class="dot dot-green"></span></div>
                <div class="terminal-title" id="terminalStatus">odoo - cart_cleanup (IDLE)</div>
                <div style="font-size:12px; color:var(--accent-cyan); font-weight:600;" id="percentText">0%</div>
            </div>
            <div class="progress-bar-container"><div class="progress-bar" id="progressBar"></div></div>
            <div class="terminal-content" id="terminalLog">
                <div class="log-entry" style="color:var(--text-muted);">Console idle. Select an action above and click "Simulate (Dry Run)" to preview or "Execute Live" to commit.</div>
            </div>
        </div>
    </div>

    <script>
        const BASE_PATH = window.location.pathname.startsWith('/cart_remediation') ? '/cart_remediation' : '/cart_cleanup';
        const chkConfirm = document.getElementById('chkConfirm');
        const btnExecute = document.getElementById('btnExecute');
        const btnDryRun = document.getElementById('btnDryRun');
        const actionSelect = document.getElementById('actionSelect');
        const progressBar = document.getElementById('progressBar');
        const percentText = document.getElementById('percentText');
        const terminalStatus = document.getElementById('terminalStatus');
        const terminalLog = document.getElementById('terminalLog');

        chkConfirm.addEventListener('change', () => {{
            btnExecute.disabled = !chkConfirm.checked;
        }});

        let pollTimer = null;

        function appendLog(line) {{
            const div = document.createElement('div');
            div.className = 'log-entry';
            if (line.includes('SUCCESS:')) div.style.color = 'var(--accent-green)';
            else if (line.includes('ERROR:')) div.style.color = 'var(--accent-red)';
            else if (line.includes('[Step') || line.includes('STARTING:')) div.style.color = 'var(--accent-cyan)';
            else if (line.includes('[DUP]')) div.style.color = 'var(--accent-amber)';
            div.textContent = line;
            terminalLog.appendChild(div);
            terminalLog.scrollTop = terminalLog.scrollHeight;
        }}

        function startExecution(commit) {{
            btnDryRun.disabled = true;
            btnExecute.disabled = true;
            chkConfirm.disabled = true;
            actionSelect.disabled = true;
            terminalLog.innerHTML = '';
            progressBar.style.width = '0%';
            percentText.innerText = '0%';
            terminalStatus.innerText = 'odoo - cart_cleanup (' + (commit ? 'LIVE EXECUTION' : 'DRY RUN') + ')';

            fetch(BASE_PATH + '/start', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{
                    action: actionSelect.value,
                    commit: commit
                }})
            }}).then(res => res.json()).then(data => {{
                pollTimer = setInterval(checkProgress, 800);
            }}).catch(err => {{
                appendLog('Error initiating request: ' + err);
                resetUI();
            }});
        }}

        function checkProgress() {{
            fetch(BASE_PATH + '/progress')
                .then(res => res.json())
                .then(data => {{
                    progressBar.style.width = data.percent + '%';
                    percentText.innerText = data.percent + '%';
                    terminalStatus.innerText = 'odoo - cart_cleanup (' + data.current_step + ')';

                    terminalLog.innerHTML = '';
                    data.logs.forEach(l => appendLog(l));

                    if (data.status === 'DONE' || data.status === 'ERROR') {{
                        clearInterval(pollTimer);
                        resetUI();
                        refreshStats();
                    }}
                }});
        }}

        function resetUI() {{
            btnDryRun.disabled = false;
            chkConfirm.disabled = false;
            btnExecute.disabled = !chkConfirm.checked;
            actionSelect.disabled = false;
        }}

        function refreshStats() {{
            fetch(BASE_PATH + '/status')
                .then(res => res.json())
                .then(d => {{
                    document.getElementById('statDupCount').innerText = d.duplicate_pickings_count;
                    document.getElementById('statDmdCount').innerText = d.dmd_headers;
                    document.getElementById('statMismatches').innerText = d.header_mismatches;
                    document.getElementById('statTotalPickings').innerText = d.total_cart_pickings;
                }});
        }}
    </script>
</body>
</html>
"""
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @http.route(['/cart_cleanup/status', '/cart_remediation/status'], type='http', auth='user', csrf=False)
    def api_status(self, **kw):
        metrics = analyze_database(request.env.cr)
        metrics.pop('duplicate_pickings', None)
        return request.make_response(json.dumps(metrics), headers=[('Content-Type', 'application/json')])

    @http.route(['/cart_cleanup/progress', '/cart_remediation/progress'], type='http', auth='user', csrf=False)
    def api_progress(self, **kw):
        return request.make_response(json.dumps(_PROGRESS), headers=[('Content-Type', 'application/json')])

    @http.route(['/cart_cleanup/start', '/cart_remediation/start'], type='http', auth='user', methods=['POST'], csrf=False)
    def api_start(self, **kw):
        body = request.httprequest.data.decode('utf-8')
        data = json.loads(body) if body else {}
        action = data.get('action', 'audit_scan')
        commit = data.get('commit', False)
        db_name = request.env.cr.dbname

        worker = threading.Thread(target=execute_action_worker, args=(db_name, action, commit), daemon=True)
        worker.start()

        return request.make_response(json.dumps({'status': 'STARTED'}), headers=[('Content-Type', 'application/json')])
