import json
import logging
import threading
import psycopg2
import odoo
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Global in-memory progress tracker
_PROGRESS = {
    'status': 'IDLE',      # IDLE, RUNNING, DONE, ERROR
    'percent': 0,
    'current_step': 'Ready',
    'logs': [],
    'is_dry_run': False,
}


def _fetch_counts(cr):
    counts = {
        'enrollment_count': 0,
        'installment_count': 0,
        'move_count': 0,
        'move_line_count': 0,
        'reconcile_count': 0,
        'redemption_count': 0,
        'pinelabs_count': 0,
    }

    def tbl_exists(tbl):
        cr.execute("SELECT to_regclass(%s);", [tbl])
        row = cr.fetchone()
        return bool(row and row[0])

    if tbl_exists('jewellery_scheme_enrollment'):
        cr.execute("SELECT count(*) FROM jewellery_scheme_enrollment;")
        counts['enrollment_count'] = cr.fetchone()[0]

    if tbl_exists('jewellery_scheme_installment'):
        cr.execute("SELECT count(*) FROM jewellery_scheme_installment;")
        counts['installment_count'] = cr.fetchone()[0]

        cr.execute("""
            SELECT count(DISTINCT id) FROM account_move
            WHERE id IN (
                SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                UNION
                SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
            )
            OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%');
        """)
        counts['move_count'] = cr.fetchone()[0]

        cr.execute("""
            SELECT count(*) FROM account_move_line
            WHERE move_id IN (
                SELECT id FROM account_move
                WHERE id IN (
                    SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                    UNION
                    SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
                )
                OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%')
            );
        """)
        counts['move_line_count'] = cr.fetchone()[0]

        if tbl_exists('account_partial_reconcile'):
            cr.execute("""
                SELECT count(*) FROM account_partial_reconcile pr
                JOIN account_move_line l ON pr.debit_move_id = l.id OR pr.credit_move_id = l.id
                WHERE l.move_id IN (
                    SELECT id FROM account_move
                    WHERE id IN (
                        SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                        UNION
                        SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
                    )
                    OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%')
                );
            """)
            counts['reconcile_count'] = cr.fetchone()[0]

    if tbl_exists('scheme_redemption'):
        cr.execute("SELECT count(*) FROM scheme_redemption;")
        counts['redemption_count'] = cr.fetchone()[0]

    if tbl_exists('pinelabs_payment_wizard'):
        cr.execute("SELECT count(*) FROM pinelabs_payment_wizard WHERE scheme_installment_id IS NOT NULL;")
        counts['pinelabs_count'] = cr.fetchone()[0]

    return counts


