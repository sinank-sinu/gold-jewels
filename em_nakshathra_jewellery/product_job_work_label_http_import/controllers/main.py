import base64
import json
import logging
from odoo import http
from odoo.http import request
from ..services.import_service import ProductLabelImportService

_logger = logging.getLogger(__name__)

class ProductJobWorkLabelImportController(http.Controller):
    @http.route(['/api/import/product_job_work_labels'], type='http', auth='user', methods=['POST'], csrf=False)
    def import_product_labels(self, **post):
        file = post.get('file')
        if not file:
            return request.make_response(json.dumps({'error': 'No file uploaded'}), headers=[('Content-Type', 'application/json')])

        try:
            file_content = file.read()
            file_base64 = base64.b64encode(file_content)

            import threading
            def run_import(env, base64_file):
                with env.registry.cursor() as new_cr:
                    import odoo
                    new_env = odoo.api.Environment(new_cr, env.uid, env.context)
                    service = ProductLabelImportService(new_env)
                    try:
                        service.process_import(base64_file)
                    except Exception as e:
                        _logger.exception("Background import failed.")

            thread = threading.Thread(target=run_import, args=(request.env, file_base64))
            thread.start()
            
            return request.make_response(json.dumps({
                'success': True, 
                'message': 'Import process started in the background. Please check the terminal logs for progress.'
            }), headers=[('Content-Type', 'application/json')])
        except Exception as e:
            _logger.exception("Error starting background product label import.")
            return request.make_response(json.dumps({'error': str(e)}), headers=[('Content-Type', 'application/json')])

    @http.route(['/import/product_job_work_labels'], type='http', auth='user', methods=['GET'])
    def upload_form(self):
        html = """
        <html>
            <head>
                <title>Import Product Labels</title>
                <style>
                    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 40px; background-color: #f4f4f4; }
                    .container { max-width: 600px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                    h2 { color: #333; margin-top: 0; }
                    .file-input { margin: 20px 0; }
                    .btn { background-color: #00A09D; color: white; border: none; padding: 12px 24px; border-radius: 4px; cursor: pointer; font-size: 16px; }
                    .btn:hover { background-color: #008885; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h2>Product Job Work Label Excel Import</h2>
                    <p>Select your <b>.xlsx</b> file and click Import. Processing 10,000+ rows may take a few moments.</p>
                    <form id="importForm">
                        <div class="file-input">
                            <input type="file" id="fileInput" name="file" accept=".xlsx, .xls" required="required" />
                        </div>
                        <button type="submit" class="btn" id="submitBtn">Start Import</button>
                    </form>
                    <div id="statusMessage" style="margin-top: 20px; font-weight: bold;"></div>
                </div>
                <script>
                    document.getElementById('importForm').addEventListener('submit', function(e) {
                        e.preventDefault();
                        const fileInput = document.getElementById('fileInput');
                        const statusMessage = document.getElementById('statusMessage');
                        const submitBtn = document.getElementById('submitBtn');
                        
                        if (fileInput.files.length === 0) return;
                        
                        const formData = new FormData();
                        formData.append('file', fileInput.files[0]);
                        
                        submitBtn.disabled = true;
                        submitBtn.innerText = 'Starting...';
                        statusMessage.innerText = 'Sending request to server...';
                        statusMessage.style.color = '#333';
                        
                        fetch('/api/import/product_job_work_labels', {
                            method: 'POST',
                            body: formData
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                statusMessage.innerText = 'Success: ' + (data.message || 'Import completed.');
                                statusMessage.style.color = 'green';
                            } else {
                                statusMessage.innerText = 'Error: ' + data.error;
                                statusMessage.style.color = 'red';
                            }
                            submitBtn.disabled = false;
                            submitBtn.innerText = 'Start Import';
                        })
                        .catch(err => {
                            statusMessage.innerText = 'Request failed. See console for details.';
                            statusMessage.style.color = 'red';
                            console.error(err);
                            submitBtn.disabled = false;
                            submitBtn.innerText = 'Start Import';
                        });
                    });
                </script>
            </body>
        </html>
        """
        return request.make_response(html)

