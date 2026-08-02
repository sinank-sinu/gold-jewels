# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import base64
import threading
import uuid
import json
import logging
from ..services.import_script import JobWorkImportService

_logger = logging.getLogger(__name__)

class JobWorkImportController(http.Controller):

    @http.route('/jewellery_job_work_import', type='http', auth='user', website=True)
    def import_page(self, **kw):
        """Render the HTML page for uploading the job work excel."""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Jewellery Job Work Bulk Import</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { padding: 40px; background-color: #f8f9fa; font-family: sans-serif; }
                .container { max-width: 650px; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                .btn-primary { background-color: #7c5dfa; border-color: #7c5dfa; }
                .btn-primary:hover { background-color: #6449d8; border-color: #6449d8; }
            </style>
        </head>
        <body>
            <div class="container">
                <h2 class="mb-4 text-center">Jewellery Job Work Bulk Import</h2>
                <form action="/jewellery_job_work_import/upload" method="post" enctype="multipart/form-data">
                    <input type="hidden" name="csrf_token" value="%s"/>
                    <div class="mb-3">
                        <label for="excel_file" class="form-label">Select Excel File (supports Job Works, Issues, & Receipts)</label>
                        <input class="form-control" type="file" id="excel_file" name="excel_file" accept=".xlsx,.xls" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100 py-2">Upload and Process in Background</button>
                </form>
            </div>
        </body>
        </html>
        """ % request.csrf_token()
        return request.make_response(html_content)

    @http.route('/jewellery_job_work_import/upload', type='http', auth='user', methods=['POST'], csrf=True)
    def upload_file(self, excel_file=None, **kw):
        """Handle file upload and trigger background worker thread."""
        if not excel_file:
            return request.make_response("No file uploaded.", status=400)
            
        file_content = excel_file.read()
        file_base64 = base64.b64encode(file_content)
        
        task_id = str(uuid.uuid4())
        request.env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'running')
        request.env['ir.config_parameter'].sudo().set_param(f'import_progress_{task_id}', 'Initializing...')
        request.env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', '')
        
        # Spawn daemon worker thread
        db_name = request.env.cr.dbname
        uid = request.env.uid
        context = request.env.context.copy()
        
        thread = threading.Thread(
            target=self._run_import_in_background,
            args=(db_name, uid, context, file_base64, task_id)
        )
        thread.start()
        
        # Display processing dashboard and begin polling
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Importing Job Works...</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { padding: 40px; background-color: #f8f9fa; font-family: sans-serif; }
                .container { max-width: 650px; background: white; padding: 45px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; }
                .spinner-border { width: 3.5rem; height: 3.5rem; color: #7c5dfa; margin-bottom: 20px; }
                .progress-text { font-size: 1.1rem; color: #555; margin-top: 15px; font-weight: bold; }
                .btn-home { background-color: #7c5dfa; color: white; border: none; }
                .btn-home:hover { background-color: #6449d8; color: white; }
            </style>
            <script>
                function checkStatus() {
                    fetch('/jewellery_job_work_import/status?task_id=%(task_id)s')
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'done') {
                            document.getElementById('loading-ui').style.display = 'none';
                            document.getElementById('success-stats').innerText = data.stats || '';
                            document.getElementById('success-ui').style.display = 'block';
                        } else if (data.status === 'error') {
                            document.getElementById('loading-ui').style.display = 'none';
                            document.getElementById('error-reason').innerText = data.error_reason || 'Unknown error occurred.';
                            document.getElementById('error-ui').style.display = 'block';
                        } else {
                            if (data.progress) {
                                document.getElementById('progress-msg').innerText = data.progress;
                            }
                            setTimeout(checkStatus, 2000);
                        }
                    });
                }
                window.onload = checkStatus;
            </script>
        </head>
        <body>
            <div class="container">
                <div id="loading-ui">
                    <div class="spinner-border" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <h2 class="mb-3" style="color: #7c5dfa;">Processing Spreadsheet</h2>
                    <p>Executing data verification, subcontractor balance checks, and validating Odoo stock pickings in the background. Please do not close this window.</p>
                    <div id="progress-msg" class="progress-text">Scanning dataset for duplicates...</div>
                </div>
                
                <div id="success-ui" style="display: none;">
                    <h2 class="text-success mb-3">✓ Import Completed Successfully</h2>
                    <p class="mb-4">All Job Works, Material Issues, and Ornament Receives have been validated and created in database.</p>
                    <div class="alert alert-success" id="success-stats"></div>
                    <a href="/web" class="btn btn-home px-4 py-2 mt-3">Go to Odoo Dashboard</a>
                    <a href="/jewellery_job_work_import" class="btn btn-outline-secondary px-4 py-2 mt-3 ms-2">Upload Another File</a>
                </div>
                
                <div id="error-ui" style="display: none;">
                    <h2 class="text-danger mb-3">⚠️ Import Failed</h2>
                    <p>The import was aborted to protect database integrity. No partial records were created.</p>
                    <div class="alert alert-danger text-start mt-3" id="error-reason" style="white-space: pre-wrap;"></div>
                    <a href="/jewellery_job_work_import" class="btn btn-outline-primary px-4 py-2 mt-3">Try Again</a>
                </div>
            </div>
        </body>
        </html>
        """ % {'task_id': task_id}
        return request.make_response(html_content)

    @http.route('/jewellery_job_work_import/status', type='http', auth='user', methods=['GET'])
    def import_status(self, task_id, **kw):
        """Poll the background import task status."""
        status = request.env['ir.config_parameter'].sudo().get_param(f'import_status_{task_id}', 'running')
        progress = request.env['ir.config_parameter'].sudo().get_param(f'import_progress_{task_id}', '')
        error_reason = request.env['ir.config_parameter'].sudo().get_param(f'import_error_{task_id}', '')
        stats = request.env['ir.config_parameter'].sudo().get_param(f'import_stats_{task_id}', '')
        
        return request.make_response(
            json.dumps({
                'status': status,
                'progress': progress,
                'error_reason': error_reason,
                'stats': stats
            }),
            headers=[('Content-Type', 'application/json')]
        )

    def _run_import_in_background(self, db_name, uid, context, file_base64, task_id):
        """Background worker thread runner."""
        import odoo
        try:
            db_registry = odoo.registry(db_name)
            with db_registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, context)
                service = JobWorkImportService(env)
                service.process_import(file_base64, task_id)
                env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'done')
        except Exception as e:
            _logger.error(f"Background Job Work Import Failed: {e}", exc_info=True)
            try:
                db_registry = odoo.registry(db_name)
                with db_registry.cursor() as cr:
                    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, context)
                    env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'error')
                    if not env['ir.config_parameter'].sudo().get_param(f'import_error_{task_id}', ''):
                        env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', str(e))
            except Exception:
                pass
