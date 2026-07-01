import json
import logging
from datetime import datetime, date

from odoo import http
from odoo.http import request, Response
from odoo.exceptions import AccessDenied


class _SafeEncoder(json.JSONEncoder):
    """Converts datetime/date objects and any other non-serializable types to strings."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def _dumps(obj):
    return json.dumps(obj, cls=_SafeEncoder)

from ..services.file_parser import FileParser
from ..services.import_engine import ImportEngine, PO_FIELDS, POL_FIELDS, LABEL_TEMPLATE_FIELDS
from ..services.xlsx_exporter import XlsxExporter

_logger = logging.getLogger(__name__)

ALLOWED_GROUPS = ['purchase.group_purchase_manager',
                  'purchase_order_bulk_import.group_po_bulk_import_manager']


def _check_access():
    user = request.env.user
    if not any(user.has_group(g) for g in ALLOWED_GROUPS):
        raise AccessDenied('You do not have access to the Purchase Order Bulk Import feature.')


class POImportController(http.Controller):

    # ── Model catalogue ───────────────────────────────────────────────────────

    @http.route('/purchase/import/get_importable_models', type='json', auth='user', methods=['POST'])
    def get_importable_models(self):
        _check_access()
        models = request.env['ir.model'].sudo().search(
            [('transient', '=', False)], order='name asc'
        )
        return [{'model': m.model, 'name': m.name} for m in models]

    @http.route('/purchase/import/get_model_fields', type='json', auth='user', methods=['POST'])
    def get_model_fields(self, model_name):
        _check_access()
        try:
            env_model = request.env[model_name]
        except KeyError:
            return {'fields': [], 'error': f'Model "{model_name}" not found.'}
        skip_types = ('one2many', 'binary', 'html', 'many2many')
        fields_data = env_model.fields_get(attributes=['string', 'type', 'required', 'store'])
        result = []
        for fname, finfo in sorted(fields_data.items(), key=lambda x: x[1]['string']):
            if finfo['type'] not in skip_types and finfo.get('store', True):
                result.append({
                    'name': fname,
                    'label': finfo['string'],
                    'type': finfo['type'],
                    'required': finfo.get('required', False),
                })
        return {'fields': result, 'error': None}

    # ── Field catalogue (Purchase Order – kept for backward compat) ───────────

    @http.route('/purchase/import/get_fields', type='json', auth='user', methods=['POST'])
    def get_fields(self):
        _check_access()
        return {'po_fields': PO_FIELDS, 'pol_fields': POL_FIELDS}

    # ── Auto-map columns to Odoo fields ──────────────────────────────────────

    @http.route('/purchase/import/auto_map', type='json', auth='user', methods=['POST'])
    def auto_map(self, headers, model_name, line_model_name=None):
        """
        Given a list of Excel column headers, return the best-guess Odoo field
        mapping using server-side field metadata.
        Returns { col: "h:field" | "l:field" | "field" | "" }
        """
        _check_access()
        import re

        def _norm(s):
            return re.sub(r'[^a-z0-9]+', '_', str(s).lower()).strip('_')

        # Extra synonyms applied on top of the label-based index.
        # Key = normalised column keyword, value = Odoo field name.
        EXTRA_SYNONYMS = {
            'product_variant':      'product_id',
            'product_var':          'product_id',
            'variant':              'product_id',
            'variant_name':         'product_id',
            'product_template':     'product_tmpl_id',
            'purchase_order':       'purchase_id',
            'purchase_order_no':    'purchase_id',
            'po_ref':               'purchase_id',
            'po_no':                'purchase_id',
            'po_number':            'purchase_id',
            'branch':               'branch_id',
            'branch_name':          'branch_id',
            'destination_location': 'branch_location_id',
            'source_location':      'source_location_id',
            'purity':               'purity_id',
            'sale_purity':          'sale_purity_id',
            'label_reference':      'name',
            'label_ref':            'name',
            'age':                  'age_import',
            'age_days':             'age_import',
            'days':                 'age_import',
            'label_age':            'age_import',
        }

        def _build_index(model):
            try:
                fdata = request.env[model].fields_get(attributes=['string', 'type'])
            except KeyError:
                return {}
            idx = {}
            for fname, finfo in fdata.items():
                idx[fname] = fname                          # exact field name
                idx[_norm(finfo['string'])] = fname         # normalised label
            # Apply extra synonyms (only for fields that exist in this model)
            for keyword, fname in EXTRA_SYNONYMS.items():
                if fname in fdata:
                    idx.setdefault(keyword, fname)
            return idx

        hdr_idx = _build_index(model_name) if model_name else {}
        line_idx = _build_index(line_model_name) if line_model_name else {}
        has_lines = bool(line_model_name)

        result = {}
        for col in headers:
            nc = _norm(col)
            mapped = ''
            if has_lines:
                if nc in hdr_idx:
                    mapped = 'h:' + hdr_idx[nc]
                elif nc in line_idx:
                    mapped = 'l:' + line_idx[nc]
            else:
                if nc in hdr_idx:
                    mapped = hdr_idx[nc]
            result[col] = mapped
        return result

    # ── PO search (for target PO selector) ───────────────────────────────────

    @http.route('/purchase/import/search_po', type='json', auth='user', methods=['POST'])
    def search_po(self, query):
        _check_access()
        domain = [('state', 'not in', ('cancel', 'done'))]
        if query:
            domain += ['|', ('name', 'ilike', query), ('partner_id.name', 'ilike', query)]
        pos = request.env['purchase.order'].search(domain, limit=20, order='name asc')
        return [{'id': po.id, 'name': po.name,
                 'vendor': po.partner_id.name, 'state': po.state} for po in pos]

    # ── File parsing ──────────────────────────────────────────────────────────

    @http.route('/purchase/import/get_sheet_names', type='json', auth='user', methods=['POST'])
    def get_sheet_names(self, file_data, file_name):
        _check_access()
        try:
            names = FileParser.get_sheet_names(file_data, file_name)
            return {'sheets': names, 'error': None}
        except Exception as exc:
            return {'sheets': [], 'error': str(exc)}

    @http.route('/purchase/import/parse_headers', type='json', auth='user', methods=['POST'])
    def parse_headers(self, file_data, file_name, sheet_name=None):
        _check_access()
        try:
            headers = FileParser.get_headers(file_data, file_name, sheet_name=sheet_name or None)
            return {'headers': headers, 'error': None}
        except Exception as exc:
            _logger.exception('parse_headers failed')
            return {'headers': [], 'error': str(exc)}

    @http.route('/purchase/import/get_preview', type='json', auth='user', methods=['POST'])
    def get_preview(self, file_data, file_name, mapping):
        _check_access()
        try:
            headers, rows = FileParser.get_preview(file_data, file_name, num_rows=20)
            # Re-label columns using mapping for display
            mapped_preview = []
            reverse = {}
            for excel_col, target in mapping.items():
                if target:
                    if '.' in target:
                        prefix, _, field = target.partition('.')
                        reverse[excel_col] = f'[{prefix.upper()}] {field}'
                    else:
                        reverse[excel_col] = target
            for row in rows:
                mapped_row = {}
                for col, val in row.items():
                    display_key = reverse.get(col, col)
                    mapped_row[display_key] = val if val is not None else ''
                mapped_preview.append(mapped_row)
            return {'rows': mapped_preview, 'error': None}
        except Exception as exc:
            _logger.exception('get_preview failed')
            return {'rows': [], 'error': str(exc)}

    # ── Job creation ──────────────────────────────────────────────────────────

    @http.route('/purchase/import/create_job', type='json', auth='user', methods=['POST'])
    def create_job(self, file_data, file_name, mapping, batch_size, match_field,
                   model_name=None, unique_field=None,
                   has_lines=False, line_model=None, line_link_field=None,
                   group_by_field=None, auto_create_m2o=False, target_po_id=None,
                   auto_confirm_receive=False, auto_create_bill=False,
                   sheet_name=None):
        _check_access()
        try:
            file_type = 'csv' if file_name.lower().endswith('.csv') else 'xlsx'
            total_rows = FileParser.count_rows(file_data, file_name,
                                               sheet_name=sheet_name or None)

            # Store file as ir.attachment (no_document=True keeps it off Documents app)
            attachment = request.env['ir.attachment'].sudo().create({
                'name': file_name,
                'datas': file_data,
                'res_model': 'po.import.job',
                'type': 'binary',
            })

            import math
            bs = max(int(batch_size), 100)
            total_batches = math.ceil(total_rows / bs)

            job = request.env['po.import.job'].create({
                'name': f'Import – {file_name}',
                'attachment_id': attachment.id,
                'file_name': file_name,
                'file_type': file_type,
                'total_rows': total_rows,
                'batch_size': bs,
                'total_batches': total_batches,
                'match_field': match_field,
                'mapping_config': json.dumps(mapping),
                'model_name': model_name or 'purchase.order',
                'unique_field_name': unique_field or 'name',
                'has_lines': bool(has_lines),
                'line_model_name': line_model or '',
                'line_link_field': line_link_field or '',
                'group_by_field': group_by_field or unique_field or 'name',
                'auto_create_m2o': bool(auto_create_m2o),
                'auto_confirm_receive': bool(auto_confirm_receive),
                'auto_create_bill': bool(auto_create_bill),
                'sheet_name': sheet_name or '',
                'target_po_id': int(target_po_id) if target_po_id else False,
                'state': 'draft',
            })

            return {'job_id': job.id, 'total_rows': total_rows,
                    'total_batches': total_batches, 'error': None}
        except Exception as exc:
            _logger.exception('create_job failed')
            try:
                request.env.cr.rollback()
            except Exception:
                pass
            return {'job_id': None, 'error': str(exc)}

    # ── Batch processing ──────────────────────────────────────────────────────

    @http.route('/purchase/import/process_batch', type='json', auth='user', methods=['POST'])
    def process_batch(self, job_id):
        _check_access()
        try:
            job = request.env['po.import.job'].browse(int(job_id))
            if not job.exists():
                return {'error': 'Job not found'}
            if job.state == 'cancelled':
                return {'error': 'Job was cancelled'}
            if job.state == 'done':
                return {'done': True, 'stats': _job_stats(job)}

            job.state = 'processing'
            request.env.cr.commit()

            offset = job.current_offset
            batch_size = job.batch_size
            batch_number = job.current_batch_number + 1

            # Read file attachment (guard against missing filestore files)
            attachment = job.attachment_id.sudo()
            try:
                file_b64 = attachment.datas
            except FileNotFoundError:
                job.state = 'paused'
                return {
                    'error': (
                        'The uploaded file is no longer available on disk. '
                        'Please create a new import job and re-upload the file.'
                    )
                }
            if not file_b64:
                job.state = 'paused'
                return {'error': 'File attachment not found or empty'}

            file_name = job.file_name
            sheet_name = job.sheet_name or None
            headers = FileParser.get_headers(file_b64, file_name, sheet_name=sheet_name)

            rows_list = list(FileParser.iter_batch(
                file_b64, file_name, headers, offset, batch_size, sheet_name=sheet_name
            ))
            actual_rows_in_batch = len(rows_list)

            numbered = ((offset + i + 1, row) for i, row in enumerate(rows_list))

            engine = ImportEngine(request.env, job)
            result = engine.process_rows(numbered)

            lines_created = result.get('lines_created', 0)

            batch = request.env['po.import.batch'].create({
                'job_id': job.id,
                'batch_number': batch_number,
                'start_row': offset + 1,
                'end_row': offset + actual_rows_in_batch,
                'created_count': result['created'],
                'updated_count': result['updated'],
                'duplicate_count': result['duplicates'],
                'skipped_count': result['skipped'],
                'error_count': result['errors'],
                'lines_created_count': lines_created,
                'error_rows_json': _dumps(result['error_rows']),
                'updated_rows_json': _dumps(result['updated_rows']),
                'duplicate_rows_json': _dumps(result['duplicate_rows']),
                'skipped_rows_json': _dumps(result['skipped_rows']),
            })

            new_offset = offset + actual_rows_in_batch
            job.write({
                'current_offset': new_offset,
                'current_batch_number': batch_number,
                'processed_rows': job.processed_rows + actual_rows_in_batch,
                'created_count': job.created_count + result['created'],
                'updated_count': job.updated_count + result['updated'],
                'duplicate_count': job.duplicate_count + result['duplicates'],
                'skipped_count': job.skipped_count + result['skipped'],
                'error_count': job.error_count + result['errors'],
                'lines_created_count': job.lines_created_count + lines_created,
                'state': 'done' if new_offset >= job.total_rows else 'paused',
            })
            request.env.cr.commit()

            return {
                'done': job.state == 'done',
                'batch_number': batch_number,
                'total_batches': job.total_batches,
                'offset': new_offset,
                'total_rows': job.total_rows,
                'remaining': max(job.total_rows - new_offset, 0),
                'batch_stats': {
                    'created': result['created'],
                    'updated': result['updated'],
                    'duplicates': result['duplicates'],
                    'skipped': result['skipped'],
                    'errors': result['errors'],
                    'lines_created': lines_created,
                },
                'total_stats': _job_stats(job),
                'skipped_reasons': _reason_summary(result['skipped_rows']),
                'error_reasons': _reason_summary(result['error_rows']),
                'error': None,
            }

        except Exception as exc:
            _logger.exception('process_batch failed for job %s', job_id)
            try:
                # Must rollback the aborted transaction before any new DB write
                request.env.cr.rollback()
                request.env['po.import.job'].browse(int(job_id)).write({'state': 'paused'})
                request.env.cr.commit()
            except Exception:
                try:
                    request.env.cr.rollback()
                except Exception:
                    pass
            return {'error': str(exc)}

    # ── Job status ────────────────────────────────────────────────────────────

    @http.route('/purchase/import/job_status', type='json', auth='user', methods=['POST'])
    def job_status(self, job_id):
        _check_access()
        job = request.env['po.import.job'].browse(int(job_id))
        if not job.exists():
            return {'error': 'Job not found'}
        return {
            'state': job.state,
            'total_rows': job.total_rows,
            'processed_rows': job.processed_rows,
            'current_batch': job.current_batch_number,
            'total_batches': job.total_batches,
            'progress_pct': job.progress_pct,
            'stats': _job_stats(job),
        }

    # ── Cancel ────────────────────────────────────────────────────────────────

    @http.route('/purchase/import/cancel', type='json', auth='user', methods=['POST'])
    def cancel_job(self, job_id):
        _check_access()
        job = request.env['po.import.job'].browse(int(job_id))
        if job.exists():
            job.action_cancel()
            request.env.cr.commit()
        return {'ok': True}

    # ── PO Summary ────────────────────────────────────────────────────────────

    @http.route('/purchase/import/approve_bills', type='json', auth='user', methods=['POST'])
    def approve_bills(self, job_id=None):
        _check_access()
        env = request.env
        bills = _get_job_bills(env, job_id, approved=False)
        count = len(bills)
        try:
            if bills:
                bills.action_approve_bill()
                request.env.cr.commit()
            return {'approved': count, 'error': None}
        except Exception as exc:
            try:
                request.env.cr.rollback()
            except Exception:
                pass
            return {'approved': 0, 'error': str(exc)}

    @http.route('/purchase/import/confirm_bills', type='json', auth='user', methods=['POST'])
    def confirm_bills(self, job_id=None):
        _check_access()
        from odoo import fields as odoo_fields
        env = request.env
        bills = _get_job_bills(env, job_id, approved=True)
        count = len(bills)
        try:
            if bills:
                no_date = bills.filtered(lambda b: not b.invoice_date)
                if no_date:
                    no_date.write({'invoice_date': odoo_fields.Date.context_today(env['account.move'])})
                bills.action_post()
                request.env.cr.commit()
            return {'confirmed': count, 'error': None}
        except Exception as exc:
            try:
                request.env.cr.rollback()
            except Exception:
                pass
            return {'confirmed': 0, 'error': str(exc)}

    @http.route('/purchase/import/get_po_summary', type='json', auth='user', methods=['POST'])
    def get_po_summary(self, job_id=None):
        _check_access()
        env = request.env

        if job_id:
            job = env['po.import.job'].browse(int(job_id))
            if job.exists():
                po_ids = _job_po_ids(job)
                if po_ids:
                    pos = env['purchase.order'].sudo().browse(po_ids)
                    bills = pos.mapped('invoice_ids').filtered(
                        lambda b: b.move_type == 'in_invoice' and b.state == 'draft'
                    )
                    return {
                        'po_count':        len(po_ids),
                        'pending_approve': len(bills.filtered(lambda b: not b.is_approved)),
                        'pending_confirm': len(bills),
                    }
                return {'po_count': 0, 'pending_approve': 0, 'pending_confirm': 0}

        # Fallback: global counts
        AM = env['account.move'].sudo()
        po_count = env['purchase.order'].sudo().search_count([('state', 'in', ['purchase', 'done'])])
        draft_bills = AM.search([('move_type', '=', 'in_invoice'), ('state', '=', 'draft')])
        return {
            'po_count':        po_count,
            'pending_approve': len(draft_bills.filtered(lambda b: not b.is_approved)),
            'pending_confirm': len(draft_bills),
        }

    @http.route('/purchase/import/get_job_vendors', type='json', auth='user', methods=['POST'])
    def get_job_vendors(self, job_id):
        _check_access()
        env = request.env
        job = env['po.import.job'].browse(int(job_id))
        if not job.exists():
            return []
        po_ids = _job_po_ids(job)
        if not po_ids:
            return []
        pos = env['purchase.order'].sudo().browse(po_ids)
        result = []
        for po in pos:
            result.append({
                'vendor':     po.partner_id.name or 'Unknown',
                'po_name':    po.name or '',
                'line_count': len(po.order_line),
                'state':      po.state or '',
            })
        result.sort(key=lambda x: x['vendor'].lower())
        return result

    @http.route('/purchase/import/trigger_label_transfers', type='json', auth='user', methods=['POST'])
    def trigger_label_transfers(self, job_id=None):
        _check_access()
        env = request.env
        from datetime import datetime, timedelta

        # Scope to labels created since this job started (or all pending if no job)
        domain = [('is_stocked_in', '=', False), ('picking_id', '=', False)]
        if job_id:
            job = env['po.import.job'].browse(int(job_id))
            if job.exists() and job.create_date:
                # Labels created from job start up to now
                domain.append(('create_date', '>=', job.create_date))

        labels = env['product.label'].sudo().search(domain)
        # Allow all companies so location/picking company checks don't block
        all_company_ids = env['res.company'].sudo().search([]).ids
        success = 0
        failed_labels = []
        error_counts = {}  # {error_message: count}
        import logging
        _log = logging.getLogger(__name__)
        for label in labels:
            try:
                with env.cr.savepoint():
                    label.sudo().with_context(
                        skip_immediate=True,
                        skip_backorder=True,
                        skip_sms=True,
                        allowed_company_ids=all_company_ids,
                    ).action_stock_in()
                success += 1
            except Exception as exc:
                # Shorten long error messages to first line only
                err_text = str(exc).split('\n')[0][:120]
                _log.warning('trigger_label_transfers: label %s (%s) failed: %s', label.id, label.name, exc)
                failed_labels.append(label.name or str(label.id))
                error_counts[err_text] = error_counts.get(err_text, 0) + 1
        # Build aggregated error list: "42x <reason>"
        aggregated_errors = [f"{cnt}x {msg}" for msg, cnt in sorted(error_counts.items(), key=lambda x: -x[1])]
        return {
            'success': success,
            'failed': len(failed_labels),
            'failed_labels': failed_labels[:20],
            'errors': aggregated_errors,
        }

    # ── Download result files ─────────────────────────────────────────────────

    @http.route('/purchase/import/download/<int:job_id>/<string:result_type>',
                type='http', auth='user', methods=['GET'])
    def download_results(self, job_id, result_type):
        _check_access()
        if result_type not in ('error', 'updated', 'duplicate', 'skipped'):
            return Response('Invalid result type', status=400)

        job = request.env['po.import.job'].browse(job_id)
        if not job.exists():
            return Response('Job not found', status=404)

        batches = job.batch_ids
        xlsx_bytes = XlsxExporter.build(batches, result_type)
        file_name = f'{result_type}_rows_job_{job_id}.xlsx'

        return request.make_response(
            xlsx_bytes,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename="{file_name}"'),
                ('Content-Length', str(len(xlsx_bytes))),
            ],
        )


    # ── Download import template ──────────────────────────────────────────────

    @http.route('/purchase/import/download_template/<string:model_name>',
                type='http', auth='user', methods=['GET'])
    def download_template(self, model_name):
        _check_access()

        import io
        import xlsxwriter

        skip_types = ('one2many', 'binary', 'html', 'many2many')

        GROUP_COLORS = {
            'core':     {'bg': '#2E75B6', 'fg': '#FFFFFF'},
            'link':     {'bg': '#375623', 'fg': '#FFFFFF'},
            'purchase': {'bg': '#843C0C', 'fg': '#FFFFFF'},
            'sale':     {'bg': '#7B2C87', 'fg': '#FFFFFF'},
            'charge':   {'bg': '#833C00', 'fg': '#FFFFFF'},
            'generic':  {'bg': '#404040', 'fg': '#FFFFFF'},
        }

        def _get_ordered_fields(mname):
            try:
                fmeta = request.env[mname].fields_get(attributes=['string', 'type', 'required'])
            except KeyError:
                return None, None
            if mname == 'product.label':
                ordered = [
                    (fn, lbl, grp, hint)
                    for fn, lbl, grp, hint in LABEL_TEMPLATE_FIELDS
                    if fn in fmeta
                ]
            else:
                ordered = [
                    (fn, finfo['string'], 'generic', finfo['type'])
                    for fn, finfo in sorted(fmeta.items(), key=lambda x: x[0])
                    if finfo['type'] not in skip_types
                ]
            return fmeta, ordered

        def _write_data_sheet(wb, sheet_label, ordered, fmts_map, data_fmt, ref_fmt):
            ws = wb.add_worksheet(sheet_label[:31])
            ws.set_row(0, 30)
            for col_idx, (fname, label, grp, hint) in enumerate(ordered):
                grp_key = grp if grp in fmts_map else 'generic'
                ws.write(0, col_idx, fname, fmts_map[grp_key])
                ws.write_comment(0, col_idx, f'{label}\nType: {hint}', {
                    'width': 240, 'height': 80,
                })
                ws.set_column(col_idx, col_idx, max(22, min(32, len(fname) + 4)))
            ws.freeze_panes(1, 0)
            for row in range(1, 502):
                for col_idx in range(len(ordered)):
                    ws.write_blank(row, col_idx, None, data_fmt)

        def _write_ref_sheet(wb, sheet_label, ordered, hdr_fmt, even_fmt, odd_fmt):
            ws = wb.add_worksheet(sheet_label[:31])
            ws.set_column(0, 0, 32)
            ws.set_column(1, 1, 28)
            ws.set_column(2, 2, 18)
            ws.set_column(3, 3, 38)
            ws.write(0, 0, 'Field (column header)', hdr_fmt)
            ws.write(0, 1, 'Label',                hdr_fmt)
            ws.write(0, 2, 'Type',                 hdr_fmt)
            ws.write(0, 3, 'Notes',                hdr_fmt)
            for i, (fname, label, grp, hint) in enumerate(ordered):
                fmt = even_fmt if i % 2 == 0 else odd_fmt
                ws.write(i + 1, 0, fname,  fmt)
                ws.write(i + 1, 1, label,  fmt)
                ws.write(i + 1, 2, grp,    fmt)
                ws.write(i + 1, 3, hint,   fmt)
            ws.freeze_panes(1, 0)

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})

        # ── shared formats ────────────────────────────────────────────────────
        fmts_map = {}
        for grp, c in GROUP_COLORS.items():
            fmts_map[grp] = wb.add_format({
                'bold': True, 'bg_color': c['bg'], 'font_color': c['fg'],
                'border': 1, 'align': 'center', 'valign': 'vcenter',
            })
        data_fmt = wb.add_format({'border': 1})
        ref_fmt  = wb.add_format({'italic': True, 'font_color': '#555555',
                                   'bg_color': '#F2F2F2', 'border': 1, 'text_wrap': True})
        hdr_fmt  = wb.add_format({'bold': True, 'bg_color': '#1F4E79',
                                   'font_color': '#FFFFFF', 'border': 1})
        even_fmt = wb.add_format({'border': 1, 'bg_color': '#DEEAF1'})
        odd_fmt  = wb.add_format({'border': 1})

        # ── decide which model sheets to generate ────────────────────────────
        # Always include purchase.order + product.label.
        # If a different model was requested, include it too.
        models_to_include = ['purchase.order', 'product.label']
        if model_name not in models_to_include:
            models_to_include.insert(0, model_name)

        for mname in models_to_include:
            fmeta, ordered = _get_ordered_fields(mname)
            if ordered is None:
                continue
            sheet_label = mname.replace('.', ' ').title()   # e.g. "Product Label"
            _write_data_sheet(wb, sheet_label, ordered, fmts_map, data_fmt, ref_fmt)
            _write_ref_sheet(wb, f'{sheet_label} - Guide', ordered, hdr_fmt, even_fmt, odd_fmt)

        wb.close()
        xlsx_bytes = output.getvalue()

        safe_name = model_name.replace('.', '_')
        file_name = f'{safe_name}_import_template.xlsx'

        return request.make_response(
            xlsx_bytes,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename="{file_name}"'),
                ('Content-Length', str(len(xlsx_bytes))),
            ],
        )


def _job_stats(job):
    return {
        'created': job.created_count,
        'updated': job.updated_count,
        'duplicates': job.duplicate_count,
        'skipped': job.skipped_count,
        'errors': job.error_count,
        'lines_created': job.lines_created_count,
        'processed': job.processed_rows,
        'total': job.total_rows,
        'progress_pct': job.progress_pct,
    }


def _reason_summary(rows, top=8):
    from collections import Counter
    reasons = Counter(
        r.get('reason') or r.get('error') or 'Unknown'
        for r in rows
    )
    return [{'reason': r, 'count': c} for r, c in reasons.most_common(top)]


def _job_po_ids(job):
    """Return the list of purchase.order IDs created/updated by this import job."""
    vendor_po_map = json.loads(job.vendor_po_map or '{}')
    return list({int(v) for v in vendor_po_map.values() if v})


def _get_job_bills(env, job_id, approved):
    """
    Return draft vendor bills scoped to a specific import job's POs.
    Falls back to all draft bills when job_id is None.
    approved=False → bills not yet approved; approved=True → bills already approved.
    """
    AM = env['account.move'].sudo()
    base_domain = [('move_type', '=', 'in_invoice'), ('state', '=', 'draft')]

    if job_id:
        job = env['po.import.job'].browse(int(job_id))
        if job.exists():
            po_ids = _job_po_ids(job)
            if po_ids:
                pos = env['purchase.order'].sudo().browse(po_ids)
                bills = pos.mapped('invoice_ids').filtered(
                    lambda b: b.move_type == 'in_invoice' and b.state == 'draft'
                )
                if approved:
                    return bills.filtered(lambda b: b.is_approved)
                return bills.filtered(lambda b: not b.is_approved)
            return AM.browse([])

    bills = AM.search(base_domain)
    if approved:
        return bills.filtered(lambda b: b.is_approved)
    return bills.filtered(lambda b: not b.is_approved)