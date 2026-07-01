import json
import logging
from datetime import datetime, date

_logger = logging.getLogger(__name__)


def _safe_row(row):
    """Return a copy of row dict with all values converted to JSON-safe strings."""
    out = {}
    for k, v in (row or {}).items():
        if isinstance(v, (datetime, date)):
            out[str(k)] = v.isoformat()
        elif v is None:
            out[str(k)] = ''
        else:
            out[str(k)] = str(v)
    return out

# ── Field definitions exposed to the UI ──────────────────────────────────────

PO_FIELDS = [
    {'name': 'name',            'label': 'PO Number',           'type': 'char',     'required': True},
    {'name': 'partner_id',      'label': 'Vendor',              'type': 'many2one', 'model': 'res.partner'},
    {'name': 'date_order',      'label': 'Order Date',          'type': 'datetime'},
    {'name': 'currency_id',     'label': 'Currency',            'type': 'many2one', 'model': 'res.currency'},
    {'name': 'payment_term_id', 'label': 'Payment Terms',       'type': 'many2one', 'model': 'account.payment.term'},
    {'name': 'user_id',         'label': 'Purchase Rep',        'type': 'many2one', 'model': 'res.users'},
    {'name': 'partner_ref',     'label': 'Vendor Reference',    'type': 'char'},
    {'name': 'notes',           'label': 'Notes',               'type': 'text'},
    {'name': 'incoterm_id',     'label': 'Incoterm',            'type': 'many2one', 'model': 'account.incoterms'},
    {'name': 'company_id',      'label': 'Company',             'type': 'many2one', 'model': 'res.company'},
]

POL_FIELDS = [
    {'name': 'product_id',  'label': 'Product',         'type': 'many2one', 'model': 'product.product',  'required': True},
    {'name': 'name',        'label': 'Description',     'type': 'text'},
    {'name': 'product_qty', 'label': 'Quantity',        'type': 'float'},
    {'name': 'product_uom', 'label': 'Unit of Measure', 'type': 'many2one', 'model': 'uom.uom'},
    {'name': 'price_unit',  'label': 'Unit Price',      'type': 'float'},
    {'name': 'date_planned','label': 'Scheduled Date',  'type': 'datetime'},
    {'name': 'taxes_id',    'label': 'Taxes',           'type': 'many2many','model': 'account.tax'},
]

# ── product.label template field order ───────────────────────────────────────
# Defines the curated column order used when generating a download template.
# Each entry: (field_name, human_label, group_color_key, type_hint)
LABEL_TEMPLATE_FIELDS = [
    # ── Core identity ────────────────────────────────────────────────────────
    ('name',              'Label Reference (auto if blank)', 'core',     'char'),
    ('label_number',      'Label Number',                    'core',     'char'),
    ('label_name',        'Label Name',                      'core',     'char'),
    ('barcode',           'Barcode (auto-generated, read-only)', 'core', 'char'),
    ('active',            'Active',                          'core',     'boolean: True / False'),
    # ── Links ────────────────────────────────────────────────────────────────
    ('product_id',        'Product (Variant)',                'link',     'many2one → product.product (name)'),
    ('product_tmpl_id',   'Product Template',                'link',     'many2one → product.template (name)'),
    ('purchase_id',       'Purchase Order',                  'link',     'many2one → purchase.order (e.g. P00123)'),
    ('age_import',        'Age (Import)',                     'core',     'integer'),
    ('branch_id',         'Branch',                          'link',     'many2one → res.branch (name)'),
    ('branch_location_id','Destination Location',            'link',     'many2one → stock.location (name)'),
    ('source_location_id','Source Location',                 'link',     'many2one → stock.location (name)'),
    ('purity_id',         'Purity (Purchase)',               'link',     'many2one → gold.purity (name)'),
    ('sale_purity_id',    'Purity (Sale)',                   'link',     'many2one → gold.purity (name)'),
    ('job_work_id',       'Job Work',                        'link',     'many2one → jewellery.job.work (name)'),
    ('requisition_id',    'Requisition',                     'link',     'many2one → material.purchase.requisition (name)'),
    # ── Purchase jewellery details ────────────────────────────────────────────
    ('purchase_price_per_gram',      'Purchase Fine Rate / gram',    'purchase', 'float'),
    ('purchase_gross_weight',        'Purchase Gross Weight (g)',     'purchase', 'float'),
    ('purchase_stone_weight',        'Purchase Stone Weight (g)',     'purchase', 'float'),
    ('purchase_diamond_weight_gm',   'Purchase Diamond Weight (g)',   'purchase', 'float'),
    ('purchase_diamond_weight_ct',   'Purchase Diamond Weight (ct)',  'purchase', 'float'),
    ('purchase_stone_rate',          'Purchase Stone Amount',         'purchase', 'float'),
    ('purchase_diamond_rate',        'Purchase Diamond Amount',       'purchase', 'float'),
    ('purchase_making_charge_type',  'Purchase MC Type',              'purchase', 'selection: percent / amount / rate_per_gram'),
    ('purchase_making_charge_value', 'Purchase MC Value',             'purchase', 'float'),
    ('purchase_metal_rate',          'Purchase Metal Amount',         'purchase', 'float'),
    # ── Sale jewellery details ────────────────────────────────────────────────
    ('sale_price_per_gram',      'Sale Rate / gram',        'sale', 'float'),
    ('sale_gross_weight',        'Sale Gross Weight (g)',    'sale', 'float'),
    ('sale_stone_weight',        'Sale Stone Weight (g)',    'sale', 'float'),
    ('sale_diamond_weight_gm',   'Sale Diamond Weight (g)', 'sale', 'float'),
    ('sale_diamond_weight_ct',   'Sale Diamond Weight (ct)','sale', 'float'),
    ('sale_stone_rate',          'Sale Stone Amount',        'sale', 'float'),
    ('sale_diamond_rate',        'Sale Diamond Amount',      'sale', 'float'),
    ('sale_making_charge_type',  'Sale MC Type',             'sale', 'selection: percent / amount / rate_per_gram'),
    ('sale_making_charge_value', 'Sale MC Max',              'sale', 'float'),
    ('sale_making_charge_min',   'Sale MC Min',              'sale', 'float'),
    ('sale_metal_rate',          'Sale Metal Amount',         'sale', 'float'),
    # ── Charges ──────────────────────────────────────────────────────────────
    ('tag_weight',             'Tag Weight (g)',         'charge', 'float'),
    ('certification_charge',   'Certification Charge',   'charge', 'float'),
    ('transportation_charge',  'Transportation Charge',  'charge', 'float'),
    ('cargo_charge',           'Cargo Charge',           'charge', 'float'),
    ('others',                 'Others',                 'charge', 'float'),
]


