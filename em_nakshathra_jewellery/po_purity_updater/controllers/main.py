# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PoPurityUploadController(http.Controller):

    @http.route('/po_purity/diagnose', type='http', auth='user', website=True, methods=['GET'])
    def diagnose(self, **kwargs):
        data = request.env['po.purity.updater'].sudo().get_diagnostics()
        return request.render('po_purity_updater.diagnose_template', {'data': data})

    @http.route('/po_purity/upload', type='http', auth='user', website=True, methods=['GET'])
    def upload_form(self, **kwargs):
        return request.render('po_purity_updater.upload_form_template', {})

    @http.route('/po_purity/upload/submit', type='http', auth='user', website=True,
                methods=['POST'], csrf=True)
    def upload_submit(self, **post):
        upload = post.get('excel_file')
        result = None
        error = None

        if not upload:
            error = "Please choose an .xlsx file to upload."
        else:
            try:
                file_bytes = upload.read()
                result = request.env['po.purity.updater'].sudo().process_excel(file_bytes)
            except Exception as e:
                _logger.exception("PO purity upload failed")
                # Defensive: if anything above raised a raw DB error outside
                # of a savepoint, the cursor's transaction is left aborted
                # (InFailedSqlTransaction) and every later query - including
                # the ones needed to render this very error page - would
                # fail too. Roll back explicitly so the page can render.
                #
                # But rollback() itself can fail if the underlying DB
                # connection was actually dropped (not just the transaction
                # aborted) - e.g. a network blip or the server closing an
                # idle/long-running connection - which raises
                # psycopg2.InterfaceError: cursor already closed. That must
                # never be allowed to escape unhandled here, or it replaces
                # the real error with a confusing second crash.
                try:
                    request.env.cr.rollback()
                except Exception:
                    _logger.exception(
                        "Could not roll back the DB transaction after upload "
                        "failure - the connection was likely already closed")
                error = str(e)

        return request.render('po_purity_updater.upload_result_template', {
            'result': result,
            'error': error,
        })