def _run_cleanup_thread(dbname, commit=False):
    global _PROGRESS
    _PROGRESS['status'] = 'RUNNING'
    _PROGRESS['percent'] = 5
    _PROGRESS['is_dry_run'] = not commit
    _PROGRESS['logs'] = []

    def log(msg, pct=None):
        _logger.info("[Scheme Cleanup] %s", msg)
        _PROGRESS['logs'].append(msg)
        _PROGRESS['current_step'] = msg
        if pct is not None:
            _PROGRESS['percent'] = pct

    mode_label = "LIVE DELETION" if commit else "SAFE DRY-RUN"
    log(f"Starting Scheme Cleanup in {mode_label} mode on database '{dbname}'...", 5)

    registry = odoo.registry(dbname)
    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
        try:
            def table_exists(tbl):
                cr.execute("SELECT to_regclass(%s);", [tbl])
                row = cr.fetchone()
                return bool(row and row[0])

            # 1. Identify all scheme account_move IDs into a temporary table
            log("Identifying all scheme journal entries...", 10)
            cr.execute("""
                CREATE TEMP TABLE tmp_scheme_moves_to_delete AS
                SELECT DISTINCT id FROM account_move
                WHERE id IN (
                    SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                    UNION
                    SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
                )
                OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%');
            """)
            cr.execute("CREATE INDEX IF NOT EXISTS idx_tmp_scheme_moves ON tmp_scheme_moves_to_delete(id);")
            cr.execute("SELECT count(*) FROM tmp_scheme_moves_to_delete;")
            total_moves = cr.fetchone()[0]
            log(f"Found {total_moves:,} scheme journal entries to revert.", 15)

            # 2. Clear foreign keys on sale_order
            if table_exists('sale_order'):
                cr.execute("""
                    SELECT count(*) FROM information_schema.columns 
                    WHERE table_name = 'sale_order' AND column_name = 'active_scheme_id';
                """)
                if cr.fetchone()[0] > 0:
                    cr.execute("UPDATE sale_order SET active_scheme_id = NULL WHERE active_scheme_id IS NOT NULL;")
                    log(f"Cleared active_scheme_id on {cr.rowcount} sale order(s).", 20)

            # 3. Delete pinelabs payment wizards
            if table_exists('pinelabs_payment_wizard'):
                cr.execute("DELETE FROM pinelabs_payment_wizard WHERE scheme_installment_id IS NOT NULL;")
                log(f"Deleted {cr.rowcount} pinelabs_payment_wizard record(s).", 25)

            # 4. Delete scheme redemptions
            if table_exists('scheme_redemption'):
                cr.execute("DELETE FROM scheme_redemption;")
                log(f"Deleted {cr.rowcount} scheme_redemption record(s).", 30)

            # 5. Delete customer scheme records
            if table_exists('customer_scheme_payment'):
                cr.execute("DELETE FROM customer_scheme_payment;")
            if table_exists('customer_scheme'):
                cr.execute("DELETE FROM customer_scheme;")
            log("Cleaned customer_scheme tables.", 35)

            if total_moves > 0:
                # 6. Unlink partial reconciliations
                if table_exists('account_partial_reconcile'):
                    cr.execute("""
                        DELETE FROM account_partial_reconcile
                        WHERE debit_move_id IN (
                            SELECT id FROM account_move_line WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete)
                        )
                        OR credit_move_id IN (
                            SELECT id FROM account_move_line WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete)
                        );
                    """)
                    log(f"Unlinked {cr.rowcount} partial reconciliation(s).", 40)

                # 7. Unlink account_payment
                if table_exists('account_payment'):
                    cr.execute("DELETE FROM account_payment WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
                    log(f"Unlinked {cr.rowcount} account_payment record(s).", 45)

                # 8. Unlink mail followers and messages
                if table_exists('mail_followers'):
                    cr.execute("DELETE FROM mail_followers WHERE res_model = 'account.move' AND res_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
                if table_exists('mail_message'):
                    cr.execute("DELETE FROM mail_message WHERE model = 'account.move' AND res_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
                log("Deleted mail followers and audit messages on scheme moves.", 50)

                # 9. Delete account_move_line
                cr.execute("DELETE FROM account_move_line WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
                log(f"Deleted {cr.rowcount:,} account_move_line record(s).", 65)

            # 10. Disconnect move references and delete installments FIRST
            # (Deleting installments first empties the FK table, making move deletion lightning fast!)
            if table_exists('jewellery_scheme_installment'):
                cr.execute("UPDATE jewellery_scheme_installment SET move_id = NULL, suspense_move_id = NULL;")
                cr.execute("DELETE FROM jewellery_scheme_installment;")
                log(f"Deleted {cr.rowcount:,} scheme installment(s).", 75)

            # 11. Delete enrollments
            if table_exists('jewellery_scheme_enrollment'):
                cr.execute("DELETE FROM jewellery_scheme_enrollment;")
                log(f"Deleted {cr.rowcount:,} scheme enrollment(s).", 85)

            # 12. Delete account_move
            if total_moves > 0:
                cr.execute("DELETE FROM account_move WHERE id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
                log(f"Deleted {cr.rowcount:,} account_move record(s).", 95)

            # 13. Invalidate ORM cache
            env.invalidate_all()
            log("Invalidated Odoo ORM registry cache.", 98)

            if commit:
                cr.commit()
                log("COMMITTED: All scheme data has been permanently reverted and deleted!", 100)
                _PROGRESS['status'] = 'DONE'
            else:
                cr.rollback()
                log("DRY-RUN FINISHED: Transaction successfully rolled back. No data was modified.", 100)
                _PROGRESS['status'] = 'DONE'

        except Exception as e:
            cr.rollback()
            _logger.exception("Error in Scheme Cleanup thread")
            log(f"ERROR: {str(e)}", 100)
            _PROGRESS['status'] = 'ERROR'


class SchemeCleanupController(http.Controller):

    @http.route('/scheme_cleanup', type='http', auth='user')
    def cleanup_dashboard(self, **kwargs):
        cr = request.env.cr
        counts = _fetch_counts(cr)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scheme Data Cleanup &amp; Journal Reversal</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #4361ee;
            --primary-hover: #3751d6;
            --danger: #ef4444;
            --danger-hover: #dc2626;
            --success: #10b981;
            --warning: #f59e0b;
            --bg: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text-main);
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .header h1 {{
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }}
        .header p {{
            color: var(--text-muted);
            font-size: 15px;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
            background: rgba(239, 68, 68, 0.2);
            color: #fca5a5;
            border: 1px solid rgba(239, 68, 68, 0.4);
            margin-bottom: 12px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 18px;
            text-align: center;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        }}
        .stat-card .num {{
            font-size: 26px;
            font-weight: 700;
            color: #38bdf8;
            margin-bottom: 4px;
        }}
        .stat-card .label {{
            font-size: 13px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .action-card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .btn-group {{
            display: flex;
            gap: 14px;
            margin-top: 18px;
            flex-wrap: wrap;
        }}
        button {{
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }}
        .btn-primary {{
            background: var(--primary);
            color: white;
        }}
        .btn-primary:hover {{ background: var(--primary-hover); }}
        .btn-danger {{
            background: var(--danger);
            color: white;
        }}
        .btn-danger:hover {{ background: var(--danger-hover); }}
        .btn-secondary {{
            background: #334155;
            color: #f8fafc;
        }}
        .btn-secondary:hover {{ background: #475569; }}
        .confirm-wrapper {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 14px;
            padding: 12px;
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.3);
            border-radius: 8px;
            font-size: 14px;
            color: #fca5a5;
        }}
        .confirm-wrapper input[type=checkbox] {{
            width: 18px;
            height: 18px;
            cursor: pointer;
        }}
        .progress-box {{
            display: none;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .progress-bar-bg {{
            background: #334155;
            border-radius: 10px;
            height: 22px;
            overflow: hidden;
            margin-bottom: 14px;
        }}
        .progress-bar-fill {{
            background: linear-gradient(90deg, #38bdf8, #818cf8);
            height: 100%;
            width: 0%;
            transition: width 0.4s ease;
        }}
        .step-label {{
            font-size: 14px;
            font-weight: 600;
            color: #38bdf8;
            margin-bottom: 12px;
        }}
        .terminal {{
            background: #090d16;
            border: 1px solid #1e293b;
            border-radius: 8px;
            padding: 14px;
            font-family: 'Courier New', Courier, monospace;
            font-size: 13px;
            max-height: 240px;
            overflow-y: auto;
            color: #a5f3fc;
            line-height: 1.5;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <span class="badge">Production Safe Cleanup Tool</span>
            <h1>Scheme Data Cleanup &amp; Journal Reversal</h1>
            <p>Database: <strong>{request.env.cr.dbname}</strong> | Real-Time Execution Console</p>
        </div>

        <div class="stats-grid" id="statsGrid">
            <div class="stat-card">
                <div class="num" id="cntEnrollments">{counts['enrollment_count']:,}</div>
                <div class="label">Enrollments</div>
            </div>
            <div class="stat-card">
                <div class="num" id="cntInstallments">{counts['installment_count']:,}</div>
                <div class="label">Installments</div>
            </div>
            <div class="stat-card">
                <div class="num" id="cntMoves">{counts['move_count']:,}</div>
                <div class="label">Journal Entries</div>
            </div>
            <div class="stat-card">
                <div class="num" id="cntLines">{counts['move_line_count']:,}</div>
                <div class="label">Move Lines</div>
            </div>
            <div class="stat-card">
                <div class="num" id="cntReconcile">{counts['reconcile_count']:,}</div>
                <div class="label">Reconciliations</div>
            </div>
        </div>

        <div class="action-card">
            <h3 style="margin-bottom: 8px;">Run Controls</h3>
            <p style="color: var(--text-muted); font-size: 14px;">
                You can run a safe <strong>Test Run (Dry Run)</strong> to verify the queries and dependencies without modifying the database, or authorize <strong>Permanent Deletion</strong>.
            </p>

            <div class="confirm-wrapper">
                <input type="checkbox" id="chkConfirm">
                <label for="chkConfirm">I confirm and authorize the permanent deletion of all scheme records and journal entries.</label>
            </div>

            <div class="btn-group">
                <button class="btn-secondary" onclick="startExecution(false)">
                    <span>🧪 Run Safe Dry-Run (No Data Lost)</span>
                </button>
                <button class="btn-danger" id="btnDelete" onclick="startExecution(true)" disabled>
                    <span>🗑️ Revert &amp; Delete All Scheme Data</span>
                </button>
                <button class="btn-secondary" onclick="refreshCounts()">
                    <span>🔄 Refresh Counts</span>
                </button>
                <a href="/web" style="text-decoration: none;">
                    <button type="button" class="btn-secondary">
                        <span>⬅️ Back to Odoo</span>
                    </button>
                </a>
            </div>
        </div>

        <div class="progress-box" id="progressBox">
            <div class="step-label" id="stepLabel">Starting...</div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" id="progressBar"></div>
            </div>
            <div class="terminal" id="terminalLog"></div>
        </div>
    </div>

    <script>
        const chkConfirm = document.getElementById('chkConfirm');
        const btnDelete = document.getElementById('btnDelete');
        const progressBox = document.getElementById('progressBox');
        const progressBar = document.getElementById('progressBar');
        const stepLabel = document.getElementById('stepLabel');
        const terminalLog = document.getElementById('terminalLog');

        chkConfirm.addEventListener('change', () => {{
            btnDelete.disabled = !chkConfirm.checked;
        }});

        function logToTerminal(msg) {{
            const div = document.createElement('div');
            div.textContent = msg;
            terminalLog.appendChild(div);
            terminalLog.scrollTop = terminalLog.scrollHeight;
        }}

        function refreshCounts() {{
            fetch('/scheme_cleanup/counts')
                .then(r => r.json())
                .then(data => {{
                    document.getElementById('cntEnrollments').innerText = data.enrollment_count.toLocaleString();
                    document.getElementById('cntInstallments').innerText = data.installment_count.toLocaleString();
                    document.getElementById('cntMoves').innerText = data.move_count.toLocaleString();
                    document.getElementById('cntLines').innerText = data.move_line_count.toLocaleString();
                    document.getElementById('cntReconcile').innerText = data.reconcile_count.toLocaleString();
                }});
        }}

        let pollInterval = null;
        let seenLogsCount = 0;

        function startExecution(commit) {{
            if (commit && !chkConfirm.checked) {{
                alert('Please check the confirmation box to authorize deletion.');
                return;
            }}

            seenLogsCount = 0;
            progressBox.style.display = 'block';
            terminalLog.innerHTML = '';
            progressBar.style.width = '5%';
            stepLabel.innerText = commit ? 'Starting live deletion...' : 'Starting safe dry-run...';
            btnDelete.disabled = true;

            fetch('/scheme_cleanup/start', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ commit: commit }})
            }})
            .then(r => r.json())
            .then(res => {{
                if (res.error) {{
                    alert(res.error);
                    btnDelete.disabled = !chkConfirm.checked;
                    return;
                }}
                if (pollInterval) clearInterval(pollInterval);
                pollInterval = setInterval(pollProgress, 1000);
            }})
            .catch(err => {{
                alert('Failed to start cleanup: ' + err);
                btnDelete.disabled = !chkConfirm.checked;
            }});
        }}

        function pollProgress() {{
            fetch('/scheme_cleanup/progress')
                .then(r => r.json())
                .then(data => {{
                    progressBar.style.width = data.percent + '%';
                    stepLabel.innerText = data.current_step + ' (' + data.percent + '%)';

                    if (data.logs && data.logs.length > seenLogsCount) {{
                        for (let i = seenLogsCount; i < data.logs.length; i++) {{
                            logToTerminal(data.logs[i]);
                        }}
                        seenLogsCount = data.logs.length;
                    }}

                    if (data.status === 'DONE' || data.status === 'ERROR') {{
                        clearInterval(pollInterval);
                        pollInterval = null;
                        refreshCounts();
                        btnDelete.disabled = !chkConfirm.checked;
                        if (data.status === 'DONE') {{
                            stepLabel.innerHTML = '🎉 <strong>Cleanup Execution Complete! (100%)</strong>';
                        }} else {{
                            stepLabel.innerHTML = '❌ <strong>Error Occurred</strong>';
                        }}
                    }}
                }});
        }}
    </script>
</body>
</html>"""
        return request.make_response(html, headers=[('Content-Type', 'text/html')])

    @http.route('/scheme_cleanup/counts', type='http', auth='user', methods=['GET'])
    def cleanup_counts(self, **kwargs):
        counts = _fetch_counts(request.env.cr)
        return request.make_response(
            json.dumps(counts),
            headers=[('Content-Type', 'application/json')]
        )

    @http.route('/scheme_cleanup/start', type='http', auth='user', methods=['POST'], csrf=False)
    def cleanup_start(self, **kwargs):
        global _PROGRESS
        if _PROGRESS.get('status') == 'RUNNING':
            return request.make_response(
                json.dumps({'error': 'A cleanup task is already running.'}),
                headers=[('Content-Type', 'application/json')]
            )

        try:
            data = json.loads(request.httprequest.data or '{}')
        except Exception:
            data = kwargs
        commit = bool(data.get('commit', False))
        dbname = request.env.cr.dbname

        thread = threading.Thread(target=_run_cleanup_thread, args=(dbname, commit))
        thread.daemon = True
        thread.start()

        return request.make_response(
            json.dumps({'status': 'STARTED', 'commit': commit}),
            headers=[('Content-Type', 'application/json')]
        )

    @http.route('/scheme_cleanup/progress', type='http', auth='user', methods=['GET'])
    def cleanup_progress(self, **kwargs):
        global _PROGRESS
        return request.make_response(
            json.dumps(_PROGRESS),
            headers=[('Content-Type', 'application/json')]
        )