class ImportEngine:
    """Stateful batch processor. Create one instance per batch call."""

    COMMIT_CHUNK = 500  # commit every N purchase orders

    def __init__(self, env, job):
        self.env = env
        self.job = job
        self.mapping = job.get_mapping()
        self.match_field = job.match_field
        self.model_name = getattr(job, 'model_name', None) or 'purchase.order'
        self.unique_field = getattr(job, 'unique_field_name', None) or 'name'
        self.has_lines = getattr(job, 'has_lines', False)
        self.line_model = getattr(job, 'line_model_name', '') or ''
        self.line_link_field = getattr(job, 'line_link_field', '') or ''
        self.group_by_field = getattr(job, 'group_by_field', '') or self.unique_field
        self.auto_create_m2o = getattr(job, 'auto_create_m2o', False)
        self.auto_confirm_receive = getattr(job, 'auto_confirm_receive', False)
        self.auto_create_bill = getattr(job, 'auto_create_bill', False)
        # If set, all rows are imported as lines directly onto this existing PO
        target_po = getattr(job, 'target_po_id', None)
        self.target_po_id = target_po.id if target_po else None
        self._related_cache = {}
        self._fields_info_cache = {}

        # Cross-batch vendor→PO deduplication: {str(partner_id): po_id}
        # Persisted on the job so it survives across batch calls.
        self._vendor_po_map = json.loads(getattr(job, 'vendor_po_map', None) or '{}')

        # Parse mapping into buckets based on prefix
        self.po_col = {}      # old po.field format  → {field: excel_col}
        self.pol_col = {}     # old pol.field format → {field: excel_col}
        self.header_col = {}  # new h:field format   → {field: excel_col}
        self.line_col = {}    # new l:field format   → {field: excel_col}
        self.plain_col = {}   # plain field name     → {field: excel_col}

        for excel_col, target in self.mapping.items():
            if not target:
                continue
            if target.startswith('h:'):
                self.header_col[target[2:]] = excel_col
            elif target.startswith('l:'):
                self.line_col[target[2:]] = excel_col
            elif '.' in target:
                prefix, _, field = target.partition('.')
                if prefix == 'po':
                    self.po_col[field] = excel_col
                elif prefix == 'pol':
                    self.pol_col[field] = excel_col
            else:
                self.plain_col[target] = excel_col

        # When purchase.order.line is set as line model but the user mapped all
        # columns as flat fields (no l: prefix), auto-promote product-level fields
        # into line_col so each row produces a real order line with data.
        # Fields that exist only on purchase.order.line (not purchase.order) are safe
        # to move; PO-level fields (partner_id, name, date_order, …) stay in plain_col.
        if (self.model_name == 'purchase.order'
                and self.line_model == 'purchase.order.line'
                and not self.line_col):
            _pol_only = {'product_id', 'product_qty', 'price_unit',
                         'product_uom', 'date_planned', 'taxes_id'}
            for _f, _c in self.plain_col.items():
                if _f in _pol_only:
                    self.line_col[_f] = _c

        # Legacy caches used by PO-specific path
        self._partner_cache = {}
        self._product_cache = {}
        self._uom_cache = {}
        self._currency_cache = {}
        self._payment_term_cache = {}
        self._user_cache = {}
        self._incoterm_cache = {}
        self._company_cache = {}
        self._tax_cache = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def process_rows(self, rows):
        # Direct-to-existing-PO mode: add all rows as lines to a chosen PO
        if self.target_po_id and self.line_model and self.line_link_field:
            return self._process_direct_lines(rows)
        # header+lines mode (h:/l: prefixes)
        if self.header_col and self.has_lines:
            return self._process_header_lines_rows(rows)
        # purchase.order with partner_id in plain mapping (user didn't enable Has Lines mode):
        # synthesise header_col from plain_col so vendor-grouping logic runs.
        # _process_header_lines_rows skips line creation when line_col/line_model are empty,
        # so it is safe to call here — it just creates correctly-vendored PO headers.
        if self.model_name == 'purchase.order' and 'partner_id' in self.plain_col:
            if not self.header_col:
                self.header_col = dict(self.plain_col)
            return self._process_header_lines_rows(rows)
        # legacy PO path (po./pol. prefixes)
        uses_old_prefix = any('.' in v for v in self.mapping.values() if v)
        if self.model_name == 'purchase.order' and uses_old_prefix:
            return self._process_po_rows(rows)
        # generic flat path
        return self._process_generic_rows(rows)

    def _process_direct_lines(self, rows):
        """
        Add every row as a line record directly onto self.target_po_id.
        No PO creation or grouping — all rows become lines on one existing PO.
        """
        result = {
            'created': 0, 'updated': 0, 'duplicates': 0,
            'skipped': 0, 'errors': 0, 'lines_created': 0,
            'error_rows': [], 'updated_rows': [], 'duplicate_rows': [], 'skipped_rows': [],
        }
        po = self.env['purchase.order'].browse(self.target_po_id)
        if not po.exists():
            result['errors'] += 1
            result['error_rows'].append({'row': 0, 'po_number': str(self.target_po_id),
                                         'data': {}, 'error': 'Target PO not found'})
            return result

        commit_counter = 0
        for abs_row_num, row in rows:
            try:
                line_vals = {self.line_link_field: po.id}
                for field, col in self.line_col.items():
                    raw = str(row.get(col, '') or '').strip()
                    if not raw:
                        continue
                    resolved = self._resolve_field_value(self.line_model, field, raw)
                    if resolved is not None:
                        line_vals[field] = resolved

                # Skip rows that have no useful data beyond the link field
                if len(line_vals) <= 1:
                    result['skipped'] += 1
                    result['skipped_rows'].append({
                        'row': abs_row_num, 'po_number': po.name,
                        'data': _safe_row(row), 'reason': 'No line field values mapped',
                    })
                    continue

                self.env[self.line_model].create(line_vals)
                result['lines_created'] += 1
                commit_counter += 1
                if commit_counter % self.COMMIT_CHUNK == 0:
                    self.env.cr.commit()
            except Exception as exc:
                _logger.exception('Direct-lines error row %s', abs_row_num)
                result['errors'] += 1
                result['error_rows'].append({
                    'row': abs_row_num, 'po_number': po.name,
                    'data': _safe_row(row), 'error': str(exc),
                })
                try:
                    self.env.cr.rollback()
                except Exception:
                    pass

        return result

    def _process_po_rows(self, rows):
        """
        Process an iterable of row dicts for purchase.order.
        Returns a result dict with created/updated/duplicate/skipped/error lists.
        """
        result = {
            'created': 0, 'updated': 0, 'duplicates': 0,
            'skipped': 0, 'errors': 0,
            'error_rows': [], 'updated_rows': [], 'duplicate_rows': [], 'skipped_rows': [],
        }

        # Group rows by PO key (name / partner_ref / partner+name)
        po_groups = {}  # po_key → [(row_number, row_dict), ...]
        for abs_row_num, row in rows:
            po_key = self._get_po_key(row)
            if not po_key:
                result['skipped'] += 1
                result['skipped_rows'].append({
                    'row': abs_row_num,
                    'data': _safe_row(row),
                    'reason': 'Missing PO identifier',
                })
                continue
            po_groups.setdefault(po_key, []).append((abs_row_num, row))

        processed_pos = 0
        for po_key, line_rows in po_groups.items():
            try:
                status = self._process_po_group(po_key, line_rows, result)
                if status == 'created':
                    result['created'] += 1
                elif status == 'updated':
                    result['updated'] += 1
                elif status == 'duplicate':
                    result['duplicates'] += 1
                    result['duplicate_rows'].append({
                        'row': line_rows[0][0],
                        'po_number': po_key,
                        'data': line_rows[0][1],
                        'reason': 'PO already processed in this batch',
                    })
            except Exception as exc:
                _logger.exception('Error processing PO %s', po_key)
                result['errors'] += len(line_rows)
                for row_num, row in line_rows:
                    result['error_rows'].append({
                        'row': row_num,
                        'po_number': po_key,
                        'data': _safe_row(row),
                        'error': str(exc),
                    })
                try:
                    self.env.cr.rollback()
                except Exception:
                    pass

            processed_pos += 1
            if processed_pos % self.COMMIT_CHUNK == 0:
                self.env.cr.commit()

        return result

    def _process_generic_rows(self, rows):
        """Generic row-by-row import for any Odoo model."""
        result = {
            'created': 0, 'updated': 0, 'duplicates': 0,
            'skipped': 0, 'errors': 0,
            'error_rows': [], 'updated_rows': [], 'duplicate_rows': [], 'skipped_rows': [],
        }
        commit_counter = 0
        for abs_row_num, row in rows:
            try:
                vals = self._build_generic_vals(row)
                if not vals:
                    result['skipped'] += 1
                    result['skipped_rows'].append({
                        'row': abs_row_num, 'data': _safe_row(row),
                        'reason': 'No mapped fields produced values',
                    })
                    continue
                unique_val = vals.get(self.unique_field)
                raw_variant = self._get_raw_col_value(row, 'product_id') if self.model_name == 'product.label' else None

                # Wrap each row in its own savepoint so a failed row only rolls
                # back itself — not all previously created but uncommitted rows.
                with self.env.cr.savepoint():
                    if unique_val:
                        existing = self.env[self.model_name].search(
                            [(self.unique_field, '=', unique_val)], limit=1
                        )
                    else:
                        existing = None
                    if existing:
                        existing.write(vals)
                        if self.model_name == 'product.label':
                            self._post_process_label(existing, raw_variant)
                        result['updated'] += 1
                        result['updated_rows'].append({
                            'row': abs_row_num,
                            'po_number': str(unique_val or ''),
                            'data': _safe_row(row),
                            'reason': 'Record updated',
                        })
                        rec = existing
                    else:
                        rec = self.env[self.model_name].create(vals)
                        if self.model_name == 'product.label':
                            self._post_process_label(rec, raw_variant)
                        result['created'] += 1

                    # Post-processing for purchase.order (confirm / receive / bill)
                    if self.model_name == 'purchase.order':
                        if self.auto_confirm_receive:
                            self._auto_confirm_and_receive(rec)
                        elif self.auto_create_bill:
                            self._auto_create_bill_standalone(rec)

                commit_counter += 1
                if commit_counter % self.COMMIT_CHUNK == 0:
                    self.env.cr.commit()
            except Exception as exc:
                _logger.exception('Generic import error row %s', abs_row_num)
                result['errors'] += 1
                result['error_rows'].append({
                    'row': abs_row_num, 'po_number': '',
                    'data': _safe_row(row), 'error': str(exc),
                })
                # Clear the related cache — any auto-created IDs from this row
                # were rolled back by the savepoint and must not be reused.
                self._related_cache.clear()
        return result

    def _build_generic_vals(self, row):
        fields_info = self._get_fields_info(self.model_name)
        vals = {}
        for excel_col, odoo_field in self.mapping.items():
            if not odoo_field:
                continue
            raw = row.get(excel_col)
            if raw is None or str(raw).strip() == '':
                continue
            raw_str = str(raw).strip()
            finfo = fields_info.get(odoo_field)
            if not finfo:
                vals[odoo_field] = raw_str
                continue
            # Skip computed non-stored fields — cannot write to them
            if finfo.get('compute') and not finfo.get('store', True):
                continue
            ftype = finfo['type']
            if ftype == 'many2one':
                rel = finfo.get('relation', '')
                resolved = self._resolve_related(rel, raw_str, auto_create=self.auto_create_m2o)
                if resolved:
                    vals[odoo_field] = resolved
            elif ftype == 'selection':
                vals[odoo_field] = self._resolve_selection(finfo.get('selection') or [], raw_str)
            elif ftype in ('float', 'monetary'):
                try:
                    vals[odoo_field] = float(raw_str.replace(',', '.'))
                except (ValueError, AttributeError):
                    pass
            elif ftype == 'integer':
                try:
                    vals[odoo_field] = int(float(raw_str))
                except (ValueError, AttributeError):
                    pass
            elif ftype in ('date', 'datetime'):
                parsed = self._parse_datetime(raw_str)
                if parsed:
                    vals[odoo_field] = parsed
            elif ftype == 'boolean':
                vals[odoo_field] = raw_str.lower() in ('true', '1', 'yes', 'y')
            else:
                vals[odoo_field] = raw_str

        # product.label: ensure active=True on every import row unless the
        # Excel explicitly mapped an active column with value False/0/no.
        if self.model_name == 'product.label' and 'active' not in vals:
            vals['active'] = True

        # product.label: branch_id is required by the sequence override (needs branch_code
        # to generate the label name). If not resolved from the Excel column, fall back
        # to the current user's branch, then to any branch with a branch_code.
        if self.model_name == 'product.label' and not vals.get('branch_id'):
            user_branch = self.env.user.branch_id
            if user_branch and user_branch.branch_code:
                vals['branch_id'] = user_branch.id
            else:
                fallback = self.env['res.branch'].search(
                    [('branch_code', '!=', False), ('branch_code', '!=', '')], limit=1
                )
                if fallback:
                    vals['branch_id'] = fallback.id

        return vals

    def _resolve_related(self, model, raw, auto_create=False):
        import re
        key = f'{model}:{raw}'
        if key in self._related_cache:
            return self._related_cache[key] or None

        raw_stripped = raw.strip()

        # ── Special: product.product ──────────────────────────────────────────
        # product.product.name is stored as JSON and is the TEMPLATE name — many
        # variants share the same name (e.g. 10 "Ring" records with different
        # attributes). Use name_search which resolves display_name including
        # attribute values like "Ring - Design Flower".
        if model == 'product.product':
            result = self.env['product.product'].name_search(raw_stripped, limit=1)
            if result:
                rec_id = result[0][0]
                self._related_cache[key] = rec_id
                return rec_id
            # Fall through to generic logic (auto_create path)
            rec = self.env['product.product'].browse()
        else:
            # 1. Exact case-insensitive match on name only.
            # display_name is computed/non-stored; searching it returns wrong results.
            rec = self.env[model].search(
                [('name', '=ilike', raw_stripped)], limit=1
            )

        # 2. Match by ref / internal reference
        if not rec and 'ref' in self.env[model]._fields:
            rec = self.env[model].search([('ref', '=', raw_stripped)], limit=1)

        # 2b. Model-specific secondary identifier fields
        if not rec and model == 'res.branch':
            # Try branch_code exact (short code like "HO", "NDJ", "KNR")
            rec = self.env[model].search([('branch_code', '=ilike', raw_stripped)], limit=1)
        if not rec and model == 'res.branch':
            # Try partial branch name match
            rec = self.env[model].search([('name', 'ilike', raw_stripped)], limit=1)
        if not rec and model == 'res.branch':
            # Try partial branch_code match
            rec = self.env[model].search([('branch_code', 'ilike', raw_stripped)], limit=1)
        if not rec and model in ('product.product', 'product.template'):
            # Try internal reference (default_code)
            rec = self.env[model].search([('default_code', '=ilike', raw_stripped)], limit=1)
        if not rec and 'code' in self.env[model]._fields:
            rec = self.env[model].search([('code', '=ilike', raw_stripped)], limit=1)

        # 2c. jewellery.job.work — sequence name may differ in format (JW0001 vs JW/2024/0001)
        # Try partial ilike so "JW0001" matches "JW/2024/0001" etc.
        if not rec and model == 'jewellery.job.work':
            rec = self.env[model].search([('name', 'ilike', raw_stripped)], limit=1)
        # Auto-create job work if still not found (always, regardless of auto_create_m2o).
        # Use the first available job worker as default so the required field is satisfied.
        if not rec and model == 'jewellery.job.work':
            try:
                default_worker = self.env['res.partner'].search(
                    [('is_job_worker', '=', True)], limit=1
                )
                jw_vals = {
                    'name': raw_stripped,
                    'branch_id': self.env.user.branch_id.id if self.env.user.branch_id else False,
                }
                if default_worker:
                    jw_vals['job_worker_id'] = default_worker.id
                with self.env.cr.savepoint():
                    rec = self.env['jewellery.job.work'].sudo().create(jw_vals)
                _logger.info('Auto-created jewellery.job.work: %s', raw_stripped)
            except Exception as exc:
                _logger.warning('Auto-create jewellery.job.work "%s" failed: %s', raw_stripped, exc)
                rec = self.env['jewellery.job.work'].browse()

        # 2d. product.product — additional fallbacks when name_search returns nothing.
        if not rec and model == 'product.product':
            # Try internal reference (default_code) ilike
            rec = self.env[model].search([('default_code', 'ilike', raw_stripped)], limit=1)
        if not rec and model == 'product.product':
            # Try name_search with ilike operator (partial match)
            result = self.env['product.product'].name_search(raw_stripped, operator='ilike', limit=1)
            if result:
                rec = self.env['product.product'].browse(result[0][0])
        if not rec and model == 'product.product':
            # Try matching by product template name — pick the first variant of that template
            tmpl = self.env['product.template'].search(
                [('name', 'ilike', raw_stripped)], limit=1
            )
            if tmpl:
                variant = self.env['product.product'].search(
                    [('product_tmpl_id', '=', tmpl.id)], limit=1
                )
                if variant:
                    rec = variant

        # 3. Partial (contains) match — only when NOT auto-creating to avoid silently
        # matching a different vendor whose name contains this one as a substring
        # (e.g. searching 'Jaffer' when only 'M/s Jaffer Thanveer' exists returns the
        # wrong partner, then every other vendor group collapses into that one PO).
        if not rec and not auto_create and model == 'res.partner':
            rec = self.env[model].search(
                ['|', ('name', 'ilike', raw_stripped),
                      ('display_name', 'ilike', raw_stripped)], limit=1
            )

        # 4. Normalised match — only when NOT auto-creating (same reason as step 3)
        if not rec and not auto_create and model == 'res.partner':
            def _norm(s):
                return re.sub(r'[\s\.,\-&\'\"]+', ' ', str(s)).strip().upper()
            norm_raw = _norm(raw_stripped)
            first_word = norm_raw.split()[0] if norm_raw else ''
            candidates = self.env[model].search(
                [('name', 'ilike', first_word)], limit=50
            ) if first_word else self.env[model].browse()
            for cand in candidates:
                if _norm(cand.name) == norm_raw:
                    rec = cand
                    break

        if not rec and auto_create:
            try:
                create_vals = {'name': raw_stripped}
                if model == 'res.partner':
                    create_vals.update({'supplier_rank': 1, 'company_type': 'company'})
                elif model == 'product.product':
                    create_vals = {'name': raw_stripped, 'type': 'consu',
                                   'purchase_ok': True, 'sale_ok': False}
                with self.env.cr.savepoint():
                    rec = self.env[model].create(create_vals)
                _logger.info('Auto-created %s: %s', model, raw_stripped)
            except Exception as exc:
                # Savepoint rolled back; cursor is clean for caller to continue
                _logger.warning('Auto-create %s "%s" failed: %s', model, raw_stripped, exc)
                rec = self.env[model].browse()

        # Only cache positive results. Never cache "not found" (False) — a later call
        # with auto_create=True must still be able to create the record.
        if rec:
            self._related_cache[key] = rec.id
        return rec.id if rec else None

    # ── Shared field resolver (used by generic + header-lines paths) ──────────

    def _get_fields_info(self, model_name):
        """Return cached fields_get for a model (includes type, relation, selection, compute, store)."""
        if model_name not in self._fields_info_cache:
            self._fields_info_cache[model_name] = self.env[model_name].fields_get(
                attributes=['type', 'relation', 'selection', 'compute', 'store']
            )
        return self._fields_info_cache[model_name]

    def _resolve_field_value(self, model_name, field_name, raw):
        """Resolve a raw string value to the correct Python type for the given field."""
        finfo = self._get_fields_info(model_name).get(field_name)
        if not finfo:
            return raw
        ftype = finfo['type']
        if ftype == 'many2one':
            return self._resolve_related(
                finfo.get('relation', ''), raw, auto_create=self.auto_create_m2o
            )
        if ftype == 'selection':
            return self._resolve_selection(finfo.get('selection') or [], raw)
        if ftype in ('float', 'monetary'):
            try:
                return float(str(raw).replace(',', '.'))
            except (ValueError, AttributeError):
                return None
        if ftype == 'integer':
            try:
                return int(float(str(raw)))
            except (ValueError, AttributeError):
                return None
        if ftype in ('date', 'datetime'):
            return self._parse_datetime(str(raw))
        if ftype == 'boolean':
            return str(raw).lower() in ('true', '1', 'yes', 'y')
        return str(raw)

    def _resolve_selection(self, selection, raw):
        """
        Map a raw string (key or label) to the correct selection key.
        Tries exact key → exact label → case-insensitive → normalised (strips
        spaces / dashes / em-dashes) → partial containment.
        """
        import re

        raw_s = str(raw).strip()
        if not selection or not raw_s:
            return raw_s

        def norm(s):
            return re.sub(r'[\s\-–—_]+', '', str(s)).lower()

        raw_lower = raw_s.lower()
        raw_norm  = norm(raw_s)

        for key, label in selection:
            # 1. Exact key match
            if str(key) == raw_s:
                return key
        for key, label in selection:
            # 2. Exact label match
            if str(label) == raw_s:
                return key
        for key, label in selection:
            # 3. Case-insensitive label
            if str(label).lower() == raw_lower:
                return key
        for key, label in selection:
            # 4. Normalised (strips spaces, dashes, em-dashes)
            if norm(label) == raw_norm:
                return key
        for key, label in selection:
            # 5. Partial containment
            lbl_lower = str(label).lower()
            if raw_lower in lbl_lower or lbl_lower in raw_lower:
                return key

        _logger.warning('No selection match for value %r. Available: %s',
                        raw_s, [l for _, l in selection])
        return raw_s  # let Odoo report the error with the original value

    # ── Header + Lines processor ──────────────────────────────────────────────

    def _process_header_lines_rows(self, rows):
        """
        Group rows by the group_by column, create/update one parent record
        per group, then create child (line) records for every row in the group.
        Supports Many2one group-by fields (e.g. partner_id as vendor).
        """
        result = {
            'created': 0, 'updated': 0, 'duplicates': 0,
            'skipped': 0, 'errors': 0, 'lines_created': 0,
            'error_rows': [], 'updated_rows': [], 'duplicate_rows': [], 'skipped_rows': [],
        }

        # Resolve the Excel column used for grouping.
        # For purchase.order: when partner_id is explicitly mapped as a header column
        # always group by vendor (one PO per vendor). This is the standard use case
        # where an Excel file has a "Vendor" / "Purchase Order" column and multiple
        # line rows per vendor. Grouping by name would require each vendor to have a
        # unique bill-reference value in the data, which often fails in practice.
        group_field = self.group_by_field or self.unique_field
        if self.model_name == 'purchase.order' and 'partner_id' in self.header_col:
            group_field = 'partner_id'

        group_col = self.header_col.get(group_field, '')
        if not group_col:
            group_col = next(iter(self.header_col.values()), '')

        # Check whether the group-by field is a Many2one (need ID-based search)
        parent_fields_info = self._get_fields_info(self.model_name)
        group_finfo = parent_fields_info.get(group_field, {})
        group_is_m2o = group_finfo.get('type') == 'many2one'

        # Group rows by raw value in the group column
        groups = {}   # raw_key → [(row_num, row_dict), ...]
        for row_num, row in rows:
            key = str(row.get(group_col, '') or '').strip()
            if not key:
                result['skipped'] += 1
                result['skipped_rows'].append({
                    'row': row_num, 'data': _safe_row(row),
                    'reason': f'Missing group-by value (column: "{group_col}")',
                })
                continue
            groups.setdefault(key, []).append((row_num, row))

        commit_counter = 0
        for group_key, group_rows in groups.items():
            try:
                # Build parent header vals from the first row.
                # partner_id is excluded here for purchase.order and resolved separately
                # below using strict (exact-only) matching. Generic _resolve_field_value
                # uses fuzzy matching which can silently return the wrong vendor (e.g.
                # 'Jaffer' fuzzy-matches a partner whose display_name contains 'Jaffer'
                # but belongs to a completely different vendor) — causing all line groups
                # to share one PO.
                header_vals = {}
                for field, col in self.header_col.items():
                    if self.model_name == 'purchase.order' and field == 'partner_id':
                        continue
                    raw = str(group_rows[0][1].get(col, '') or '').strip()
                    if not raw:
                        continue
                    resolved = self._resolve_field_value(self.model_name, field, raw)
                    if resolved is not None:
                        header_vals[field] = resolved

                # For purchase.order the vendor (partner_id) is mandatory.
                # Covers BOTH grouping modes:
                #   - M2O grouping (partner_id column): group_key is the raw vendor name
                #   - Char grouping (e.g. PO name / bill ref): look up the mapped vendor col
                if self.model_name == 'purchase.order':
                    if group_is_m2o:
                        vendor_raw = group_key
                    else:
                        vendor_col = self.header_col.get('partner_id', '')
                        vendor_raw = (
                            str(group_rows[0][1].get(vendor_col, '') or '').strip()
                            if vendor_col else ''
                        )

                    if not vendor_raw:
                        result['errors'] += len(group_rows)
                        for row_num, row in group_rows:
                            result['error_rows'].append({
                                'row': row_num, 'po_number': group_key,
                                'data': _safe_row(row),
                                'error': (
                                    'Vendor (partner_id) is required but the column is not '
                                    'mapped or is empty in this row.'
                                ),
                            })
                        continue

                    # Strict (exact-match) vendor lookup + auto-create.
                    # Using fuzzy matching here risks returning the wrong partner when
                    # multiple vendor names are similar, which would route all groups to
                    # one PO. _resolve_partner_strict only does exact =ilike + auto-create.
                    partner_id = self._resolve_partner_strict(vendor_raw)
                    if not partner_id:
                        result['errors'] += len(group_rows)
                        for row_num, row in group_rows:
                            result['error_rows'].append({
                                'row': row_num, 'po_number': group_key,
                                'data': _safe_row(row),
                                'error': f"Vendor '{vendor_raw}' could not be found or created.",
                            })
                        continue

                    header_vals['partner_id'] = partner_id
                    # Best-effort: apply GST treatment to vendor (Indian localisation)
                    self._apply_vendor_gst_treatment(partner_id, group_rows[0][1])

                # Find existing parent record.
                # For Many2one group-by (e.g. partner_id as vendor):
                #   1. Check the cross-batch vendor_po_map first (same job, different batches)
                #   2. Then check the DB by (name + partner_id) to prevent duplicates when
                #      the SAME file is imported a second time in a new job.
                if group_is_m2o:
                    partner_id_val = header_vals.get('partner_id')
                    cached_po_id = (
                        self._vendor_po_map.get(str(partner_id_val))
                        if partner_id_val else None
                    )
                    SudoModel = self.env[self.model_name].sudo()
                    if cached_po_id:
                        existing = SudoModel.browse(cached_po_id)
                        if not existing.exists():
                            existing = SudoModel.browse()
                    elif partner_id_val:
                        # Check DB: does a PO with the same bill-reference name AND vendor
                        # already exist from a previous import run?
                        po_name = header_vals.get('name')
                        if po_name:
                            existing = SudoModel.search([
                                ('name', '=', po_name),
                                ('partner_id', '=', partner_id_val),
                            ], limit=1)
                        else:
                            existing = SudoModel.browse()
                    else:
                        existing = SudoModel.browse()
                else:
                    existing = self.env[self.model_name].sudo().search(
                        [(group_field, '=', group_key)], limit=1
                    )

                if existing:
                    parent = existing
                    # Update header fields (date, notes, etc.) but skip partner_id to
                    # avoid accidentally reassigning the vendor on re-import
                    update_vals = {k: v for k, v in header_vals.items()
                                   if k != 'partner_id' and k != 'name'}
                    if update_vals:
                        existing.sudo().write(update_vals)
                    result['updated'] += 1
                    result['updated_rows'].append({
                        'row': group_rows[0][0], 'po_number': group_key,
                        'data': _safe_row(group_rows[0][1]), 'reason': 'Header updated',
                    })
                    # Register in map so further batches of THIS job also find it
                    if group_is_m2o and partner_id_val:
                        self._vendor_po_map[str(partner_id_val)] = existing.id
                        self.job.sudo().write(
                            {'vendor_po_map': json.dumps(self._vendor_po_map)}
                        )
                else:
                    parent = self.env[self.model_name].sudo().create(header_vals)
                    result['created'] += 1
                    # Register vendor→PO so subsequent batches add lines here instead of
                    # creating a duplicate PO for the same vendor.
                    if group_is_m2o and header_vals.get('partner_id'):
                        self._vendor_po_map[str(header_vals['partner_id'])] = parent.id
                        self.job.sudo().write(
                            {'vendor_po_map': json.dumps(self._vendor_po_map)}
                        )

                # Create or update line records
                if self.line_model and self.line_link_field:
                    for row_num, row in group_rows:
                        try:
                            line_vals = {self.line_link_field: parent.id}
                            for field, col in self.line_col.items():
                                raw = str(row.get(col, '') or '').strip()
                                if not raw:
                                    continue
                                resolved = self._resolve_field_value(
                                    self.line_model, field, raw
                                )
                                if resolved is not None:
                                    line_vals[field] = resolved

                            self.env[self.line_model].sudo().create(line_vals)
                            result['lines_created'] += 1
                        except Exception as exc:
                            result['errors'] += 1
                            result['error_rows'].append({
                                'row': row_num, 'po_number': group_key,
                                'data': _safe_row(row), 'error': str(exc),
                            })

                # Post-processing for purchase.order
                if self.model_name == 'purchase.order':
                    if self.auto_confirm_receive:
                        # Full flow: Confirm → Receive → (optionally) Create & Post Bill
                        self._auto_confirm_and_receive(parent)
                    elif self.auto_create_bill:
                        # Bill-only flow: Confirm PO (minimum required) → Create Bill → Approve
                        self._auto_create_bill_standalone(parent)

                commit_counter += 1
                if commit_counter % self.COMMIT_CHUNK == 0:
                    self.env.cr.commit()

            except Exception as exc:
                _logger.exception('Header+lines error for group %s', group_key)
                result['errors'] += len(group_rows)
                for row_num, row in group_rows:
                    result['error_rows'].append({
                        'row': row_num, 'po_number': group_key,
                        'data': _safe_row(row), 'error': str(exc),
                    })
                try:
                    self.env.cr.rollback()
                except Exception:
                    pass

        return result

    # ── PO group handling ─────────────────────────────────────────────────────

    def _process_po_group(self, po_key, line_rows, result):
        """Find or create PO, then create/update its lines. Returns status string."""
        existing_po = self._find_existing_po(po_key, line_rows[0][1])

        if existing_po:
            # Update header fields from first row
            header_vals = self._build_po_vals(line_rows[0][1])
            header_vals.pop('order_line', None)
            if header_vals:
                existing_po.write(header_vals)
            po = existing_po
            status = 'updated'
        else:
            po_vals = self._build_po_vals(line_rows[0][1])
            po_vals.pop('order_line', None)
            if not po_vals.get('partner_id'):
                # Show the raw vendor value from the row so the user knows what to fix
                vendor_col = self.po_col.get('partner_id', '')
                vendor_raw = str(line_rows[0][1].get(vendor_col, '') or '').strip()
                msg = (
                    f"Vendor '{vendor_raw}' not found in Odoo — check the name spelling "
                    "or enable 'Auto-Create Missing Records'."
                    if vendor_raw else
                    "Vendor (partner_id) is required but was not mapped or is empty."
                )
                result['skipped'] += 1
                result['skipped_rows'].append({
                    'row': line_rows[0][0],
                    'po_number': po_key,
                    'data': line_rows[0][1],
                    'reason': msg,
                })
                return 'skipped'
            po = self.env['purchase.order'].create(po_vals)
            status = 'created'

        # Process lines
        for row_num, row in line_rows:
            try:
                self._process_line(po, row_num, row, result)
            except Exception as exc:
                _logger.exception('Error on PO line row %s', row_num)
                result['errors'] += 1
                result['error_rows'].append({
                    'row': row_num,
                    'po_number': po_key,
                    'data': _safe_row(row),
                    'error': str(exc),
                })

        # Post-processing: confirm / receive / bill
        if self.auto_confirm_receive:
            self._auto_confirm_and_receive(po)
        elif self.auto_create_bill:
            self._auto_create_bill_standalone(po)

        return status

    def _process_line(self, po, row_num, row, result):
        product_id = self._resolve_product(row.get(self.pol_col.get('product_id', ''), ''))
        if not product_id:
            result['skipped'] += 1
            result['skipped_rows'].append({
                'row': row_num,
                'po_number': po.name,
                'data': row,
                'reason': 'Product not found or not mapped',
            })
            return

        line_vals = self._build_pol_vals(row, product_id, po)
        line_vals['order_id'] = po.id
        self.env['purchase.order.line'].sudo().create(line_vals)

    # ── Builders ──────────────────────────────────────────────────────────────

    def _build_po_vals(self, row):
        vals = {}
        for field, col in self.po_col.items():
            raw = str(row.get(col, '') or '').strip()
            if not raw:
                continue
            resolved = self._resolve_po_field(field, raw)
            if resolved is not None:
                vals[field] = resolved
        return vals

    def _build_pol_vals(self, row, product_id, po):
        vals = {'product_id': product_id}
        for field, col in self.pol_col.items():
            if field == 'product_id':
                continue
            raw = str(row.get(col, '') or '').strip()
            if not raw:
                continue
            resolved = self._resolve_pol_field(field, raw, product_id, po)
            if resolved is not None:
                vals[field] = resolved

        # Default description from product if not mapped
        if 'name' not in vals:
            product = self.env['product.product'].browse(product_id)
            vals['name'] = product.display_name

        # Default UoM from product if not mapped
        if 'product_uom' not in vals:
            product = self.env['product.product'].browse(product_id)
            vals['product_uom'] = product.uom_po_id.id or product.uom_id.id

        if 'product_qty' not in vals:
            vals['product_qty'] = 1.0

        if 'price_unit' not in vals:
            vals['price_unit'] = 0.0

        return vals

    # ── Field resolvers ───────────────────────────────────────────────────────

    def _resolve_po_field(self, field, raw):
        if field == 'partner_id':
            return self._resolve_partner(raw)
        if field == 'currency_id':
            return self._resolve_cached('res.currency', 'name', raw, self._currency_cache)
        if field == 'payment_term_id':
            return self._resolve_cached('account.payment.term', 'name', raw, self._payment_term_cache)
        if field == 'user_id':
            return self._resolve_cached('res.users', 'name', raw, self._user_cache)
        if field == 'incoterm_id':
            return self._resolve_cached('account.incoterms', 'code', raw, self._incoterm_cache)
        if field == 'company_id':
            return self._resolve_cached('res.company', 'name', raw, self._company_cache)
        if field in ('date_order',):
            return self._parse_datetime(raw)
        # Plain char/text
        return raw

    def _resolve_pol_field(self, field, raw, product_id, po):
        if field == 'product_uom':
            return self._resolve_cached('uom.uom', 'name', raw, self._uom_cache)
        if field == 'taxes_id':
            # Comma-separated tax names
            tax_ids = []
            for tax_name in raw.split(','):
                tax_name = tax_name.strip()
                if tax_name not in self._tax_cache:
                    rec = self.env['account.tax'].search(
                        [('name', '=', tax_name), ('type_tax_use', '=', 'purchase')], limit=1
                    )
                    self._tax_cache[tax_name] = rec.id if rec else False
                if self._tax_cache[tax_name]:
                    tax_ids.append(self._tax_cache[tax_name])
            return [(6, 0, tax_ids)] if tax_ids else None
        if field == 'date_planned':
            return self._parse_datetime(raw)
        if field in ('product_qty', 'price_unit'):
            try:
                return float(str(raw).replace(',', '.'))
            except (ValueError, TypeError):
                return None
        return raw

    def _resolve_partner(self, raw):
        # Delegate to the improved _resolve_related which does multi-step fuzzy matching
        result = self._resolve_related('res.partner', raw, auto_create=self.auto_create_m2o)
        self._partner_cache[raw] = result or False
        return result

    def _resolve_partner_strict(self, raw):
        """Exact-match vendor lookup with auto-create; no fuzzy/partial matching.

        Used for purchase.order vendor resolution so that distinct vendor names
        (e.g. 'Jaffer', 'Joy') are never accidentally matched to an existing partner
        whose name merely contains them as a substring, which would collapse all
        vendor groups into one PO.

        Uses a savepoint so a failed creation rolls back only that one operation
        and leaves the DB cursor in a clean state for the next group.
        """
        raw_stripped = str(raw).strip()
        if not raw_stripped:
            return None

        cache_key = f'res.partner:{raw_stripped}'
        if cache_key in self._related_cache:
            return self._related_cache[cache_key] or None

        # Exact case-insensitive match on name only.
        # display_name is a computed (non-stored) field; searching on it in Odoo 17
        # bypasses the value filter and returns all partners sorted by display_name,
        # so limit=1 always returns the partner that sorts first (e.g. ".ASHIDA KK"
        # because "." sorts before letters) — completely wrong behaviour.
        rec = self.env['res.partner'].search([('name', '=ilike', raw_stripped)], limit=1)
        if not rec:
            rec = self.env['res.partner'].search([('ref', '=', raw_stripped)], limit=1)

        if not rec:
            try:
                with self.env.cr.savepoint():
                    rec = self.env['res.partner'].create({
                        'name': raw_stripped,
                        'supplier_rank': 1,
                        'company_type': 'company',
                    })
                _logger.info('Auto-created vendor: %s', raw_stripped)
            except Exception as exc:
                # Savepoint already rolled back; cursor is clean for next group
                _logger.warning('Could not create vendor "%s": %s', raw_stripped, exc)
                rec = self.env['res.partner'].browse()

        if rec:
            self._related_cache[cache_key] = rec.id
            return rec.id
        return None

    def _get_raw_col_value(self, row, odoo_field):
        """Return the raw Excel cell value for the column mapped to odoo_field, or None."""
        for excel_col, mapped_field in self.mapping.items():
            if mapped_field == odoo_field:
                val = row.get(excel_col)
                return str(val).strip() if val is not None else None
        return None

    def _post_process_label(self, label, raw_variant=None):
        """Auto-fill product_id from product_tmpl_id and purchase_id from product if not set."""
        try:
            update = {}

            # ── Auto-set Product Variant from Product Template ────────────────
            if label.product_tmpl_id and not label.product_id:
                tmpl_id = label.product_tmpl_id.id
                # If we have a raw variant name, try name_search for precise match
                if raw_variant:
                    result = self.env['product.product'].name_search(
                        raw_variant,
                        args=[('product_tmpl_id', '=', tmpl_id)],
                        limit=1,
                    )
                    if result:
                        update['product_id'] = result[0][0]

                # Fallback: just pick the first variant of the template
                if 'product_id' not in update:
                    first = self.env['product.product'].search(
                        [('product_tmpl_id', '=', tmpl_id)], limit=1
                    )
                    if first:
                        update['product_id'] = first.id

            # Determine effective product_id after the above step
            effective_product_id = update.get('product_id') or (label.product_id.id if label.product_id else None)

            # ── Auto-set Purchase Order from Product ──────────────────────────
            if effective_product_id and not label.purchase_id:
                po = self.env['purchase.order'].search([
                    ('state', 'in', ('purchase', 'done')),
                    ('order_line.product_id', '=', effective_product_id),
                ], order='date_order desc', limit=1)
                if po:
                    update['purchase_id'] = po.id

            if update:
                label.write(update)

            # Auto-trigger stock transfer after label create/update.
            # Re-read from DB after write() to get the latest field values.
            label.invalidate_recordset()

            # Auto-fill locations if not set — required by action_stock_in.
            company = (
                label.branch_id.company_id
                if label.branch_id and label.branch_id.company_id
                else self.env.company
            )
            StockLoc = self.env['stock.location'].sudo()
            loc_update = {}
            if not label.branch_location_id and label.branch_id:
                dest_loc = StockLoc.search([
                    ('usage', '=', 'internal'),
                    ('branch_id', '=', label.branch_id.id),
                    '|', ('company_id', '=', company.id), ('company_id', '=', False),
                ], limit=1)
                if dest_loc:
                    loc_update['branch_location_id'] = dest_loc.id
            if not label.source_location_id:
                src_loc = StockLoc.search([
                    ('usage', '=', 'internal'),
                    '|', ('company_id', '=', company.id), ('company_id', '=', False),
                    ('complete_name', 'ilike', 'stock'),
                ], limit=1)
                if not src_loc:
                    src_loc = StockLoc.search([
                        ('usage', '=', 'internal'),
                        '|', ('company_id', '=', company.id), ('company_id', '=', False),
                    ], limit=1)
                if src_loc:
                    loc_update['source_location_id'] = src_loc.id
            if loc_update:
                label.write(loc_update)
                label.invalidate_recordset()

            _logger.info(
                'Label %s transfer check — product_id=%s branch_location_id=%s '
                'source_location_id=%s is_stocked_in=%s picking_id=%s',
                label.id, label.product_id.id if label.product_id else None,
                label.branch_location_id.id if label.branch_location_id else None,
                label.source_location_id.id if label.source_location_id else None,
                label.is_stocked_in, label.picking_id.id if label.picking_id else None,
            )
            if not label.is_stocked_in and not label.picking_id:
                try:
                    with self.env.cr.savepoint():
                        label.sudo().with_company(company).with_context(
                            skip_immediate=True,
                            skip_backorder=True,
                            skip_sms=True,
                            allowed_company_ids=company.ids,
                        ).action_stock_in()
                    _logger.info('action_stock_in completed for label %s', label.id)
                except Exception as transfer_exc:
                    _logger.warning(
                        'action_stock_in failed for label %s: %s', label.id, transfer_exc
                    )

        except Exception as exc:
            _logger.warning('post_process_label failed for label %s: %s', label.id, exc)

    def _auto_confirm_and_receive(self, po):
        """Confirm PO → receive all products → validate picking → optionally create & post bill."""
        _logger.info('_auto_confirm_and_receive called for PO %s (state=%s)', po.name, po.state)
        try:
            # Step 1: Confirm
            if po.state == 'draft':
                po.button_confirm()
            if po.state not in ('purchase', 'done'):
                return

            # Steps 2 & 3: Receive + Validate each pending picking
            pending = po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
            for picking in pending:
                for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                    move.quantity = move.product_uom_qty
                try:
                    picking.with_context(
                        skip_immediate=True,
                        skip_backorder=True,
                        skip_sms=True,
                    ).button_validate()
                except Exception:
                    picking._action_done()

            # Steps 4-6: Create vendor bill, swap Creditors → Opening Balance, post
            if self.auto_create_bill:
                self._auto_create_and_post_bill(po)

        except Exception as exc:
            _logger.warning('Auto-confirm/receive failed for PO %s: %s', po.name, exc)

    def _auto_create_and_post_bill(self, po):
        """Create a draft vendor bill, replace Creditors account with Opening Balance, then post it."""
        from odoo import fields as odoo_fields

        # Helper: search account.move via the stored purchase_line_id path.
        # purchase_id on account.move is NOT stored in DB (computed), so we
        # search through invoice_line_ids.purchase_line_id instead.
        po_line_ids = po.order_line.ids

        def _find_bills(state):
            if not po_line_ids:
                return self.env['account.move'].sudo().browse()
            return self.env['account.move'].sudo().search([
                ('move_type', '=', 'in_invoice'),
                ('state', '=', state),
                ('invoice_line_ids.purchase_line_id', 'in', po_line_ids),
            ])

        # Skip if a posted bill already exists for this PO
        try:
            if _find_bills('posted'):
                return
        except Exception as exc:
            _logger.warning('Bill check failed for PO %s: %s', po.name, exc)
            return

        # Create the bill if no draft exists yet
        try:
            if not _find_bills('draft'):
                po.sudo().with_context(
                    tracking_disable=True,
                    mail_notrack=True,
                ).action_create_invoice()
        except Exception as exc:
            _logger.exception('action_create_invoice failed for PO %s: %s', po.name, exc)
            return

        invoices = _find_bills('draft')
        if not invoices:
            _logger.warning('No draft bill found for PO %s after action_create_invoice', po.name)
            return

        # Find Opening Balance Account (search by name, fall back to code)
        ob_account = self.env['account.account'].search(
            [('name', 'ilike', 'Opening Balance')], limit=1
        )
        if not ob_account:
            ob_account = self.env['account.account'].search(
                ['|', ('code', '=', 'OB001'), ('code', '=', '339001')], limit=1
            )

        today = odoo_fields.Date.context_today(self.env['account.move'])

        for invoice in invoices:
            try:
                # Step 1: Ensure invoice_date is set — required before action_post()
                if not invoice.invoice_date:
                    invoice.sudo().write({'invoice_date': today})

                due_date = invoice.invoice_date or today

                # Step 2: Optionally swap the payable account to Opening Balance.
                # Use search() — not invoice.line_ids — because search() flushes
                # pending ORM writes before hitting DB, so freshly-created lines
                # are always visible (avoids the "empty line_ids on first import" bug).
                AML = self.env['account.move.line'].sudo()
                payable_lines = AML.search([
                    ('move_id', '=', invoice.id),
                    ('account_id.account_type', 'in',
                     ['liability_payable', 'asset_receivable']),
                ])
                _logger.info(
                    'Bill %s: found %d payable line(s) (ob_account=%s)',
                    invoice.name, len(payable_lines),
                    ob_account.name if ob_account else None,
                )
                if ob_account and payable_lines:
                    payable_lines.write({'account_id': ob_account.id})

                # Step 3: Final safety pass — enforce the date_maturity constraint
                # on ALL lines right before posting, using a fresh DB read (search
                # flushes pending writes, so this always sees the current state).
                all_lines = AML.search([('move_id', '=', invoice.id)])
                for line in all_lines:
                    is_payable = line.account_id.account_type in (
                        'liability_payable', 'asset_receivable'
                    )
                    if is_payable and not line.date_maturity:
                        line.write({'date_maturity': due_date})
                    elif not is_payable and line.date_maturity:
                        line.write({'date_maturity': False})

                # Step 4: Approve bill — equivalent to clicking "Approve Bill" in UI.
                # em_jewellery_management blocks action_post() on vendor bills unless
                # is_approved=True, regardless of user role.
                invoice.sudo().write({'is_approved': True})

                # Step 5: Post (confirm) the bill
                invoice.sudo().with_context(
                    tracking_disable=True,
                    mail_notrack=True,
                    mail_auto_subscribe_no_notify=True,
                ).action_post()
                _logger.info('Bill %s posted for PO %s', invoice.name, po.name)

            except Exception as exc:
                _logger.exception(
                    'action_post failed for bill %s (PO %s): %s',
                    invoice.name, po.name, exc
                )

    def _auto_create_bill_standalone(self, po):
        """Confirm PO (if still draft) → create vendor bill → approve (action_post).

        Used when auto_create_bill is enabled without auto_confirm_receive.
        Skips the receive/validate picking steps — bill is created directly from
        the confirmed PO.
        """
        _logger.info('_auto_create_bill_standalone called for PO %s (state=%s)', po.name, po.state)
        try:
            # Step 1: Confirm the PO if it is still a draft
            if po.state == 'draft':
                po.button_confirm()
            if po.state not in ('purchase', 'done'):
                _logger.warning(
                    'Cannot create bill for PO %s in state %s', po.name, po.state
                )
                return

            # Step 2: Create bill + approve
            self._auto_create_and_post_bill(po)

        except Exception as exc:
            _logger.warning('Auto-create-bill-standalone failed for PO %s: %s', po.name, exc)

    def _apply_vendor_gst_treatment(self, partner_id, row):
        """Set l10n_in_gst_treatment on the vendor partner from the row (Indian localisation).

        Looks for the value in:
          1. A header column mapped to 'l10n_in_gst_treatment'
          2. Any column whose name contains 'gst' and 'treatment' (case-insensitive)
        Does nothing if the field does not exist on res.partner or value can't be mapped.
        """
        # Find the raw GST treatment value from the row
        gst_col = self.header_col.get('l10n_in_gst_treatment', '')
        if not gst_col:
            # Auto-detect by column name hint
            for col in row.keys():
                nc = col.lower()
                if 'gst' in nc and 'treatment' in nc:
                    gst_col = col
                    break
        if not gst_col:
            return

        gst_raw = str(row.get(gst_col, '') or '').strip()
        if not gst_raw:
            return

        try:
            partner = self.env['res.partner'].browse(partner_id)
            if 'l10n_in_gst_treatment' not in partner._fields:
                return
            field_obj = partner._fields['l10n_in_gst_treatment']
            selection = field_obj.selection
            if callable(selection):
                selection = selection(partner)
            gst_key = self._resolve_selection(list(selection) if selection else [], gst_raw)
            if gst_key:
                partner.write({'l10n_in_gst_treatment': gst_key})
                _logger.debug('Set GST treatment %s on vendor %s', gst_key, partner.name)
        except Exception as exc:
            _logger.debug('Could not set GST treatment on partner %s: %s', partner_id, exc)

    def _resolve_product(self, raw):
        if not raw:
            return None
        raw = str(raw).strip()
        if raw not in self._product_cache:
            rec = self.env['product.product'].search(
                ['|', ('default_code', '=', raw), ('name', '=ilike', raw)], limit=1
            )
            self._product_cache[raw] = rec.id if rec else False
        return self._product_cache[raw] or None

    def _resolve_cached(self, model, field, raw, cache):
        if raw not in cache:
            rec = self.env[model].search([(field, '=ilike', raw)], limit=1)
            cache[raw] = rec.id if rec else False
        return cache[raw] or None

    @staticmethod
    def _parse_datetime(raw):
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(raw, fmt).strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                continue
        return None

    # ── Match logic ───────────────────────────────────────────────────────────

    def _get_po_key(self, row):
        if self.match_field == 'name':
            col = self.po_col.get('name', '')
            return str(row.get(col, '') or '').strip() or None
        if self.match_field == 'partner_ref':
            col = self.po_col.get('partner_ref', '')
            return str(row.get(col, '') or '').strip() or None
        if self.match_field == 'partner_name':
            name_col = self.po_col.get('name', '')
            partner_col = self.po_col.get('partner_id', '')
            name = str(row.get(name_col, '') or '').strip()
            partner = str(row.get(partner_col, '') or '').strip()
            return f'{partner}||{name}' if (name or partner) else None
        return None

    def _find_existing_po(self, po_key, row):
        if self.match_field == 'name':
            return self.env['purchase.order'].search([('name', '=', po_key)], limit=1)
        if self.match_field == 'partner_ref':
            return self.env['purchase.order'].search([('partner_ref', '=', po_key)], limit=1)
        if self.match_field == 'partner_name':
            partner_name, _, po_name = po_key.partition('||')
            partner_id = self._resolve_partner(partner_name)
            domain = [('name', '=', po_name)]
            if partner_id:
                domain.append(('partner_id', '=', partner_id))
            return self.env['purchase.order'].search(domain, limit=1)
        return None