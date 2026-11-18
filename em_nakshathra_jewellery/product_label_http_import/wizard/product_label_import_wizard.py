import base64
import io
import logging
import re
import threading

import odoo
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from ..services.import_service import ProductLabelImportService

_logger = logging.getLogger(__name__)

BATCH_CHUNK_SIZE = 10
MAX_IMPORT_ROWS = 1000

MANDATORY_EXCEL_COLUMNS = [
    'Label Name',
    'Age (Days)',
    'Product',
    'Product Variant',
    'TYPE',
    'VARIETY',
    'DESIGN',
    'SIZE',
    'STONE COLOUR',
    'METAL COLOUR',
    'Branch',
    'Source Location',
    'Destination Location',
    'Tag Weight (g)',
    'Purity',
    'Barcode',
    'Bill Reference',
    'Bill Date',
    'Purchase Order',
    'Place of supply',
    'GST Treatment',
    'UOM',
    'Order Lines/Quantity',
    'Order Lines/Unit Price',
    'Order Lines/Subtotal',
    'Order Lines/Taxes',
    'Fine Weight  (g)',
    'Sale Gross Weight (g)',
    'Sale Stone Weight (g)',
    'Diamond Weight (g)',
    'Diamond Weight (ct)',
    'Sale Net Weight (g)',
    'Sale Making Charge Type',
    'Sale Making Charge Max',
    'Sale Making Charge Min',
    'Sale Stone Amount',
    'Sale Diamond Amount',
    'Purchase fine Rate / gram',
    'Fine Weight  (g)',
    'Others',
    'Other Weight (g)',
    'Purchase Gross Amount (g)',
    'Purchase Stone Weight (g)',
    'Diamond Weight (g)',
    'Diamond Weight (ct)',
    'Purchase Net Weight (g)',
    'Purchase Making Charge Type',
    'Purchase Making Charge',
    'Purchase Making Charge Amount',
    'MC Fine',
    'Purchase Metal Amount',
    'Purchase Stone Amount',
    'Purchase Diamond Amount',
    'Active',
    'Company',
]


def _normalize_header(name):
    """Collapse multiple spaces and lowercase for header comparison."""
    return re.sub(r'\s+', ' ', str(name or '').strip()).casefold()


