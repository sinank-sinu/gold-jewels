# -*- coding: utf-8 -*-
import base64
import json
import logging
import threading
import uuid
from odoo import http
from odoo.http import request
from ..services.import_service import ProductLabelImportService

_logger = logging.getLogger(__name__)


class ProductLabelImportController(http.Controller):

    @http.route(['/product_label_import', '/label_vendor_barcode_import'], type='http', auth='user', website=True)
    def import_page(self, **kw):
        """Render the HTML upload interface for product label vendor and second barcode import."""
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Product Label Vendor &amp; Barcode Import</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.8.1/font/bootstrap-icons.css">
            <style>
                body {
                    padding: 40px 15px;
                    background: linear-gradient(135deg, #f0f4f8 0%%, #e2e8f0 100%%);
                    min-height: 100vh;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                }
                .card-container {
                    max-width: 650px;
                    margin: 0 auto;
                    background: #ffffff;
                    padding: 35px 30px;
                    border-radius: 12px;
                    box-shadow: 0 10px 25px rgba(0,0,0,0.08);
                    border: 1px solid #e2e8f0;
                }
                .header-icon {
                    width: 54px;
                    height: 54px;
                    background: #e0f2fe;
                    color: #0284c7;
                    border-radius: 50%%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 26px;
                    margin-bottom: 15px;
                }
                .btn-primary {
                    background-color: #0284c7;
                    border-color: #0284c7;
                    padding: 12px 20px;
                    font-weight: 600;
                    border-radius: 8px;
                }
                .btn-primary:hover {
                    background-color: #0369a1;
                    border-color: #0369a1;
                }
                .column-pill {
                    display: inline-block;
                    background: #f1f5f9;
                    color: #334155;
                    font-size: 0.82rem;
                    padding: 4px 10px;
                    border-radius: 20px;
                    margin: 2px 2px;
                    font-weight: 500;
                }
            </style>
        </head>
        <body>
            <div class="card-container">
                <div class="header-icon">
                    <i class="bi bi-file-earmark-excel"></i>
                </div>
                <h3 class="fw-bold mb-1">Product Label Vendor &amp; Barcode Import</h3>
                <p class="text-muted small mb-4">
                    Upload an Excel file (.xlsx / .xls) to bulk update Product Labels with Vendor (Supplier) and Second Barcode (Old Barcode).
                </p>

                <form action="/product_label_import/upload" method="post" enctype="multipart/form-data">
                    <input type="hidden" name="csrf_token" value="%s"/>

                    <div class="mb-4">
                        <label for="excel_file" class="form-label fw-semibold">Select Excel File</label>
                        <input class="form-control form-control-lg" type="file" id="excel_file" name="excel_file" accept=".xlsx,.xls" required>
                        <div class="form-text">Supports .xlsx and .xls files of any size with background execution.</div>
                    </div>

                    <div class="row mb-3">
                        <div class="col-md-6 mb-3">
                            <label class="form-label fw-semibold small">Match Existing Labels By</label>
                            <select class="form-select" name="match_by">
                                <option value="auto" selected>Auto (Label No, then Barcode, then Second Barcode)</option>
                                <option value="name">Label Reference / No Only</option>
                                <option value="barcode">Barcode Only</option>
                                <option value="barcode2">Second Barcode Only</option>
                            </select>
                        </div>
                        <div class="col-md-6 mb-3 d-flex align-items-center pt-md-3">
                            <div class="form-check">
                                <input class="form-check-input" type="checkbox" name="create_partner" value="1" id="create_partner" checked>
                                <label class="form-check-label small fw-semibold" for="create_partner">
                                    Create Vendor if Not Found
                                </label>
                            </div>
                        </div>
                    </div>

                    <div class="card bg-light border-0 mb-4">
                        <div class="card-body py-3 px-3">
                            <div class="fw-semibold small text-secondary mb-2"><i class="bi bi-info-circle me-1"></i> Recognized Excel Columns:</div>
                            <div>
                                <span class="column-pill">Label No / Label Name</span>
                                <span class="column-pill">Old BarcodeNo / Second Barcode</span>
                                <span class="column-pill">BarcodeNo / Barcode</span>
                                <span class="column-pill">Supplier Name / Vendor</span>
                                <span class="column-pill">Supp Code / Vendor Code</span>
                                <span class="column-pill">Branch Name</span>
                                <span class="column-pill">Company</span>
                            </div>
                        </div>
                    </div>

                    <button type="submit" class="btn btn-primary w-100 mb-2">
                        <i class="bi bi-cloud-arrow-up me-2"></i>Upload and Process in Background
                    </button>
                    <a href="/web" class="btn btn-outline-secondary w-100 btn-sm">Return to Odoo</a>
                </form>
            </div>
        </body>
        </html>
        """ % request.csrf_token()
        return request.make_response(html_content)

    @http.route(['/product_label_import/upload', '/label_vendor_barcode_import/upload'], type='http', auth='user', methods=['GET', 'POST'], csrf=True)
    def upload_file(self, excel_file=None, match_by='auto', create_partner=None, **kw):
        """Handle upload and initiate background import worker."""
        if request.httprequest.method == 'GET':
            return request.redirect('/product_label_import')

        if not excel_file:
            return request.make_response("No file uploaded.", status=400)

        file_content = excel_file.read()
        file_base64 = base64.b64encode(file_content)

        task_id = str(uuid.uuid4())
        request.env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'running')
        request.env['ir.config_parameter'].sudo().set_param(f'import_result_{task_id}', '')

        db_name = request.env.cr.dbname
        uid = request.env.uid
        context = request.env.context.copy()
        create_partner_bool = True if create_partner in ('1', 'true', 'True', True) else False

        thread = threading.Thread(
            target=self._run_import_in_background,
            args=(db_name, uid, context, file_base64, task_id, match_by, create_partner_bool)
        )
        thread.daemon = True
        thread.start()

        # Render real-time progress & completion UI
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Import Processing...</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.8.1/font/bootstrap-icons.css">
            <style>
                body {
                    padding: 40px 15px;
                    background: linear-gradient(135deg, #f0f4f8 0%%, #e2e8f0 100%%);
                    min-height: 100vh;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                }
                .container-card {
                    max-width: 650px;
                    margin: 0 auto;
                    background: white;
                    padding: 35px 30px;
                    border-radius: 12px;
                    box-shadow: 0 10px 25px rgba(0,0,0,0.08);
                    border: 1px solid #e2e8f0;
                    text-align: center;
                }
                .spinner-border {
                    width: 3.5rem;
                    height: 3.5rem;
                    margin-bottom: 20px;
                    color: #0284c7;
                }
                .stat-box {
                    background: #f8fafc;
                    border: 1px solid #e2e8f0;
                    border-radius: 8px;
                    padding: 15px 10px;
                    text-align: center;
                }
                .stat-num {
                    font-size: 1.6rem;
                    font-weight: 700;
                    color: #0f172a;
                }
                .stat-lbl {
                    font-size: 0.8rem;
                    color: #64748b;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
            </style>
            <script>
                function checkStatus() {
                    fetch('/product_label_import/status?task_id=%(task_id)s')
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'done') {
                            document.getElementById('loading-ui').style.display = 'none';
                            document.getElementById('success-ui').style.display = 'block';

                            if (data.result) {
                                document.getElementById('stat-total').innerText = data.result.total || 0;
                                document.getElementById('stat-updated').innerText = data.result.updated || 0;
                                document.getElementById('stat-unchanged').innerText = data.result.unchanged || 0;
                                document.getElementById('stat-skipped').innerText = data.result.not_found || 0;
                                document.getElementById('stat-vendors').innerText = data.result.vendors_count || 0;

                                if (data.result.unmatched_rows && data.result.unmatched_rows.length > 0) {
                                    document.getElementById('unmatched-section').style.display = 'block';
                                    let tableBody = document.getElementById('unmatched-tbody');
                                    tableBody.innerHTML = '';
                                    data.result.unmatched_rows.forEach(r => {
                                        let row = `<tr>
                                            <td>Row ${r.row}</td>
                                            <td><code>${r.label}</code></td>
                                            <td>${r.barcode}</td>
                                            <td>${r.branch || '-'}</td>
                                            <td>${r.company || '-'}</td>
                                            <td>${r.vendor}</td>
                                        </tr>`;
                                        tableBody.innerHTML += row;
                                    });
                                }
                            }
                        } else if (data.status === 'error') {
                            document.getElementById('loading-ui').style.display = 'none';
                            document.getElementById('error-ui').style.display = 'block';
                            if (data.error) {
                                document.getElementById('error-msg').innerText = data.error;
                            }
                        } else {
                            setTimeout(checkStatus, 2000);
                        }
                    })
                    .catch(err => {
                        setTimeout(checkStatus, 3000);
                    });
                }
                window.onload = checkStatus;
            </script>
        </head>
        <body>
            <div class="container-card">
                <!-- LOADING STATE -->
                <div id="loading-ui">
                    <div class="spinner-border" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <h3 class="fw-bold text-dark mb-2">Importing Records...</h3>
                    <p class="text-muted">
                        Processing Excel file, matching product labels, and updating vendor &amp; second barcode. Please wait...
                    </p>
                </div>

                <!-- SUCCESS STATE -->
                <div id="success-ui" style="display: none;">
                    <div class="text-success mb-3">
                        <i class="bi bi-check-circle-fill" style="font-size: 3.5rem;"></i>
                    </div>
                    <h3 class="fw-bold text-dark mb-1">Import Completed Successfully</h3>
                    <p class="text-muted small mb-4">All rows from the Excel file have been processed.</p>

                    <div class="row g-2 mb-4">
                        <div class="col-4">
                            <div class="stat-box">
                                <div class="stat-num text-primary" id="stat-total">0</div>
                                <div class="stat-lbl">Total Rows</div>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="stat-box">
                                <div class="stat-num text-success" id="stat-updated">0</div>
                                <div class="stat-lbl">Updated</div>
                            </div>
                        </div>
                        <div class="col-4">
                            <div class="stat-box">
                                <div class="stat-num text-secondary" id="stat-unchanged">0</div>
                                <div class="stat-lbl">Up to Date</div>
                            </div>
                        </div>
                        <div class="col-6 mt-2">
                            <div class="stat-box">
                                <div class="stat-num text-warning" id="stat-skipped">0</div>
                                <div class="stat-lbl">Not Found / Skipped</div>
                            </div>
                        </div>
                        <div class="col-6 mt-2">
                            <div class="stat-box">
                                <div class="stat-num text-info" id="stat-vendors">0</div>
                                <div class="stat-lbl">Vendors Processed</div>
                            </div>
                        </div>
                    </div>

                    <!-- UNMATCHED ROWS SECTION -->
                    <div id="unmatched-section" style="display: none;" class="text-start mb-4">
                        <h6 class="fw-bold text-muted small text-uppercase">Unmatched Labels in Odoo:</h6>
                        <div class="table-responsive" style="max-height: 200px; overflow-y: auto;">
                            <table class="table table-sm table-bordered small">
                                <thead class="table-light">
                                    <tr>
                                        <th>Row</th>
                                        <th>Label Ref</th>
                                        <th>Barcode</th>
                                        <th>Branch</th>
                                        <th>Company</th>
                                        <th>Vendor</th>
                                    </tr>
                                </thead>
                                <tbody id="unmatched-tbody"></tbody>
                            </table>
                        </div>
                    </div>

                    <div class="d-flex gap-2 justify-content-center">
                        <a href="/web" class="btn btn-primary px-4">
                            <i class="bi bi-arrow-left me-1"></i> Return to Odoo
                        </a>
                        <a href="/product_label_import" class="btn btn-outline-secondary px-4">
                            <i class="bi bi-upload me-1"></i> Upload Another
                        </a>
                    </div>
                </div>

                <!-- ERROR STATE -->
                <div id="error-ui" style="display: none;">
                    <div class="text-danger mb-3">
                        <i class="bi bi-x-circle-fill" style="font-size: 3.5rem;"></i>
                    </div>
                    <h3 class="fw-bold text-dark mb-2">Import Failed</h3>
                    <p class="text-muted small" id="error-msg">An unexpected error occurred during import.</p>
                    <a href="/product_label_import" class="btn btn-primary mt-3 px-4">Try Again</a>
                </div>
            </div>
        </body>
        </html>
        """ % {'task_id': task_id}
        return request.make_response(html_content)

    @http.route(['/product_label_import/status', '/label_vendor_barcode_import/status'], type='http', auth='user', methods=['GET'])
    def import_status(self, task_id, **kw):
        """Poll import background status and results."""
        status = request.env['ir.config_parameter'].sudo().get_param(f'import_status_{task_id}', 'running')
        result_json = request.env['ir.config_parameter'].sudo().get_param(f'import_result_{task_id}', '')
        error_msg = request.env['ir.config_parameter'].sudo().get_param(f'import_error_{task_id}', '')

        result = {}
        if result_json:
            try:
                result = json.loads(result_json)
            except Exception:
                result = {}

        return request.make_response(
            json.dumps({'status': status, 'result': result, 'error': error_msg}),
            headers=[('Content-Type', 'application/json')]
        )

    def _run_import_in_background(self, db_name, uid, context, file_base64, task_id, match_by, create_partner):
        """Thread worker with independent cursor."""
        import odoo
        try:
            db_registry = odoo.registry(db_name)
            with db_registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, context)
                service = ProductLabelImportService(env)
                result = service.process_import(file_base64, match_by=match_by, create_partner=create_partner)
                env['ir.config_parameter'].sudo().set_param(f'import_result_{task_id}', json.dumps(result))
                env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'done')
        except Exception as e:
            _logger.error("Background Product Label Import Failed: %s", e, exc_info=True)
            try:
                db_registry = odoo.registry(db_name)
                with db_registry.cursor() as cr:
                    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, context)
                    env['ir.config_parameter'].sudo().set_param(f'import_status_{task_id}', 'error')
                    env['ir.config_parameter'].sudo().set_param(f'import_error_{task_id}', str(e))
            except Exception:
                pass
