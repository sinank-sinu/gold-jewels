import io
import json
import logging
from datetime import datetime, date

from odoo import http
from odoo.http import request, Response
from odoo.exceptions import AccessDenied

from ..services.file_parser import FileParser
from ..services.import_engine import ImportEngine, LABEL_TEMPLATE_FIELDS
from ..services.xlsx_exporter import XlsxExporter

_logger = logging.getLogger(__name__)

MODEL = 'product.label'

ALLOWED_GROUPS = ['stock.group_stock_manager',
                  'product_label_bulk_import.group_label_bulk_import_manager']


class _SafeEncoder(json.JSONEncoder):
    """Converts datetime/date objects (and other non-serializable types) to strings."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def _dumps(obj):
    return json.dumps(obj, cls=_SafeEncoder)


def _check_access():
    user = request.env.user
    if not any(user.has_group(g) for g in ALLOWED_GROUPS):
        raise AccessDenied('You do not have access to the Product Label Bulk Import feature.')


class LabelImportController(http.Controller):

    # ── Model fields (fixed to product.label) ────────────────────────────────

    @http.route('/product_label/import/get_model_fields', type='json', auth='user', methods=['POST'])
    def get_model_fields(self):
        _check_access()
        env_model = request.env[MODEL]
        skip_types = ('one2many', 'binary', 'html', 'many2many')
        fields_data = env_model.fields_get(attributes=['string', 'type', 'required', 'store'])
        result = []
        for fname, finfo in sorted(fields_data.items(), key=lambda x: x[1]['string']):
            stored = finfo.get('store', True)
            if finfo['type'] not in skip_types and (stored or finfo['type'] == 'many2one'):
                result.append({
                    'name': fname,
                    'label': finfo['string'],
                    'type': finfo['type'],
                    'required': finfo.get('required', False),
                })
        return {'fields': result, 'error': None}

    # ── Auto-map columns to product.label fields ──────────────────────────────

    @http.route('/product_label/import/auto_map', type='json', auth='user', methods=['POST'])
    def auto_map(self, headers):
        _check_access()
        import re

        def _norm(s):
            return re.sub(r'[^a-z0-9]+', '_', str(s).lower()).strip('_')

        EXTRA_SYNONYMS = {
            'product_variant':      'product_id',
            'product_var':          'product_id',
            'variant':              'product_id',
            'variant_name':         'product_id',
            'product':              'product_tmpl_id',
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

        fdata = request.env[MODEL].fields_get(attributes=['string', 'type'])
        idx = {}
        for fname, finfo in fdata.items():
            idx[fname] = fname
            idx[_norm(finfo['string'])] = fname
        for keyword, fname in EXTRA_SYNONYMS.items():
            if fname in fdata:
                idx.setdefault(keyword, fname)

        # Force critical mappings: these column names should ALWAYS map to specific
        # fields to avoid ambiguity or incorrect fallbacks.
        FORCE = {
            'label_name': 'name',  # "Label Name" → name (shows DMDR/56042, etc.)
            'labelname': 'name',
            'label': 'name',
            'source_location': 'source_location_id',  # "Source Location" → source_location_id
            'sourcelocation': 'source_location_id',
            'origin_location': 'source_location_id',
            'destination_location': 'branch_location_id',  # "Destination Location" → branch_location_id
            'destinationlocation': 'branch_location_id',
            'dest_location': 'branch_location_id',
        }
        idx.update(FORCE)

        result = {}
        for col in headers:
            nc = _norm(col)
            result[col] = idx.get(nc, '')
        return result

    # ── File parsing ──────────────────────────────────────────────────────────

    @http.route('/product_label/import/get_sheet_names', type='json', auth='user', methods=['POST'])
    def get_sheet_names(self, file_data, file_name):
        _check_access()
        try:
            names = FileParser.get_sheet_names(file_data, file_name)
            return {'sheets': names, 'error': None}
        except Exception as exc:
            return {'sheets': [], 'error': str(exc)}

    @http.route('/product_label/import/parse_headers', type='json', auth='user', methods=['POST'])
    def parse_headers(self, file_data, file_name, sheet_name=None):
        _check_access()
        try:
            headers = FileParser.get_headers(file_data, file_name, sheet_name=sheet_name or None)
            return {'headers': headers, 'error': None}
        except Exception as exc:
            _logger.exception('parse_headers failed')
            return {'headers': [], 'error': str(exc)}

    @http.route('/product_label/import/get_preview', type='json', auth='user', methods=['POST'])
    def get_preview(self, file_data, file_name, mapping):
        _check_access()
        try:
            headers, rows = FileParser.get_preview(file_data, file_name, num_rows=20)
            reverse = {col: target for col, target in mapping.items() if target}
            mapped_preview = []
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

    @http.route('/product_label/import/create_job', type='json', auth='user', methods=['POST'])
    def create_job(self, file_data, file_name, mapping, batch_size,
                   unique_field=None, auto_create_m2o=False,
                   auto_transfer=False, sheet_name=None):
        _check_access()
        try:
            import math
            file_type = 'csv' if file_name.lower().endswith('.csv') else 'xlsx'
            total_rows = FileParser.count_rows(file_data, file_name,
                                               sheet_name=sheet_name or None)

            attachment = request.env['ir.attachment'].sudo().create({
                'name': file_name,
                'datas': file_data,
                'res_model': 'label.import.job',
                'type': 'binary',
            })

            bs = max(int(batch_size), 100)
            total_batches = math.ceil(total_rows / bs) if total_rows else 0

            job = request.env['label.import.job'].create({
                'name': f'Import – {file_name}',
                'attachment_id': attachment.id,
                'file_name': file_name,
                'file_type': file_type,
                'total_rows': total_rows,
                'batch_size': bs,
                'total_batches': total_batches,
                'mapping_config': json.dumps(mapping),
                'unique_field_name': unique_field or 'name',
                'auto_create_m2o': bool(auto_create_m2o),
                'auto_transfer': bool(auto_transfer),
                'sheet_name': sheet_name or '',
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

    @http.route('/product_label/import/process_batch', type='json', auth='user', methods=['POST'])
    def process_batch(self, job_id):
        _check_access()
        try:
            job = request.env['label.import.job'].browse(int(job_id))
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

            attachment = job.attachment_id.sudo()
            try:
                file_b64 = attachment.datas
            except FileNotFoundError:
                job.state = 'paused'
                return {'error': ('The uploaded file is no longer available on disk. '
                                  'Please create a new import job and re-upload the file.')}
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

            transferred = result.get('transferred', 0)

            request.env['label.import.batch'].create({
                'job_id': job.id,
                'batch_number': batch_number,
                'start_row': offset + 1,
                'end_row': offset + actual_rows_in_batch,
                'created_count': result['created'],
                'updated_count': result['updated'],
                'duplicate_count': result['duplicates'],
                'skipped_count': result['skipped'],
                'error_count': result['errors'],
                'transferred_count': transferred,
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
                'transferred_count': job.transferred_count + transferred,
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
                    'transferred': transferred,
                },
                'total_stats': _job_stats(job),
                'skipped_reasons': _reason_summary(result['skipped_rows']),
                'error_reasons': _reason_summary(result['error_rows']),
                'error': None,
            }

        except Exception as exc:
            _logger.exception('process_batch failed for job %s', job_id)
            try:
                request.env.cr.rollback()
                request.env['label.import.job'].browse(int(job_id)).write({'state': 'paused'})
                request.env.cr.commit()
            except Exception:
                try:
                    request.env.cr.rollback()
                except Exception:
                    pass
            return {'error': str(exc)}

    # ── Job status ────────────────────────────────────────────────────────────

    @http.route('/product_label/import/job_status', type='json', auth='user', methods=['POST'])
    def job_status(self, job_id):
        _check_access()
        job = request.env['label.import.job'].browse(int(job_id))
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

    @http.route('/product_label/import/cancel', type='json', auth='user', methods=['POST'])
    def cancel_job(self, job_id):
        _check_access()
        job = request.env['label.import.job'].browse(int(job_id))
        if job.exists():
            job.action_cancel()
            request.env.cr.commit()
        return {'ok': True}

    # ── Bulk transfer (stock-in) pending labels ───────────────────────────────

    @http.route('/product_label/import/trigger_label_transfers', type='json', auth='user', methods=['POST'])
    def trigger_label_transfers(self, job_id=None):
        _check_access()
        env = request.env

        domain = [('is_stocked_in', '=', False), ('picking_id', '=', False)]
        if job_id:
            job = env['label.import.job'].browse(int(job_id))
            if job.exists() and job.create_date:
                domain.append(('create_date', '>=', job.create_date))

        labels = env[MODEL].sudo().search(domain)
        all_company_ids = env['res.company'].sudo().search([]).ids
        success = 0
        failed_labels = []
        error_counts = {}
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
                err_text = str(exc).split('\n')[0][:120]
                _logger.warning('trigger_label_transfers: label %s (%s) failed: %s',
                                label.id, label.name, exc)
                failed_labels.append(label.name or str(label.id))
                error_counts[err_text] = error_counts.get(err_text, 0) + 1
        request.env.cr.commit()
        aggregated_errors = [f"{cnt}x {msg}" for msg, cnt in sorted(error_counts.items(), key=lambda x: -x[1])]
        return {
            'success': success,
            'failed': len(failed_labels),
            'failed_labels': failed_labels[:20],
            'errors': aggregated_errors,
        }

    # ── Download result files ─────────────────────────────────────────────────

    @http.route('/product_label/import/download/<int:job_id>/<string:result_type>',
                type='http', auth='user', methods=['GET'])
    def download_results(self, job_id, result_type):
        _check_access()
        if result_type not in ('error', 'updated', 'duplicate', 'skipped'):
            return Response('Invalid result type', status=400)

        job = request.env['label.import.job'].browse(job_id)
        if not job.exists():
            return Response('Job not found', status=404)

        xlsx_bytes = XlsxExporter.build(job.batch_ids, result_type)
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

    @http.route('/product_label/import/download_template', type='http', auth='user', methods=['GET'])
    def download_template(self):
        _check_access()
        import xlsxwriter

        GROUP_COLORS = {
            'core':     {'bg': '#2E75B6', 'fg': '#FFFFFF'},
            'link':     {'bg': '#375623', 'fg': '#FFFFFF'},
            'purchase': {'bg': '#843C0C', 'fg': '#FFFFFF'},
            'sale':     {'bg': '#7B2C87', 'fg': '#FFFFFF'},
            'charge':   {'bg': '#833C00', 'fg': '#FFFFFF'},
            'generic':  {'bg': '#404040', 'fg': '#FFFFFF'},
        }

        fmeta = request.env[MODEL].fields_get(attributes=['string', 'type', 'required'])
        ordered = [
            (fn, lbl, grp, hint)
            for fn, lbl, grp, hint in LABEL_TEMPLATE_FIELDS
            if fn in fmeta
        ]

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})

        fmts_map = {}
        for grp, c in GROUP_COLORS.items():
            fmts_map[grp] = wb.add_format({
                'bold': True, 'bg_color': c['bg'], 'font_color': c['fg'],
                'border': 1, 'align': 'center', 'valign': 'vcenter',
            })
        data_fmt = wb.add_format({'border': 1})
        hdr_fmt = wb.add_format({'bold': True, 'bg_color': '#1F4E79',
                                 'font_color': '#FFFFFF', 'border': 1})
        even_fmt = wb.add_format({'border': 1, 'bg_color': '#DEEAF1'})
        odd_fmt = wb.add_format({'border': 1})

        # Data sheet
        ws = wb.add_worksheet('Product Label')
        ws.set_row(0, 30)
        for col_idx, (fname, label, grp, hint) in enumerate(ordered):
            grp_key = grp if grp in fmts_map else 'generic'
            ws.write(0, col_idx, fname, fmts_map[grp_key])
            ws.write_comment(0, col_idx, f'{label}\nType: {hint}', {'width': 240, 'height': 80})
            ws.set_column(col_idx, col_idx, max(22, min(32, len(fname) + 4)))
        ws.freeze_panes(1, 0)
        for row in range(1, 502):
            for col_idx in range(len(ordered)):
                ws.write_blank(row, col_idx, None, data_fmt)

        # Reference / guide sheet
        gws = wb.add_worksheet('Product Label - Guide')
        gws.set_column(0, 0, 32)
        gws.set_column(1, 1, 28)
        gws.set_column(2, 2, 18)
        gws.set_column(3, 3, 38)
        gws.write(0, 0, 'Field (column header)', hdr_fmt)
        gws.write(0, 1, 'Label', hdr_fmt)
        gws.write(0, 2, 'Group', hdr_fmt)
        gws.write(0, 3, 'Notes', hdr_fmt)
        for i, (fname, label, grp, hint) in enumerate(ordered):
            fmt = even_fmt if i % 2 == 0 else odd_fmt
            gws.write(i + 1, 0, fname, fmt)
            gws.write(i + 1, 1, label, fmt)
            gws.write(i + 1, 2, grp, fmt)
            gws.write(i + 1, 3, hint, fmt)
        gws.freeze_panes(1, 0)

        wb.close()
        xlsx_bytes = output.getvalue()

        return request.make_response(
            xlsx_bytes,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename="product_label_import_template.xlsx"'),
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
        'transferred': job.transferred_count,
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