class ProductLabelImportFailedLine(models.TransientModel):
    _name = 'product.label.import.failed.line'
    _description = 'Unimported Product Label Line'
    _order = 'row_number asc, id asc'

    wizard_id = fields.Many2one(
        'product.label.import.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    row_number = fields.Integer(string='Excel Row', readonly=True)
    label_name = fields.Char(string='Label Name', readonly=True)
    reason = fields.Text(string='Reason', readonly=True)


class ProductLabelImportWizard(models.TransientModel):
    _name = 'product.label.import.wizard'
    _description = 'Product Label Import Wizard'

    file = fields.Binary(string='Excel File', required=True)
    filename = fields.Char(string='Filename')
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('running', 'Importing'),
            ('done', 'Completed'),
            ('failed', 'Failed'),
        ],
        string='Status',
        default='draft',
        readonly=True,
    )
    total_rows = fields.Integer(string='Total Labels (Max 1000)', readonly=True)
    processed_rows = fields.Integer(string='Processed Rows', readonly=True)
    imported_count = fields.Integer(string='Imported Label Count', readonly=True)
    failed_count = fields.Integer(string='Unimported Label Count', readonly=True)
    progress = fields.Float(string='Progress', readonly=True)
    result_message = fields.Text(string='Import Status', readonly=True)
    failed_line_ids = fields.One2many(
        'product.label.import.failed.line',
        'wizard_id',
        string='Unimported Labels',
        readonly=True,
    )
    failed_excel_file = fields.Binary(string='Unimported Labels Excel', readonly=True)
    failed_excel_filename = fields.Char(string='Unimported Excel Filename', readonly=True)

    def _run_background_import(self, db_name, uid, context, wizard_id, headers, indexed_rows):
        registry = odoo.registry(db_name)
        total = len(indexed_rows)
        imported_total = 0
        failed_total = 0
        processed = 0

        try:
            label_col_idx = next(
                (
                    i for i, h in enumerate(headers)
                    if _normalize_header(h) == 'label name'
                ),
                None,
            )
            company_col_idx = next(
                (
                    i for i, h in enumerate(headers)
                    if _normalize_header(h) == 'company'
                ),
                None,
            )
            company_cache = {}
            seen_in_upload = set()

            for start in range(0, total, BATCH_CHUNK_SIZE):
                chunk = indexed_rows[start:start + BATCH_CHUNK_SIZE]

                rows_to_import = []
                failed_vals_list = []

                with registry.cursor() as cr:
                    env = api.Environment(cr, uid, context)
                    LabelModel = env['product.label'].sudo().with_context(active_test=False)
                    CompanyModel = env['res.company'].sudo()

                    for orig_row_num, row_values in chunk:
                        label_val = ''
                        if label_col_idx is not None and label_col_idx < len(row_values):
                            raw_lbl = row_values[label_col_idx]
                            label_val = str(raw_lbl).strip() if raw_lbl is not None else ''

                        comp_val = ''
                        if company_col_idx is not None and company_col_idx < len(row_values):
                            raw_comp = row_values[company_col_idx]
                            comp_val = str(raw_comp).strip() if raw_comp is not None else ''

                        comp_key = comp_val.casefold()
                        if comp_key not in company_cache:
                            company_cache[comp_key] = CompanyModel.search(
                                [('name', '=ilike', comp_val)], limit=1
                            )
                        company_rec = company_cache[comp_key]

                        if not label_val:
                            failed_vals_list.append({
                                'wizard_id': wizard_id,
                                'row_number': orig_row_num,
                                'label_name': _('Empty'),
                                'reason': _("Skipped because 'Label Name' is empty in the Excel."),
                            })
                            continue

                        dedup_key = (company_rec.id if company_rec else 0, label_val.casefold())
                        if dedup_key in seen_in_upload:
                            failed_vals_list.append({
                                'wizard_id': wizard_id,
                                'row_number': orig_row_num,
                                'label_name': label_val,
                                'reason': _(
                                    "Duplicate Label '%(label)s' for company '%(company)s' in the same Excel file."
                                ) % {
                                    'label': label_val,
                                    'company': company_rec.name if company_rec else comp_val,
                                },
                            })
                            continue

                        if company_rec:
                            existing_label = LabelModel.search([
                                ('company_id', '=', company_rec.id),
                                '|',
                                ('label_name', '=ilike', label_val),
                                ('name', '=ilike', label_val),
                            ], limit=1)
                            if existing_label:
                                failed_vals_list.append({
                                    'wizard_id': wizard_id,
                                    'row_number': orig_row_num,
                                    'label_name': label_val,
                                    'reason': _(
                                        "Label '%(label)s' is already imported in company '%(company)s'."
                                    ) % {
                                        'label': label_val,
                                        'company': company_rec.name,
                                    },
                                })
                                continue

                        seen_in_upload.add(dedup_key)
                        rows_to_import.append((orig_row_num, row_values))

                chunk_created = 0
                captured_failures = []

                if rows_to_import:
                    wb = Workbook()
                    ws = wb.active
                    ws.append(headers)
                    for _orig_row_num, row_values in rows_to_import:
                        ws.append(list(row_values))
                    buf = io.BytesIO()
                    wb.save(buf)
                    chunk_base64 = base64.b64encode(buf.getvalue())

                    class _ChunkFailureHandler(logging.Handler):
                        def emit(self, record):
                            msg = record.getMessage()
                            if msg.startswith('Error on row '):
                                try:
                                    rest = msg[len('Error on row '):]
                                    idx_str, reason_str = rest.split(':', 1)
                                    chunk_row_idx = int(idx_str.strip())
                                    captured_failures.append((chunk_row_idx, reason_str.strip()))
                                except Exception:
                                    pass

                    service_logger = logging.getLogger(
                        'odoo.addons.product_label_http_import.services.import_service'
                    )
                    handler = _ChunkFailureHandler()
                    service_logger.addHandler(handler)
                    try:
                        with registry.cursor() as cr:
                            env = api.Environment(cr, uid, context)
                            service = ProductLabelImportService(env)
                            res = service.process_import(chunk_base64) or {}
                            chunk_created = int(res.get('created', 0))
                    finally:
                        service_logger.removeHandler(handler)

                    failed_by_chunk_idx = dict(captured_failures)
                    for offset, (orig_row_num, row_values) in enumerate(rows_to_import, start=2):
                        label_val = ''
                        if label_col_idx is not None and label_col_idx < len(row_values):
                            raw_lbl = row_values[label_col_idx]
                            label_val = str(raw_lbl).strip() if raw_lbl is not None else ''

                        if offset in failed_by_chunk_idx:
                            failed_vals_list.append({
                                'wizard_id': wizard_id,
                                'row_number': orig_row_num,
                                'label_name': label_val or _('N/A'),
                                'reason': failed_by_chunk_idx[offset],
                            })

                failed_vals_list.sort(key=lambda x: x['row_number'])

                imported_total += chunk_created
                failed_total += len(failed_vals_list)
                processed += len(chunk)
                pct = round((processed / total) * 100.0, 2) if total else 100.0

                with registry.cursor() as cr:
                    env = api.Environment(cr, uid, context)
                    wiz = env['product.label.import.wizard'].sudo().browse(wizard_id)
                    if wiz.exists():
                        if failed_vals_list:
                            env['product.label.import.failed.line'].sudo().create(failed_vals_list)
                        wiz.write({
                            'processed_rows': processed,
                            'imported_count': imported_total,
                            'failed_count': failed_total,
                            'progress': pct,
                            'result_message': _(
                                'Importing... %(processed)s / %(total)s rows processed '
                                '(Imported: %(imported)s, Unimported: %(failed)s).'
                            ) % {
                                'processed': processed,
                                'total': total,
                                'imported': imported_total,
                                'failed': failed_total,
                            },
                        })
                    cr.commit()

            with registry.cursor() as cr:
                env = api.Environment(cr, uid, context)
                wiz = env['product.label.import.wizard'].sudo().browse(wizard_id)
                if wiz.exists():
                    wiz.write({
                        'state': 'done',
                        'progress': 100.0,
                        'result_message': _(
                            'Import completed: %(imported)s label(s) imported, '
                            '%(failed)s label(s) unimported out of %(total)s.'
                        ) % {
                            'imported': imported_total,
                            'failed': failed_total,
                            'total': total,
                        },
                    })
                cr.commit()

        except Exception as exc:
            _logger.exception('Background product label import failed for wizard upload.')
            with registry.cursor() as cr:
                env = api.Environment(cr, uid, context)
                wiz = env['product.label.import.wizard'].sudo().browse(wizard_id)
                if wiz.exists():
                    wiz.write({
                        'state': 'failed',
                        'result_message': _('Import failed: %s') % str(exc),
                    })
                cr.commit()

    def _check_import_access(self):
        user = self.env.user
        if not (
            user.has_group('em_jewellery_management.group_jewellery_manager')
            or user.has_group('stock.group_stock_manager')
            or user.has_group('base.group_system')
        ):
            raise UserError(
                _('Access Denied: Only Managers and Administrators are allowed to import Product Labels.')
            )

    def action_import(self):
        self.ensure_one()
        self._check_import_access()
        if not self.file:
            raise UserError(_('Please upload an Excel file.'))

        headers, indexed_rows = self._validate_and_extract_rows()
        total = len(indexed_rows)

        self.failed_line_ids.unlink()
        self.write({
            'state': 'running',
            'total_rows': total,
            'processed_rows': 0,
            'imported_count': 0,
            'failed_count': 0,
            'progress': 0.0,
            'failed_excel_file': False,
            'failed_excel_filename': False,
            'result_message': _(
                'Importing... 0 / %s rows processed.'
            ) % total,
        })
        self.env.cr.commit()

        thread = threading.Thread(
            target=self._run_background_import,
            args=(
                self.env.cr.dbname,
                self.env.uid,
                dict(self.env.context),
                self.id,
                headers,
                indexed_rows,
            ),
            daemon=True,
        )
        thread.start()

        return self._reopen_wizard_action()

    def action_export_failed_excel(self):
        self.ensure_one()
        if not self.failed_line_ids:
            raise UserError(_('There are no unimported labels to export.'))

        wb = Workbook()
        ws = wb.active
        ws.title = 'Unimported Labels'

        headers = ['Excel Row', 'Label Name', 'Reason']
        ws.append(headers)

        header_fill = PatternFill(start_color='D9534F', end_color='D9534F', fill_type='solid')
        header_font = Font(color='FFFFFF', bold=True)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='left', vertical='center')

        for line in self.failed_line_ids:
            ws.append([
                line.row_number,
                line.label_name or '',
                line.reason or '',
            ])

        ws.column_dimensions['A'].width = 14
        ws.column_dimensions['B'].width = 24
        ws.column_dimensions['C'].width = 80

        buf = io.BytesIO()
        wb.save(buf)
        excel_b64 = base64.b64encode(buf.getvalue())
        export_filename = 'unimported_product_labels.xlsx'

        self.write({
            'failed_excel_file': excel_b64,
            'failed_excel_filename': export_filename,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': (
                f'/web/content/?model={self._name}&id={self.id}'
                f'&field=failed_excel_file&filename_field=failed_excel_filename&download=true'
            ),
            'target': 'self',
        }

    def _reopen_wizard_action(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _validate_mandatory_headers(self, raw_headers):
        """Ensure all mandatory Excel columns exist (including duplicate columns)."""
        actual_counts = {}
        for h in raw_headers:
            norm = _normalize_header(h)
            if norm:
                actual_counts[norm] = actual_counts.get(norm, 0) + 1

        # Allow 'Choose Purchase Order' as an alias for 'Purchase Order'
        if actual_counts.get('choose purchase order', 0) > 0 and actual_counts.get('purchase order', 0) == 0:
            actual_counts['purchase order'] = actual_counts['choose purchase order']

        required_counts = {}
        display_names = {}
        for col in MANDATORY_EXCEL_COLUMNS:
            norm = _normalize_header(col)
            required_counts[norm] = required_counts.get(norm, 0) + 1
            display_names.setdefault(norm, col)

        missing_columns = []
        for norm, req_count in required_counts.items():
            found_count = actual_counts.get(norm, 0)
            if found_count == 0:
                missing_columns.append(display_names[norm])
            elif found_count < req_count:
                missing_columns.append(
                    f"{display_names[norm]} (expected {req_count} columns, found {found_count})"
                )

        if missing_columns:
            raise UserError(
                _(
                    'Invalid or missing mandatory Excel column header(s):\n'
                    '- %s\n\n'
                    'Please ensure the uploaded Excel file contains all required headers with exact spelling.'
                )
                % '\n- '.join(missing_columns)
            )

    def _validate_and_extract_rows(self):
        workbook = load_workbook(
            io.BytesIO(base64.b64decode(self.file)),
            data_only=True,
            read_only=True,
        )
        try:
            sheet = workbook.active
            try:
                header_row = next(
                    sheet.iter_rows(min_row=1, max_row=1, values_only=True)
                )
            except StopIteration:
                raise UserError(_('The Excel file is empty and has no header row.'))

            raw_headers = [
                str(value).strip() if value is not None and str(value).strip() else f'Col_{index}'
                for index, value in enumerate(header_row)
            ]

            # Variant attribute headers ('TYPE', 'VARIETY', 'DESIGN', 'SIZE', 'STONE COLOUR', 'METAL COLOUR')
            # must strictly be in UPPERCASE in the Excel header row.
            variant_attr_headers = {
                'type': 'TYPE',
                'variety': 'VARIETY',
                'design': 'DESIGN',
                'size': 'SIZE',
                'stone colour': 'STONE COLOUR',
                'metal colour': 'METAL COLOUR',
            }
            non_caps_variant_headers = []
            for h in raw_headers:
                norm_h = _normalize_header(h)
                if norm_h in variant_attr_headers:
                    expected_caps = variant_attr_headers[norm_h]
                    if re.sub(r'\s+', ' ', h.strip()) != expected_caps:
                        non_caps_variant_headers.append(
                            f"'{h}' (must be '{expected_caps}')"
                        )
            if non_caps_variant_headers:
                raise UserError(
                    _(
                        'Variant attribute column header(s) must be in UPPERCASE in the Excel file:\n'
                        '- %s'
                    )
                    % '\n- '.join(non_caps_variant_headers)
                )

            # 1. Validate that all mandatory Excel headers exist before importing
            self._validate_mandatory_headers(raw_headers)

            headers = []
            header_counts = {}
            for header in raw_headers:
                if header in header_counts:
                    header_counts[header] += 1
                    headers.append(f'{header}_{header_counts[header]}')
                else:
                    header_counts[header] = 0
                    headers.append(header)
            header_by_name = {
                _normalize_header(header): index for index, header in enumerate(headers)
            }

            purchase_order_index = next(
                (
                    header_by_name[header]
                    for header in ('choose purchase order', 'purchase order')
                    if header in header_by_name
                ),
                None,
            )
            company_index = header_by_name.get('company')
            product_index = header_by_name.get('product')
            branch_index = header_by_name.get('branch')
            src_loc_index = header_by_name.get('source location')
            dest_loc_index = header_by_name.get('destination location')
            label_name_index = header_by_name.get('label name')
            variant_attr_indices = [
                header_by_name[attr]
                for attr in ('type', 'variety', 'design', 'size', 'stone colour', 'metal colour')
                if attr in header_by_name
            ]

            companies = {}
            purchase_orders = {}
            branches = {}
            locations = {}
            indexed_rows = []

            def _cell_str(row_tuple, idx):
                if idx is None or idx >= len(row_tuple) or row_tuple[idx] is None:
                    return ''
                return str(row_tuple[idx]).strip()

            for row_number, row in enumerate(
                sheet.iter_rows(min_row=2, values_only=True),
                start=2,
            ):
                if not any(row):
                    continue
                if len(indexed_rows) >= MAX_IMPORT_ROWS:
                    raise UserError(
                        _(
                            'Maximum %s labels can be imported at a time. '
                            'Please split your Excel file into batches of at most %s rows.'
                        )
                        % (MAX_IMPORT_ROWS, MAX_IMPORT_ROWS)
                    )

                label_name = _cell_str(row, label_name_index)
                company_name = _cell_str(row, company_index)
                purchase_order_name = _cell_str(row, purchase_order_index)
                product_name = _cell_str(row, product_index)
                branch_name = _cell_str(row, branch_index)
                src_loc_name = _cell_str(row, src_loc_index)
                dest_loc_name = _cell_str(row, dest_loc_index)

                if not label_name:
                    raise UserError(
                        _("Mandatory field 'Label Name' is missing in Excel row %s.") % row_number
                    )
                if not product_name:
                    raise UserError(
                        _("Mandatory field 'Product' is missing in Excel row %s.") % row_number
                    )
                if not company_name:
                    raise UserError(
                        _("Mandatory field 'Company' is missing in Excel row %s.") % row_number
                    )
                if not purchase_order_name:
                    raise UserError(
                        _("Mandatory field 'Purchase Order' is missing in Excel row %s.") % row_number
                    )
                if not branch_name:
                    raise UserError(
                        _("Mandatory field 'Branch' is missing in Excel row %s.") % row_number
                    )
                if not src_loc_name:
                    raise UserError(
                        _("Mandatory field 'Source Location' is missing in Excel row %s.") % row_number
                    )
                if not dest_loc_name:
                    raise UserError(
                        _("Mandatory field 'Destination Location' is missing in Excel row %s.") % row_number
                    )

                # Validate Company exists
                company_key = company_name.casefold()
                if company_key not in companies:
                    companies[company_key] = self.env['res.company'].sudo().search(
                        [('name', '=ilike', company_name)],
                        limit=1,
                    )
                company = companies[company_key]
                if not company:
                    raise UserError(
                        _("Company '%s' does not exist (Excel row %s).")
                        % (company_name, row_number)
                    )

                # Validate Purchase Order exists for Company
                po_key = (company.id, purchase_order_name.casefold())
                if po_key not in purchase_orders:
                    purchase_orders[po_key] = self.env['purchase.order'].sudo().search(
                        [
                            ('name', '=ilike', purchase_order_name),
                            ('company_id', '=', company.id),
                        ],
                        limit=1,
                    )
                if not purchase_orders[po_key]:
                    raise UserError(
                        _("Purchase Order '%s' does not exist for company '%s' (Excel row %s).")
                        % (purchase_order_name, company.name, row_number)
                    )

                # Validate Branch exists
                branch_key = branch_name.casefold()
                if branch_key not in branches:
                    branches[branch_key] = self.env['res.branch'].sudo().search(
                        [('name', '=ilike', branch_name)],
                        limit=1,
                    )
                if not branches[branch_key]:
                    raise UserError(
                        _("Branch '%s' does not exist (Excel row %s).")
                        % (branch_name, row_number)
                    )

                # Validate Source Location exists
                src_key = (company.id, src_loc_name.casefold())
                if src_key not in locations:
                    locations[src_key] = self.env['stock.location'].sudo().search(
                        [
                            '|',
                            ('complete_name', '=ilike', src_loc_name),
                            ('name', '=ilike', src_loc_name),
                            ('company_id', 'in', [company.id, False]),
                        ],
                        limit=1,
                    )
                if not locations[src_key]:
                    raise UserError(
                        _("Source Location '%s' does not exist for company '%s' (Excel row %s).")
                        % (src_loc_name, company.name, row_number)
                    )

                # Validate Destination Location exists
                dest_key = (company.id, dest_loc_name.casefold())
                if dest_key not in locations:
                    locations[dest_key] = self.env['stock.location'].sudo().search(
                        [
                            '|',
                            ('complete_name', '=ilike', dest_loc_name),
                            ('name', '=ilike', dest_loc_name),
                            ('company_id', 'in', [company.id, False]),
                        ],
                        limit=1,
                    )
                if not locations[dest_key]:
                    raise UserError(
                        _("Destination Location '%s' does not exist for company '%s' (Excel row %s).")
                        % (dest_loc_name, company.name, row_number)
                    )

                row_values = list(row)
                for attr_idx in variant_attr_indices:
                    if attr_idx < len(row_values) and row_values[attr_idx] is not None:
                        val_str = str(row_values[attr_idx]).strip()
                        if val_str:
                            row_values[attr_idx] = val_str.upper()

                indexed_rows.append((row_number, row_values))

            if not indexed_rows:
                raise UserError(_('No data rows found in the uploaded Excel file.'))

            return raw_headers, indexed_rows
        finally:
            workbook.close()
