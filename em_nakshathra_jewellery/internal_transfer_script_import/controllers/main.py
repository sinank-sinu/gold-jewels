import base64
import logging
import os
import tempfile
from io import BytesIO
import openpyxl

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class InterBranchTransferImportController(http.Controller):

    @http.route('/import/inter_branch_transfer', type='http', auth='user', methods=['GET', 'POST'], csrf=False)
    def trigger_inter_branch_import(self, **kwargs):
        if request.httprequest.method == 'GET':
            return self._render_upload_form()

        # Handle POST File Upload
        file_obj = request.httprequest.files.get('excel_file')
        if not file_obj or not file_obj.filename:
            return self._render_error("No file uploaded. Please select a valid Excel file (.xlsx).")

        filename = file_obj.filename
        if not (filename.endswith('.xlsx') or filename.endswith('.xls')):
            return self._render_error(f"Invalid file extension for '{filename}'. Only .xlsx or .xls files are allowed.")

        tmp_path = None
        try:
            # Write uploaded file to disk to avoid MemoryError on large files
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx', prefix='inter_branch_') as tmp:
                tmp_path = tmp.name
                chunk_size = 1024 * 64  # 64 KB chunks
                while True:
                    chunk = file_obj.stream.read(chunk_size)
                    if not chunk:
                        break
                    tmp.write(chunk)

            # Validate headers by reading only row 1 (read_only=True is memory-safe)
            wb_check = openpyxl.load_workbook(tmp_path, read_only=True, data_only=True)
            ws_check = wb_check.active
            headers = [str(cell.value).strip() if cell.value else "" for cell in next(ws_check.iter_rows(min_row=1, max_row=1))]
            wb_check.close()

            req_cols = ["Source Location", "Destination Location"]
            missing_cols = [c for c in req_cols if c not in headers]
            if missing_cols:
                return self._render_error(
                    f"The uploaded Excel file '{filename}' does not match the required table format!<br/><br/>"
                    f"<strong>Missing Required Columns:</strong> {', '.join(missing_cols)}<br/><br/>"
                    f"<strong>Required Headers:</strong> Source Location, Destination Location, and Label Name (or Barcode)."
                )

            # Pass file path to wizard via binary read from disk
            with open(tmp_path, 'rb') as f:
                file_content = f.read()

            wizard = request.env['inter.branch.transfer.import.wizard'].create({
                'file': base64.b64encode(file_content),
                'filename': filename,
            })

            res = wizard.action_import()
            msg = res.get('params', {}).get('message', 'Import Completed Successfully.')
            msg_type = res.get('params', {}).get('type', 'success')

            return self._render_result(filename, msg, msg_type)

        except Exception as e:
            _logger.error("Inter-Branch Transfer Import Route Error: %s", str(e))
            return self._render_error(f"Failed to process file '{filename}': {str(e)}")

        finally:
            # Always clean up temp file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    @http.route('/import/inter_branch_transfer/download_report', type='http', auth='user', methods=['GET'], csrf=False)
    def download_report(self, **kwargs):
        downloads_path = os.path.expanduser('~/Downloads/Skipped_Transfers_Report.csv')
        if not os.path.exists(downloads_path):
            return self._render_error("No Skipped Transfers Report CSV was found. Please run an import first.")
            
        with open(downloads_path, 'rb') as f:
            filecontent = f.read()
            
        headers = [
            ('Content-Type', 'text/csv'),
            ('Content-Disposition', 'attachment; filename="Skipped_Transfers_Report.csv"'),
            ('Content-Length', len(filecontent))
        ]
        return request.make_response(filecontent, headers=headers)

    def _render_upload_form(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Inter-Branch Stock Transfer Importer</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * { box-sizing: border-box; }
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f4f6f9; margin: 0; padding: 40px 20px; color: #333; }
                .container { max-width: 650px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.08); padding: 35px; }
                h2 { color: #1e293b; margin-top: 0; font-size: 24px; font-weight: 700; text-align: center; }
                p.desc { text-align: center; color: #64748b; margin-bottom: 30px; font-size: 14px; }
                .upload-box { border: 2px dashed #cbd5e1; border-radius: 10px; padding: 30px; text-align: center; background-color: #f8fafc; transition: all 0.2s ease; cursor: pointer; }
                .upload-box:hover { border-color: #3b82f6; background-color: #eff6ff; }
                input[type="file"] { display: block; width: 100%; margin: 15px 0; font-size: 14px; }
                .btn { display: block; width: 100%; padding: 14px; background-color: #2563eb; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; margin-top: 20px; transition: background 0.2s; }
                .btn:hover { background-color: #1d4ed8; }
                .info-card { background: #f0f9ff; border-left: 4px solid #0284c7; padding: 15px; border-radius: 6px; margin-top: 25px; font-size: 13px; color: #0369a1; }
                .info-card ul { margin: 8px 0 0 18px; padding: 0; }
                .nav-link { display: block; text-align: center; margin-top: 20px; font-size: 14px; color: #64748b; text-decoration: none; }
                .nav-link:hover { color: #1e293b; text-decoration: underline; }
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Inter-Branch Transfer Importer</h2>
                <p class="desc">Upload any Excel (.xlsx) file with stock transfer data</p>
                
                <form action="/import/inter_branch_transfer" method="POST" enctype="multipart/form-data">
                    <div class="upload-box">
                        <label for="excel_file"><strong>Select Excel File to Upload:</strong></label>
                        <input type="file" id="excel_file" name="excel_file" accept=".xlsx, .xls" required />
                    </div>
                    <button type="submit" class="btn">🚀 Upload & Process Transfers</button>
                </form>

                <div class="info-card">
                    <strong>Excel Format Requirements:</strong>
                    <ul>
                        <li>Must contain columns: <code>Source Location</code> and <code>Destination Location</code></li>
                        <li>Label Identifier: <code>Label Name</code> or <code>Barcode</code></li>
                        <li>Optional Date: <code>Date</code> / <code>Transfer Date</code> (e.g., MM/DD/YYYY HH:MM:SS)</li>
                        <li><strong>Safe Import:</strong> Only existing labels will be transferred. Duplicate entries are automatically skipped.</li>
                    </ul>
                </div>
                
                <div style="margin-top: 25px; text-align: center; background: #fffbeb; padding: 15px; border-radius: 8px; border: 1px solid #fcd34d;">
                    <a href="/import/inter_branch_transfer/download_report" style="color: #b45309; font-weight: 600; text-decoration: none; font-size: 15px;">
                        📥 Download Last Skipped/Error CSV Report
                    </a>
                </div>
                
                <a href="/web" class="nav-link">← Return to Odoo Portal</a>
            </div>
        </body>
        </html>
        """
        return request.make_response(html, headers=[('Content-Type', 'text/html')])

    def _render_result(self, filename, message, msg_type):
        is_success = msg_type == 'success'
        status_color = '#16a34a' if is_success else '#d97706'
        status_title = "Import Completed Successfully" if is_success else "Import Completed with Warnings"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Import Status - {filename}</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * {{ box-sizing: border-box; }}
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f4f6f9; margin: 0; padding: 40px 20px; color: #333; }}
                .container {{ max-width: 650px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.08); padding: 35px; }}
                h2 {{ color: {status_color}; margin-top: 0; font-size: 22px; font-weight: 700; text-align: center; }}
                .file-badge {{ text-align: center; background: #e2e8f0; color: #334155; font-size: 13px; padding: 4px 12px; border-radius: 20px; display: inline-block; margin-bottom: 20px; }}
                .badge-wrapper {{ text-align: center; }}
                pre {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 18px; border-radius: 8px; white-space: pre-wrap; font-size: 13.5px; line-height: 1.5; color: #1e293b; max-height: 350px; overflow-y: auto; text-align: left; }}
                .actions {{ display: flex; gap: 15px; margin-top: 25px; }}
                .btn {{ flex: 1; padding: 12px; text-align: center; border-radius: 8px; font-weight: 600; text-decoration: none; font-size: 14px; cursor: pointer; border: none; }}
                .btn-primary {{ background-color: #2563eb; color: white; }}
                .btn-primary:hover {{ background-color: #1d4ed8; }}
                .btn-secondary {{ background-color: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; }}
                .btn-secondary:hover {{ background-color: #e2e8f0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>{status_title}</h2>
                <div class="badge-wrapper"><span class="file-badge">📄 File: {filename}</span></div>
                
                <pre>{message}</pre>

                <div style="margin-top: 20px; text-align: center; background: #fffbeb; padding: 15px; border-radius: 8px; border: 1px solid #fcd34d;">
                    <a href="/import/inter_branch_transfer/download_report" style="color: #b45309; font-weight: 600; text-decoration: none; font-size: 15px;">
                        📥 Download Error/Skipped CSV Report
                    </a>
                </div>

                <div class="actions">
                    <a href="/import/inter_branch_transfer" class="btn btn-primary">📁 Upload Another Excel File</a>
                    <a href="/web" class="btn btn-secondary">🏠 Back to Odoo</a>
                </div>
            </div>
        </body>
        </html>
        """
        return request.make_response(html, headers=[('Content-Type', 'text/html')])

    def _render_error(self, error_message):
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Import Error</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * {{ box-sizing: border-box; }}
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f4f6f9; margin: 0; padding: 40px 20px; color: #333; }}
                .container {{ max-width: 650px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.08); padding: 35px; border-top: 6px solid #dc2626; }}
                h2 {{ color: #dc2626; margin-top: 0; font-size: 22px; font-weight: 700; text-align: center; }}
                .error-box {{ background: #fef2f2; border: 1px solid #fecaca; padding: 20px; border-radius: 8px; font-size: 14px; line-height: 1.6; color: #991b1b; margin: 20px 0; }}
                .actions {{ display: flex; gap: 15px; margin-top: 25px; }}
                .btn {{ flex: 1; padding: 12px; text-align: center; border-radius: 8px; font-weight: 600; text-decoration: none; font-size: 14px; cursor: pointer; border: none; }}
                .btn-primary {{ background-color: #2563eb; color: white; }}
                .btn-primary:hover {{ background-color: #1d4ed8; }}
                .btn-secondary {{ background-color: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; }}
                .btn-secondary:hover {{ background-color: #e2e8f0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>⚠️ Import Failed</h2>
                <div class="error-box">{error_message}</div>

                <div class="actions">
                    <a href="/import/inter_branch_transfer" class="btn btn-primary">🔄 Try Uploading Again</a>
                    <a href="/web" class="btn btn-secondary">🏠 Back to Odoo</a>
                </div>
            </div>
        </body>
        </html>
        """
        return request.make_response(html, headers=[('Content-Type', 'text/html')])
