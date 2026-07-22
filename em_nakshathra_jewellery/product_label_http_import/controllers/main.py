import base64
import json
import logging
from odoo import http
from odoo.http import request
from ..services.import_service import ProductLabelImportService

_logger = logging.getLogger(__name__)

class ProductLabelImportController(http.Controller):
    @http.route('/api/import/product_labels', type='http', auth='user', methods=['POST'], csrf=False)
    def import_product_labels(self, **post):
        file = post.get('file')
        if not file:
            return request.make_response(json.dumps({'error': 'No file uploaded'}), headers=[('Content-Type', 'application/json')])

        try:
            file_content = file.read()
            file_base64 = base64.b64encode(file_content)

            service = ProductLabelImportService(request.env)
            result = service.process_import(file_base64)
            
            return request.make_response(json.dumps({'success': True, 'result': result}), headers=[('Content-Type', 'application/json')])
        except Exception as e:
            _logger.exception("Error during product label import via HTTP.")
            return request.make_response(json.dumps({'error': str(e)}), headers=[('Content-Type', 'application/json')])

    @http.route('/import/product_labels', type='http', auth='user', methods=['GET'])
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
                    <h2>Product Label Excel Import</h2>
                    <p>Select your <b>.xlsx</b> file and click Import. Processing 10,000+ rows may take a few moments.</p>
                    <form action="/api/import/product_labels" method="POST" enctype="multipart/form-data">
                        <div class="file-input">
                            <input type="file" name="file" accept=".xlsx, .xls" required="required" />
                        </div>
                        <button type="submit" class="btn">Start Import</button>
                    </form>
                </div>
            </body>
        </html>
        """
        return request.make_response(html)
