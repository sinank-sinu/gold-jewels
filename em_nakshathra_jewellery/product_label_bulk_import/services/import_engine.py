import logging
from datetime import datetime, date

_logger = logging.getLogger(__name__)

MODEL = 'product.label'


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


# ── product.label template field order ───────────────────────────────────────
# Curated column order used when generating a download template.
# Each entry: (field_name, human_label, group_color_key, type_hint)
LABEL_TEMPLATE_FIELDS = [
    # ── Core identity ────────────────────────────────────────────────────────
    ('name',              'Label Reference (auto if blank)', 'core',     'char'),
    ('label_number',      'Label Number',                    'core',     'char'),
    ('label_name',        'Label Name',                      'core',     'char'),
    ('active',            'Active',                          'core',     'boolean: True / False'),
    # ── Links ────────────────────────────────────────────────────────────────
    ('product_id',        'Product (Variant)',                'link',     'many2one → product.product (name)'),
    ('product_tmpl_id',   'Product Template (product_tmpl_id)', 'link',  'many2one → product.template (name)'),
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
    """Stateful batch processor for product.label. One instance per batch call."""

    COMMIT_CHUNK = 500  # commit every N labels

    # Column name aliases: map alternative names to standard column names
    COLUMN_ALIASES = {
        'Bill Reference': 'Purchase Order',
    }

    def __init__(self, env, job):
        self.env = env
        self.job = job
        self.mapping = job.get_mapping()
        self.unique_field = getattr(job, 'unique_field_name', None) or 'name'
        self.auto_create_m2o = getattr(job, 'auto_create_m2o', False)
        self.auto_transfer = getattr(job, 'auto_transfer', False)
        self._related_cache = {}
        self._fields_info_cache = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def _normalize_row(self, row):
        """Normalize column names using COLUMN_ALIASES."""
        normalized = dict(row)
        for alias, standard_name in self.COLUMN_ALIASES.items():
            if alias in normalized and standard_name not in normalized:
                normalized[standard_name] = normalized.pop(alias)
        return normalized

    def process_rows(self, rows):
        """Process an iterable of (abs_row_num, row_dict) for product.label."""
        result = {
            'created': 0, 'updated': 0, 'duplicates': 0,
            'skipped': 0, 'errors': 0, 'transferred': 0,
            'error_rows': [], 'updated_rows': [], 'duplicate_rows': [], 'skipped_rows': [],
        }
        commit_counter = 0
        for abs_row_num, row in rows:
            row = self._normalize_row(row)
            try:
                vals = self._build_label_vals(row)
                if not vals:
                    result['skipped'] += 1
                    result['skipped_rows'].append({
                        'row': abs_row_num, 'data': _safe_row(row),
                        'reason': 'No mapped fields produced values',
                    })
                    continue

                raw_variant = self._get_raw_col_value(row, 'product_id')
                barcode_val = vals.get('barcode')

                # Append mode: every row creates a brand-new label — never match
                # or update an existing one. Each row runs in its own savepoint
                # so a failed row rolls back only itself.
                with self.env.cr.savepoint():
                    rec = self.env[MODEL].create(vals)
                    # product.label.create() overwrites barcode with an
                    # auto-generated EAN; restore the imported one.
                    if barcode_val and rec.barcode != barcode_val:
                        rec.barcode = barcode_val
                    result['created'] += 1

                    if self._post_process_label(rec, raw_variant):
                        result['transferred'] += 1

                commit_counter += 1
                if commit_counter % self.COMMIT_CHUNK == 0:
                    self.env.cr.commit()
            except Exception as exc:
                _logger.exception('Label import error row %s', abs_row_num)
                result['errors'] += 1
                result['error_rows'].append({
                    'row': abs_row_num, 'label_ref': '',
                    'data': _safe_row(row), 'error': str(exc),
                })
                # Auto-created IDs from this row were rolled back by the savepoint
                # and must not be reused.
                self._related_cache.clear()
        return result

    # ── Value builder ─────────────────────────────────────────────────────────

    def _build_label_vals(self, row):
        fields_info = self._get_fields_info(MODEL)
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

        # If no mapped column produced a value, this is an empty/blank row —
        # signal the caller to skip it (don't create a blank label).
        if not vals:
            return {}

        # Labels default to inactive on the model; imported labels should be
        # active unless the Excel explicitly mapped active=False/0/no.
        if 'active' not in vals:
            vals['active'] = True

        # branch_id is required by the sequence override (needs branch_code to
        # build the label name). Fall back to the user's branch, then any branch.
        if not vals.get('branch_id'):
            user_branch = getattr(self.env.user, 'branch_id', False)
            if user_branch and getattr(user_branch, 'branch_code', False):
                vals['branch_id'] = user_branch.id
            else:
                fallback = self.env['res.branch'].search(
                    [('branch_code', '!=', False), ('branch_code', '!=', '')], limit=1
                )
                if fallback:
                    vals['branch_id'] = fallback.id

        return vals

    # ── Field resolvers ─────────────────────────────────────────────────────

    def _get_fields_info(self, model_name):
        """Cached fields_get for a model (type, relation, selection, compute, store)."""
        if model_name not in self._fields_info_cache:
            self._fields_info_cache[model_name] = self.env[model_name].fields_get(
                attributes=['type', 'relation', 'selection', 'compute', 'store']
            )
        return self._fields_info_cache[model_name]

    def _resolve_selection(self, selection, raw):
        """Map a raw string (key or label) to the correct selection key."""
        import re

        raw_s = str(raw).strip()
        if not selection or not raw_s:
            return raw_s

        def norm(s):
            return re.sub(r'[\s\-–—_]+', '', str(s)).lower()

        raw_lower = raw_s.lower()
        raw_norm = norm(raw_s)

        for key, label in selection:
            if str(key) == raw_s:
                return key
        for key, label in selection:
            if str(label) == raw_s:
                return key
        for key, label in selection:
            if str(label).lower() == raw_lower:
                return key
        for key, label in selection:
            if norm(label) == raw_norm:
                return key
        for key, label in selection:
            lbl_lower = str(label).lower()
            if raw_lower in lbl_lower or lbl_lower in raw_lower:
                return key

        _logger.warning('No selection match for value %r. Available: %s',
                        raw_s, [l for _, l in selection])
        return raw_s  # let Odoo report the error with the original value

    def _resolve_related(self, model, raw, auto_create=False, company_id=None):
        key = f'{model}:{raw}'
        if key in self._related_cache:
            return self._related_cache[key] or None

        raw_stripped = str(raw).strip()

        # ── stock.location ────────────────────────────────────────────────────
        # Search by name first (computed complete_name field doesn't work in ORM).
        # Filter to real (non-view) locations only. Do NOT filter by usage for
        # source_location_id to allow any location type (internal, supplier, etc.)
        if model == 'stock.location':
            # Only filter by usage if searching destination_location (branch_location_id)
            # For source_location_id, allow any non-view location
            usage = []  # Start with no usage filter

            rec = None
            # If company_id provided, try to find location in same company first
            if company_id:
                company_filter = ['|', ('company_id', '=', company_id), ('company_id', '=', False)]
                # Try exact match on name first
                rec = self.env[model].search([('name', '=ilike', raw_stripped)] + company_filter, limit=1)
                if not rec:
                    rec = self.env[model].search([('name', 'ilike', raw_stripped)] + company_filter, limit=1)
                if not rec and '/' in raw_stripped:
                    parts = raw_stripped.split('/')
                    parent_name, child_name = parts[0].strip(), parts[-1].strip()
                    for loc in self.env[model].search([('name', 'ilike', child_name)] + company_filter, limit=10):
                        parent = loc.location_id
                        if parent and parent.name and parent_name.lower() in parent.name.lower():
                            rec = loc
                            break

            # Fallback: search without company filter if company_id didn't find anything
            if not rec:
                rec = self.env[model].search([('name', '=ilike', raw_stripped)], limit=1)
            if not rec:
                rec = self.env[model].search([('name', 'ilike', raw_stripped)], limit=1)
            if not rec and '/' in raw_stripped:
                parts = raw_stripped.split('/')
                parent_name, child_name = parts[0].strip(), parts[-1].strip()
                for loc in self.env[model].search([('name', 'ilike', child_name)], limit=10):
                    parent = loc.location_id
                    if parent and parent.name and parent_name.lower() in parent.name.lower():
                        rec = loc
                        break

            # Try complete_name matching as final fallback
            if not rec:
                all_locs = self.env[model].search([])
                for loc in all_locs:
                    if loc.complete_name and raw_stripped.lower() in loc.complete_name.lower():
                        rec = loc
                        break

            if rec:
                self._related_cache[key] = rec.id
                company_msg = f' in company {company_id}' if company_id else ''
                _logger.info('Resolved stock.location "%s" to %s (id=%s, complete_name=%s)%s',
                            raw_stripped, rec.name, rec.id, rec.complete_name, company_msg)
                return rec.id
            _logger.warning('Could not resolve stock.location "%s"%s', raw_stripped,
                           f' in company {company_id}' if company_id else '')
            return None

        # ── res.branch ────────────────────────────────────────────────────────
        # Use sudo() so multi-company record rules don't hide branches that
        # belong to another company, and AUTO-CREATE the branch when it does
        # not exist (with a generated branch_code). This runs regardless of the
        # "Auto-Create Missing Records" toggle — a label must have its branch.
        if model == 'res.branch':
            import re as _re
            Branch = self.env['res.branch'].sudo()

            def _unique_branch_code(seed):
                base = _re.sub(r'[^A-Za-z0-9]', '', seed).upper()[:8] or 'BR'
                code, n = base, 1
                while Branch.search([('branch_code', '=ilike', code)], limit=1):
                    n += 1
                    code = f'{base[:6]}{n}'
                return code

            rec = Branch.search([('name', '=ilike', raw_stripped)], limit=1)
            if not rec:
                rec = Branch.search([('branch_code', '=ilike', raw_stripped)], limit=1)
            if not rec:
                rec = Branch.search([('name', 'ilike', raw_stripped)], limit=1)
            if not rec:
                rec = Branch.search([('branch_code', 'ilike', raw_stripped)], limit=1)
            if not rec:
                try:
                    with self.env.cr.savepoint():
                        rec = Branch.create({
                            'name': raw_stripped,
                            'branch_code': _unique_branch_code(raw_stripped),
                            'company_id': self.env.company.id,
                        })
                    _logger.info('Auto-created res.branch %s', raw_stripped)
                except Exception as exc:
                    _logger.warning('Auto-create res.branch "%s" failed: %s', raw_stripped, exc)
                    rec = Branch.browse()

            # The product.label name sequence is "{branch_code}/{seq}" and raises
            # "Branch code is missing!" when the branch has no code. Backfill one
            # so existing code-less branches (e.g. imported dupes) don't error.
            if rec and not rec.branch_code:
                try:
                    with self.env.cr.savepoint():
                        rec.write({'branch_code': _unique_branch_code(rec.name or raw_stripped)})
                    _logger.info('Backfilled branch_code for res.branch %s', rec.name)
                except Exception as exc:
                    _logger.warning('Could not backfill branch_code for branch %s: %s', rec.id, exc)

            if rec:
                self._related_cache[key] = rec.id
                return rec.id
            return None

        # ── product.product ───────────────────────────────────────────────────
        # product.product.name is the TEMPLATE name; many variants share it.
        # NOTE: Jewellery format "Template,(v1,v2,...)" is NOT resolved to a specific
        # variant — specific variant matching is disabled. The system resolves to the
        # template, and post-processing picks the first variant. Users can manually
        # set variants if needed. Proper variant matching would require knowing the
        # exact attribute structure for each template.
        if model == 'product.product':
            # Extract just the template name (ignore the jewellery format if present)
            if ',(' in raw_stripped and raw_stripped.rstrip().endswith(')'):
                tmpl_name = raw_stripped.partition(',(')[0].strip()
            else:
                tmpl_name = raw_stripped

            # IMPORTANT: Search for the TEMPLATE first (exact match), then get its first variant.
            # This avoids matching unrelated variants from other templates (e.g., "Ring" matching
            # a "Babyring" variant). Only if the template search fails, fall back to variant search.
            tmpl = self.env['product.template'].search([('name', '=ilike', tmpl_name)], limit=1)
            if not tmpl:
                tmpl = self.env['product.template'].search([('name', 'ilike', tmpl_name)], limit=1)

            if tmpl:
                # Get the first variant of the correct template
                rec = tmpl.product_variant_ids[:1]
            else:
                # Fallback: search variants directly only if template not found
                res = self.env['product.product'].name_search(tmpl_name, limit=1)
                rec = self.env['product.product'].browse(res[0][0]) if res else self.env['product.product'].browse()
        else:
            rec = self.env[model].search([('name', '=ilike', raw_stripped)], limit=1)

        # Match by ref / internal reference
        if not rec and 'ref' in self.env[model]._fields:
            rec = self.env[model].search([('ref', '=', raw_stripped)], limit=1)

        if not rec and model in ('product.product', 'product.template'):
            rec = self.env[model].search([('default_code', '=ilike', raw_stripped)], limit=1)
        if not rec and 'code' in self.env[model]._fields:
            rec = self.env[model].search([('code', '=ilike', raw_stripped)], limit=1)

        # jewellery.job.work — sequence name may differ in format
        if not rec and model == 'jewellery.job.work':
            rec = self.env[model].search([('name', 'ilike', raw_stripped)], limit=1)
        if not rec and model == 'jewellery.job.work':
            try:
                default_worker = self.env['res.partner'].search(
                    [('is_job_worker', '=', True)], limit=1
                )
                jw_vals = {
                    'name': raw_stripped,
                    'branch_id': self.env.user.branch_id.id if getattr(self.env.user, 'branch_id', False) else False,
                }
                if default_worker:
                    jw_vals['job_worker_id'] = default_worker.id
                with self.env.cr.savepoint():
                    rec = self.env['jewellery.job.work'].sudo().create(jw_vals)
                _logger.info('Auto-created jewellery.job.work: %s', raw_stripped)
            except Exception as exc:
                _logger.warning('Auto-create jewellery.job.work "%s" failed: %s', raw_stripped, exc)
                rec = self.env['jewellery.job.work'].browse()

        # ── purchase.order ────────────────────────────────────────────────────
        # Search purchase orders by name, origin, and number fields. Only return
        # purchase orders in 'purchase' state (as per product.label domain).
        if model == 'purchase.order':
            rec = self.env[model].search([('name', '=ilike', raw_stripped), ('state', '=', 'purchase')], limit=1)
            if not rec:
                rec = self.env[model].search([('name', 'ilike', raw_stripped), ('state', '=', 'purchase')], limit=1)
            if not rec and 'origin' in self.env[model]._fields:
                rec = self.env[model].search([('origin', '=ilike', raw_stripped), ('state', '=', 'purchase')], limit=1)
            if not rec and 'origin' in self.env[model]._fields:
                rec = self.env[model].search([('origin', 'ilike', raw_stripped), ('state', '=', 'purchase')], limit=1)
            if not rec and 'number' in self.env[model]._fields:
                rec = self.env[model].search([('number', '=ilike', raw_stripped), ('state', '=', 'purchase')], limit=1)
            if not rec and 'number' in self.env[model]._fields:
                rec = self.env[model].search([('number', 'ilike', raw_stripped), ('state', '=', 'purchase')], limit=1)
            # Fallback: search without state filter (user may have other states)
            if not rec:
                rec = self.env[model].search([('name', '=ilike', raw_stripped)], limit=1)
            if not rec:
                rec = self.env[model].search([('name', 'ilike', raw_stripped)], limit=1)
            if not rec and 'origin' in self.env[model]._fields:
                rec = self.env[model].search([('origin', '=ilike', raw_stripped)], limit=1)
            if not rec:
                _logger.warning('Could not resolve purchase.order "%s". Note: domain requires state=purchase', raw_stripped)

        # product.product — additional fallbacks
        if not rec and model == 'product.product':
            rec = self.env[model].search([('default_code', 'ilike', raw_stripped)], limit=1)
        if not rec and model == 'product.product':
            res = self.env['product.product'].name_search(raw_stripped, operator='ilike', limit=1)
            if res:
                rec = self.env['product.product'].browse(res[0][0])
        if not rec and model == 'product.product':
            tmpl = self.env['product.template'].search([('name', 'ilike', raw_stripped)], limit=1)
            if tmpl:
                variant = self.env['product.product'].search(
                    [('product_tmpl_id', '=', tmpl.id)], limit=1
                )
                if variant:
                    rec = variant

        # product.template — partial name fallback
        if not rec and model == 'product.template':
            rec = self.env[model].search([('name', 'ilike', raw_stripped)], limit=1)

        if not rec and auto_create:
            # Don't auto-create purchase.order — they must exist with valid vendor/partner
            if model != 'purchase.order':
                try:
                    create_vals = {'name': raw_stripped}
                    if model == 'product.product':
                        create_vals = {'name': raw_stripped, 'type': 'consu', 'sale_ok': True}
                    with self.env.cr.savepoint():
                        rec = self.env[model].create(create_vals)
                    _logger.info('Auto-created %s: %s', model, raw_stripped)
                except Exception as exc:
                    _logger.warning('Auto-create %s "%s" failed: %s', model, raw_stripped, exc)
                    rec = self.env[model].browse()
            else:
                _logger.warning('purchase.order "%s" not found and auto-create is disabled. Please create PO manually.', raw_stripped)

        # Only cache positive results.
        if rec:
            self._related_cache[key] = rec.id
        return rec.id if rec else None

    def _resolve_jewellery_variant(self, raw):
        """Resolve a variant from "Template,(v1,v2,v3,v4,v5,v6)" jewellery format.

        For now, just resolve to the template. Variant matching is complex and requires
        knowing the exact attribute structure. The importer will use product_tmpl_id and
        the user can manually set product_id if needed, or the post-processor will pick
        the first variant.
        """
        tmpl_name, _, _ = raw.partition(',(')
        tmpl_name = tmpl_name.strip()

        template = self.env['product.template'].search([('name', '=ilike', tmpl_name)], limit=1)
        if not template:
            template = self.env['product.template'].search([('name', 'ilike', tmpl_name)], limit=1)
        if not template:
            return None

        # Return first variant as best guess (will be refined in post_process_label)
        variant = template.product_variant_ids[:1]
        return variant.id if variant else None

    @staticmethod
    def _parse_datetime(raw):
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(raw, fmt).strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                continue
        return None

    def _get_raw_col_value(self, row, odoo_field):
        """Return the raw Excel cell value for the column mapped to odoo_field, or None."""
        for excel_col, mapped_field in self.mapping.items():
            if mapped_field == odoo_field:
                val = row.get(excel_col)
                return str(val).strip() if val is not None else None
        return None

    # ── Post-processing (autofill + optional transfer) ────────────────────────

    def _post_process_label(self, label, raw_variant=None):
        """Auto-fill variant/template/PO + locations, then optionally stock-in.

        Returns True if the label was successfully transferred (stocked in).
        """
        transferred = False
        try:
            update = {}

            # ── Product Variant ← Product Template ─────────────────────────────
            if label.product_tmpl_id and not label.product_id:
                tmpl_id = label.product_tmpl_id.id
                if raw_variant:
                    res = self.env['product.product'].name_search(
                        raw_variant,
                        args=[('product_tmpl_id', '=', tmpl_id)],
                        limit=1,
                    )
                    if res:
                        update['product_id'] = res[0][0]
                if 'product_id' not in update:
                    first = self.env['product.product'].search(
                        [('product_tmpl_id', '=', tmpl_id)], limit=1
                    )
                    if first:
                        update['product_id'] = first.id

            # ── Product Template ← Product Variant ─────────────────────────────
            if label.product_id and not label.product_tmpl_id:
                tmpl = label.product_id.product_tmpl_id
                if tmpl:
                    update['product_tmpl_id'] = tmpl.id

            # NOTE: purchase_id is intentionally NOT guessed from the product.
            # It is only set when the file explicitly maps a Purchase Order
            # column that resolves to a real PO — guessing produced wrong links.

            # Final safety: if product_id exists but product_tmpl_id is still missing,
            # fill it in now (catches any edge cases where the earlier backfill didn't run).
            if label.product_id and not label.product_tmpl_id:
                tmpl = label.product_id.product_tmpl_id
                if tmpl and not update.get('product_tmpl_id'):
                    update['product_tmpl_id'] = tmpl.id

            if update:
                label.write(update)

            label.invalidate_recordset()

            if not self.auto_transfer:
                return False

            # ── Auto-fill locations required by action_stock_in ────────────────
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
            if loc_update:
                label.write(loc_update)
                label.invalidate_recordset()

            if not label.is_stocked_in and not label.picking_id:
                try:
                    with self.env.cr.savepoint():
                        label.sudo().with_company(company).with_context(
                            skip_immediate=True,
                            skip_backorder=True,
                            skip_sms=True,
                            allowed_company_ids=company.ids,
                        ).action_stock_in()
                    transferred = True
                    _logger.info('action_stock_in completed for label %s', label.id)
                except Exception as transfer_exc:
                    _logger.warning('action_stock_in failed for label %s: %s', label.id, transfer_exc)

        except Exception as exc:
            _logger.warning('post_process_label failed for label %s: %s', label.id, exc)
        return transferred