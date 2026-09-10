# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import base64
import json
import threading
from ..services.import_script import ImportLabelService
import logging

_logger = logging.getLogger(__name__)

class PurchaseExpenseServiceImportController(http.Controller):

    @http.route('/purchase_expense_service_import', type='http', auth='user', website=True)
    def import_page(self, **kw):
        """Render the HTML page for uploading the purchase label excel."""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Purchase Expense Bulk Import</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { padding: 40px; background-color: #f4f6f9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
                .container { max-width: 650px; background: white; padding: 35px; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.08); }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="d-flex align-items-center mb-4">
                    <div>
                        <h3 class="fw-bold mb-1">Purchase Expense Bulk Import</h3>
                        <p class="text-muted mb-0">Upload Excel file to create Purchase Orders & Vendor Bills</p>
                    </div>
                </div>
                <form action="/purchase_expense_service_import/upload" method="post" enctype="multipart/form-data">
                    <input type="hidden" name="csrf_token" value="%s"/>
                    <div class="mb-4">
                        <label for="excel_file" class="form-label fw-semibold">Excel File (.xlsx)</label>
                        <input class="form-control form-control-lg" type="file" id="excel_file" name="excel_file" accept=".xlsx,.xls" required>
                        <div class="form-text mt-2">Supports files with 10,000+ rows. Real-time progress and summary will be shown.</div>
                    </div>
                    <button type="submit" class="btn btn-primary btn-lg w-100 fw-bold">Upload & Start Import</button>
                </form>
            </div>
        </body>
        </html>
        """ % request.csrf_token()
        return request.make_response(html_content)

    @http.route('/purchase_expense_service_import/upload', type='http', auth='user', methods=['GET', 'POST'], csrf=True)
    def upload_file(self, excel_file=None, **kw):
        """Handle the file upload and start background processing."""
        import uuid
        
        if request.httprequest.method == 'GET':
            return request.redirect('/purchase_expense_service_import')
            
        if not excel_file:
            return request.make_response("No file uploaded.", status=400)
            
        file_content = excel_file.read()
        file_base64 = base64.b64encode(file_content)
        
        task_id = str(uuid.uuid4())
        initial_progress = {
            'status': 'running',
            'current': 0,
            'total': 0,
            'percent': 0,
            'success_count': 0,
            'failed_count': 0,
            'message': 'Analyzing Excel file and grouping bill references...',
            'recent_logs': ['Reading uploaded file...'],
            'failed_records': [],
        }
        request.env['ir.config_parameter'].sudo().set_param(f'import_progress_{task_id}', json.dumps(initial_progress))
        request.env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'running')
        
        # Start background thread
        db_name = request.env.cr.dbname
        uid = request.env.uid
        context = request.env.context.copy()
        
        thread = threading.Thread(
            target=self._run_import_in_background,
            args=(db_name, uid, context, file_base64, task_id)
        )
        thread.start()
        
        # Return immediate loading response to user with real-time live monitoring and complete results breakdown
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Importing Purchase Expenses</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { padding: 40px; background-color: #f4f6f9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
                .container { max-width: 820px; background: white; padding: 35px; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.08); }
                .terminal-box { background: #1e1e24; color: #a9b7c6; font-family: "SFMono-Regular", Consolas, Menlo, monospace; font-size: 13px; border-radius: 8px; padding: 15px; max-height: 240px; overflow-y: auto; text-align: left; }
                .detailed-log-box { max-height: 480px; }
                .log-line { margin-bottom: 3px; line-height: 1.4; word-break: break-word; }
                .log-line.success { color: #50fa7b; }
                .log-line.error { color: #ff5555; }
                .log-line.info { color: #8be9fd; }
                .log-num { color: #6272a4; display: inline-block; width: 45px; text-align: right; margin-right: 12px; user-select: none; }
                .stat-card { border-radius: 10px; padding: 18px 12px; background: #f8f9fa; border: 1px solid #e9ecef; }
                .stat-card.success { background: #e8f5e9; border-color: #c8e6c9; }
                .stat-card.danger { background: #ffebee; border-color: #ffcdd2; }
            </style>
            <script>
                let allImportLogs = [];

                function renderDetailedLogs(logs) {
                    const finalLogContent = document.getElementById('final-log-content');
                    if (!finalLogContent) return;

                    if (!logs || logs.length === 0) {
                        finalLogContent.innerHTML = '<div class="text-muted p-3">No matching log entries found.</div>';
                        return;
                    }

                    finalLogContent.innerHTML = logs.map((l, idx) => {
                        let cls = 'log-line';
                        if (l.includes('Failed') || l.includes('Error')) cls += ' error';
                        else if (l.includes('Processed')) cls += ' success';
                        else cls += ' info';
                        return `<div class="${cls}"><span class="log-num">${idx + 1}.</span>› ${l}</div>`;
                    }).join('');
                }

                function filterLogs(query) {
                    const q = (query || '').trim().toLowerCase();
                    if (!q) {
                        renderDetailedLogs(allImportLogs);
                        return;
                    }
                    const filtered = allImportLogs.filter(l => l.toLowerCase().includes(q));
                    renderDetailedLogs(filtered);
                }

                function copyAllLogs() {
                    if (!allImportLogs || allImportLogs.length === 0) return;
                    const text = allImportLogs.map((l, idx) => `${idx + 1}. ${l}`).join('\\n');
                    navigator.clipboard.writeText(text).then(() => {
                        const btn = document.getElementById('btn-copy-log');
                        if (btn) {
                            const orig = btn.innerHTML;
                            btn.innerHTML = '✓ Copied!';
                            setTimeout(() => { btn.innerHTML = orig; }, 2000);
                        }
                    });
                }

                function downloadLogs() {
                    if (!allImportLogs || allImportLogs.length === 0) return;
                    const text = allImportLogs.map((l, idx) => `${idx + 1}. ${l}`).join('\\n');
                    const blob = new Blob([text], { type: 'text/plain' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'purchase_expense_import_log.txt';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                }

                function checkStatus() {
                    fetch('/purchase_expense_service_import/status?task_id=%(task_id)s')
                    .then(response => response.json())
                    .then(data => {
                        const percent = data.percent || 0;
                        const current = data.current || 0;
                        const total = data.total || 0;
                        const message = data.message || 'Processing records...';
                        
                        // Update Progress Bar
                        const pBar = document.getElementById('progress-bar');
                        if (pBar) {
                            pBar.style.width = percent + '%%';
                            pBar.textContent = percent + '%%';
                        }
                        
                        // Update Live Text Counter
                        const pCounter = document.getElementById('progress-counter');
                        if (pCounter && total > 0) {
                            pCounter.textContent = `Processed ${current} of ${total} bills (${percent}%%)`;
                        } else if (pCounter) {
                            pCounter.textContent = message;
                        }

                        const pSub = document.getElementById('current-message');
                        if (pSub) {
                            pSub.textContent = message;
                        }

                        // Update Live Log Terminal during run
                        const logContent = document.getElementById('log-content');
                        if (logContent && data.recent_logs && data.recent_logs.length > 0) {
                            logContent.innerHTML = data.recent_logs.map(l => {
                                let cls = 'log-line';
                                if (l.includes('Failed')) cls += ' error';
                                else if (l.includes('Processed')) cls += ' success';
                                else cls += ' info';
                                return `<div class="${cls}">› ${l}</div>`;
                            }).join('');
                            const tBox = document.getElementById('terminal-box');
                            if (tBox) tBox.scrollTop = tBox.scrollHeight;
                        }

                        // Check Completion State
                        if (data.status === 'done' || data.status === 'warning') {
                            document.getElementById('loading-ui').style.display = 'none';
                            document.getElementById('results-ui').style.display = 'block';

                            document.getElementById('stat-total').textContent = data.total || current || 0;
                            const statRows = document.getElementById('stat-rows-sub');
                            if (statRows && data.total_rows) {
                                statRows.textContent = `from ${data.total_rows} Excel lines`;
                            }
                            document.getElementById('stat-success').textContent = data.success_count !== undefined ? data.success_count : current;
                            
                            const failedCount = data.failed_count || (data.failed_records ? data.failed_records.length : 0);
                            const statFailed = document.getElementById('stat-failed');
                            statFailed.textContent = failedCount;
                            
                            const statCardFailed = document.getElementById('stat-card-failed');
                            if (failedCount > 0) {
                                statCardFailed.className = 'stat-card danger';
                                statFailed.className = 'display-6 fw-bold text-danger mb-0';
                            } else {
                                statCardFailed.className = 'stat-card success';
                                statFailed.className = 'display-6 fw-bold text-success mb-0';
                            }

                            // Heading and Subtitle
                            const heading = document.getElementById('results-heading');
                            const subText = document.getElementById('results-subtext');
                            if (failedCount === 0) {
                                heading.textContent = 'Import Completed Successfully';
                                heading.className = 'fw-bold text-success mb-2';
                                subText.textContent = `All ${data.total || current} bills and payment lines have been processed and reconciled with 0 errors.`;
                            } else {
                                heading.textContent = 'Import Finished with Warnings';
                                heading.className = 'fw-bold text-warning mb-2';
                                subText.textContent = `${data.success_count} bills succeeded, but ${failedCount} bill(s) encountered issues.`;
                            }

                            // Populate Error Breakdown Table
                            const errorsSection = document.getElementById('errors-section');
                            if (failedCount > 0 && data.failed_records && data.failed_records.length > 0) {
                                errorsSection.style.display = 'block';
                                const tbody = document.getElementById('errors-table-body');
                                tbody.innerHTML = data.failed_records.map(err => {
                                    let ref = typeof err === 'object' ? (err.bill_ref || 'N/A') : err;
                                    let vendor = typeof err === 'object' ? (err.vendor || '-') : '-';
                                    let reason = typeof err === 'object' ? (err.reason || '') : '';
                                    return `
                                        <tr>
                                            <td class="fw-bold text-danger">${ref}</td>
                                            <td>${vendor}</td>
                                            <td class="small text-muted font-monospace">${reason}</td>
                                        </tr>
                                    `;
                                }).join('');
                            } else {
                                errorsSection.style.display = 'none';
                            }

                            // Render complete logs
                            allImportLogs = (data.all_logs && data.all_logs.length > 0) ? data.all_logs : (data.recent_logs || []);
                            renderDetailedLogs(allImportLogs);
                            const accordionBtn = document.getElementById('log-accordion-btn');
                            if (accordionBtn) {
                                accordionBtn.innerHTML = `View Detailed Import Log <span class="badge bg-secondary ms-2">${allImportLogs.length} lines</span>`;
                            }

                        } else if (data.status === 'error') {
                            document.getElementById('loading-ui').style.display = 'none';
                            document.getElementById('error-ui').style.display = 'block';
                            const errDesc = document.getElementById('error-desc');
                            if (errDesc) {
                                errDesc.textContent = data.message || 'An unexpected error occurred during import.';
                            }
                        } else {
                            setTimeout(checkStatus, 1200);
                        }
                    })
                    .catch(err => {
                        setTimeout(checkStatus, 2000);
                    });
                }
                window.onload = checkStatus;
            </script>
        </head>
        <body>
            <div class="container text-center">
                <!-- 1. ACTIVE LIVE PROGRESS UI -->
                <div id="loading-ui">
                    <div class="d-flex align-items-center justify-content-center mb-3">
                        <div class="spinner-border text-primary me-3" role="status" style="width: 2.5rem; height: 2.5rem;">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                        <div class="text-start">
                            <h3 class="fw-bold text-primary mb-0">Importing Expenses...</h3>
                            <small class="text-muted" id="current-message">Processing file in background...</small>
                        </div>
                    </div>

                    <div class="progress mb-2" style="height: 24px; border-radius: 8px;">
                        <div id="progress-bar" class="progress-bar progress-bar-striped progress-bar-animated bg-primary fw-bold" role="progressbar" style="width: 0%%; font-size: 14px;">0%%</div>
                    </div>

                    <div class="d-flex justify-content-between text-muted small mb-4">
                        <span id="progress-counter">Initializing records...</span>
                        <span>Background Engine Active</span>
                    </div>

                    <div class="terminal-box" id="terminal-box">
                        <div id="log-content">
                            <div class="log-line info">› Upload received. Starting background worker thread...</div>
                        </div>
                    </div>
                </div>

                <!-- 2. COMPLETE RESULTS & DETAILED STATS UI -->
                <div id="results-ui" style="display: none;">
                    <div class="mb-3">
                        <svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" fill="currentColor" class="bi bi-clipboard-check-fill text-success" viewBox="0 0 16 16">
                            <path d="M6.5 0A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3Zm3 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3Z"/>
                            <path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1A2.5 2.5 0 0 1 9.5 5h-3A2.5 2.5 0 0 1 4 2.5v-1Zm6.854 7.354-3 3a.5.5 0 0 1-.708 0l-1.5-1.5a.5.5 0 0 1 .708-.708L7.5 10.793l2.646-2.647a.5.5 0 0 1 .708.708Z"/>
                        </svg>
                    </div>

                    <h2 id="results-heading" class="fw-bold text-success mb-2">Import Completed Successfully</h2>
                    <p class="text-muted" id="results-subtext">All bills have been processed and reconciled.</p>

                    <!-- STATS CARDS -->
                    <div class="row g-3 my-4">
                        <div class="col-4">
                            <div class="stat-card">
                                <div class="text-muted small fw-semibold">TOTAL BILLS</div>
                                <div class="display-6 fw-bold text-dark mb-0" id="stat-total">0</div>
                                <div class="text-muted" style="font-size: 11px;" id="stat-rows-sub">(from 0 Excel lines)</div>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="stat-card success">
                                <div class="text-success small fw-semibold">SUCCEEDED</div>
                                <div class="display-6 fw-bold text-success mb-0" id="stat-success">0</div>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="stat-card" id="stat-card-failed">
                                <div class="small fw-semibold text-muted">FAILED / ISSUES</div>
                                <div class="display-6 fw-bold mb-0" id="stat-failed">0</div>
                            </div>
                        </div>
                    </div>

                    <!-- ERROR / ISSUE BREAKDOWN TABLE -->
                    <div id="errors-section" class="text-start mb-4" style="display: none;">
                        <div class="card border-danger">
                            <div class="card-header bg-danger text-white fw-bold d-flex justify-content-between align-items-center">
                                <span>Failed Records & Error Reasons</span>
                                <span class="badge bg-white text-danger">Action Required</span>
                            </div>
                            <div class="table-responsive" style="max-height: 250px; overflow-y: auto;">
                                <table class="table table-hover table-striped mb-0">
                                    <thead class="table-light">
                                        <tr>
                                            <th style="width: 25%%;">Bill Reference</th>
                                            <th style="width: 25%%;">Vendor</th>
                                            <th>Failure Reason</th>
                                        </tr>
                                    </thead>
                                    <tbody id="errors-table-body">
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>

                    <!-- RECENT ACTIVITY LOG ACCORDION -->
                    <div class="accordion mb-4 text-start" id="logAccordion">
                        <div class="accordion-item">
                            <h2 class="accordion-header" id="headingLog">
                                <button class="accordion-button collapsed py-2 fw-semibold" id="log-accordion-btn" type="button" data-bs-toggle="collapse" data-bs-target="#collapseLog">
                                    View Detailed Import Log
                                </button>
                            </h2>
                            <div id="collapseLog" class="accordion-collapse collapse" data-bs-parent="#logAccordion">
                                <div class="accordion-body p-0">
                                    <div class="p-2 bg-light border-bottom d-flex flex-wrap align-items-center justify-content-between gap-2">
                                        <div class="input-group input-group-sm" style="max-width: 320px;">
                                            <span class="input-group-text bg-white">🔍</span>
                                            <input type="text" class="form-control" placeholder="Search bill ref or vendor..." oninput="filterLogs(this.value)">
                                        </div>
                                        <div class="d-flex gap-2">
                                            <button type="button" id="btn-copy-log" class="btn btn-sm btn-outline-secondary" onclick="copyAllLogs()">📋 Copy All</button>
                                            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="downloadLogs()">📥 Download (.txt)</button>
                                        </div>
                                    </div>
                                    <div class="terminal-box detailed-log-box" style="border-radius: 0 0 8px 8px;">
                                        <div id="final-log-content"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- ACTION BUTTONS -->
                    <div class="d-flex justify-content-center gap-3">
                        <a href="/web" class="btn btn-primary btn-lg fw-bold px-4">Go to Odoo Dashboard</a>
                        <a href="/purchase_expense_service_import" class="btn btn-outline-secondary btn-lg px-4">Upload Another File</a>
                    </div>
                </div>

                <!-- 3. FATAL ERROR UI -->
                <div id="error-ui" style="display: none;">
                    <div class="mb-3 text-danger">
                        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" fill="currentColor" class="bi bi-x-circle-fill" viewBox="0 0 16 16">
                            <path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0zM5.354 4.646a.5.5 0 1 0-.708.708L7.293 8l-2.647 2.646a.5.5 0 0 0 .708.708L8 8.707l2.646 2.647a.5.5 0 0 0 .708-.708L8.707 8l2.647-2.646a.5.5 0 0 0-.708-.708L8 7.293 5.354 4.646z"/>
                        </svg>
                    </div>
                    <h2 class="text-danger fw-bold mb-2">Import Failed</h2>
                    <p class="text-muted" id="error-desc">An error occurred during the import process.</p>
                    <div class="d-flex justify-content-center gap-3 mt-4">
                        <a href="/purchase_expense_service_import" class="btn btn-primary px-4">Try Again</a>
                        <a href="/web" class="btn btn-outline-secondary px-4">Return to Odoo</a>
                    </div>
                </div>
            </div>
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
        </body>
        </html>
        """ % {'task_id': task_id}
        return request.make_response(html_content)

    @http.route('/purchase_expense_service_import/status', type='http', auth='user', methods=['GET'])
    def import_status(self, task_id, **kw):
        raw = request.env['ir.config_parameter'].sudo().get_param(f'import_progress_{task_id}', '')
        if raw:
            try:
                return request.make_response(raw, headers=[('Content-Type', 'application/json')])
            except Exception:
                pass
        status = request.env['ir.config_parameter'].sudo().get_param(f'import_status_{task_id}', 'running')
        return request.make_response(json.dumps({'status': status, 'percent': 0, 'message': 'Processing...'}), headers=[('Content-Type', 'application/json')])
        
    def _run_import_in_background(self, db_name, uid, context, file_base64, task_id):
        """Method to run the import engine in a separate thread with a new cursor."""
        import odoo
        db_registry = odoo.registry(db_name)
        recent_logs = []
        all_logs = []

        def progress_callback(current, total, message, failed_records):
            try:
                percent = int((current / total) * 100) if total > 0 else 0
                all_logs.append(message)
                recent_logs.append(message)
                if len(recent_logs) > 50:
                    recent_logs.pop(0)
                with db_registry.cursor() as p_cr:
                    p_env = odoo.api.Environment(p_cr, odoo.SUPERUSER_ID, context)
                    data = {
                        'status': 'running',
                        'current': current,
                        'total': total,
                        'percent': percent,
                        'success_count': current,
                        'failed_count': len(failed_records),
                        'failed_records': failed_records,
                        'message': message,
                        'recent_logs': list(recent_logs),
                    }
                    p_env['ir.config_parameter'].sudo().set_param(f'import_progress_{task_id}', json.dumps(data))
                    p_cr.commit()
            except Exception as pe:
                _logger.warning(f"Failed to record progress: {pe}")

        try:
            with db_registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, context)
                service = ImportLabelService(env)
                summary = service.process_import(file_base64, progress_callback=progress_callback)
            
            with db_registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, context)
                status = 'done' if summary.get('failed_count', 0) == 0 else 'warning'
                env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', status)
                data = {
                    'status': status,
                    'percent': 100,
                    'total': summary.get('total', 0),
                    'total_rows': summary.get('total_rows', 0),
                    'current': summary.get('success_count', 0),
                    'success_count': summary.get('success_count', 0),
                    'failed_count': summary.get('failed_count', 0),
                    'failed_records': summary.get('failed_records', []),
                    'message': f"Import completed: {summary.get('success_count', 0)} succeeded, {summary.get('failed_count', 0)} failed.",
                    'recent_logs': list(recent_logs),
                    'all_logs': list(all_logs),
                }
                env['ir.config_parameter'].sudo().set_param(f'import_progress_{task_id}', json.dumps(data))
                cr.commit()
        except Exception as e:
            _logger.error(f"Background Import Failed: {e}", exc_info=True)
            try:
                with db_registry.cursor() as cr:
                    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, context)
                    env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'error')
                    data = {
                        'status': 'error',
                        'percent': 100,
                        'message': str(e),
                        'recent_logs': list(recent_logs),
                        'all_logs': list(all_logs),
                    }
                    env['ir.config_parameter'].sudo().set_param(f'import_progress_{task_id}', json.dumps(data))
                    cr.commit()
            except Exception:
                pass

