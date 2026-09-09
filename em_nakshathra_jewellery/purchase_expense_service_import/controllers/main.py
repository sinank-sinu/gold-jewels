# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import base64
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
            <title>Purchase Label Bulk Import</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { padding: 40px; background-color: #f8f9fa; }
                .container { max-width: 600px; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            </style>
        </head>
        <body>
            <div class="container">
                <h2 class="mb-4">Purchase Label Bulk Import</h2>
                <form action="/purchase_expense_service_import/upload" method="post" enctype="multipart/form-data">
                    <input type="hidden" name="csrf_token" value="%s"/>
                    <div class="mb-3">
                        <label for="excel_file" class="form-label">Upload Excel File (10,000+ rows supported)</label>
                        <input class="form-control" type="file" id="excel_file" name="excel_file" accept=".xlsx,.xls" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Upload and Process in Background</button>
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
        
        # Return immediate loading response to user
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Import Processing</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { padding: 40px; background-color: #f8f9fa; }
                .container { max-width: 600px; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; }
                .spinner-border { width: 3rem; height: 3rem; margin-bottom: 20px; }
            </style>
            <script>
                function checkStatus() {
                    fetch('/purchase_expense_service_import/status?task_id=%(task_id)s')
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'done') {
                            document.getElementById('loading-ui').style.display = 'none';
                            document.getElementById('success-ui').style.display = 'block';
                        } else if (data.status === 'error') {
                            document.getElementById('loading-ui').style.display = 'none';
                            document.getElementById('error-ui').style.display = 'block';
                        } else {
                            setTimeout(checkStatus, 3000);
                        }
                    });
                }
                window.onload = checkStatus;
            </script>
        </head>
        <body>
            <div class="container">
                <div id="loading-ui">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <h2 class="text-primary mb-3">Importing Records...</h2>
                    <p>The file is being processed. Please wait until the import completes successfully.</p>
                </div>
                
                <div id="success-ui" style="display: none;">
                    <h2 class="text-success mb-3">Import Completed Successfully</h2>
                    <p>All records have been processed successfully.</p>
                    <p>You can now check the generated Purchase Orders and Vendor Bills in Odoo.</p>
                    <a href="/web" class="btn btn-outline-primary mt-3">Return to Odoo</a>
                    <a href="/purchase_expense_service_import" class="btn btn-outline-secondary mt-3">Upload Another</a>
                </div>
                
                <div id="error-ui" style="display: none;">
                    <h2 class="text-danger mb-3">Import Failed</h2>
                    <p>An error occurred during the import process. Please check the server logs for more details.</p>
                    <a href="/purchase_expense_service_import" class="btn btn-outline-primary mt-3">Try Again</a>
                </div>
            </div>
        </body>
        </html>
        """ % {'task_id': task_id}
        return request.make_response(html_content)

    @http.route('/purchase_expense_service_import/status', type='http', auth='user', methods=['GET'])
    def import_status(self, task_id, **kw):
        import json
        status = request.env['ir.config_parameter'].sudo().get_param(f'import_status_{task_id}', 'running')
        return request.make_response(json.dumps({'status': status}), headers=[('Content-Type', 'application/json')])
        
    def _run_import_in_background(self, db_name, uid, context, file_base64, task_id):
        """Method to run the import engine in a separate thread with a new cursor."""
        import odoo
        try:
            db_registry = odoo.registry(db_name)
            with db_registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, context)
                service = ImportLabelService(env)
                service.process_import(file_base64)
                env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'done')
        except Exception as e:
            _logger.error(f"Background Import Failed: {e}", exc_info=True)
            try:
                db_registry = odoo.registry(db_name)
                with db_registry.cursor() as cr:
                    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, context)
                    env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'error')
            except Exception:
                pass
