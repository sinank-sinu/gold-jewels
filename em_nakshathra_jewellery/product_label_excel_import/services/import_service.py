# -*- coding: utf-8 -*-
import base64
import io
import re
import logging
import openpyxl

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _normalize_header(header):
    if not header:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(header).lower())


def _clean_str(val):
    if val is None or val is False:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    val_str = str(val).strip()
    if val_str.endswith(".0") and val_str[:-2].isdigit():
        return val_str[:-2]
    return val_str


class ProductLabelImportService:
    ALIAS_MAP = {
        'label_name': [
            'labelno', 'labelnumber', 'labelname', 'labelref', 'labelreference',
            'label', 'name', 'itemno', 'referenceno', 'tagno'
        ],
        'barcode2': [
            'oldbarcodeno', 'oldbarcode', 'secondbarcode', 'secondbarcodeno',
            'barcode2', 'barcode_2', 'second_barcode', 'oldbarcodenumber'
        ],
        'barcode': [
            'barcodeno', 'barcode', 'itembarcode', 'barcodenumber', 'newbarcode'
        ],
        'supplier_name': [
            'suppliername', 'supplier', 'vendorname', 'vendor', 'partnername',
            'partner', 'supplier_name', 'vendor_name'
        ],
        'supplier_code': [
            'suppcode', 'suppliercode', 'vendorcode', 'vendorref', 'supp_code',
            'vendor_code', 'suppcode'
        ],
        'branch': [
            'branchname', 'branch', 'branch_id', 'shop'
        ],
        'company': [
            'companyname', 'company', 'company_id'
        ],
    }

    def __init__(self, env):
        self.env = env

    def build_header_col_map(self, header_row):
        col_map = {}
        for idx, cell_val in enumerate(header_row):
            if not cell_val:
                continue
            norm = _normalize_header(cell_val)
            for field_key, aliases in self.ALIAS_MAP.items():
                if norm == field_key or norm in aliases:
                    if field_key not in col_map:
                        col_map[field_key] = idx
        return col_map

    def find_or_create_partner(self, supplier_name, supplier_code, create_partner, partner_cache):
        supplier_name = _clean_str(supplier_name)
        supplier_code = _clean_str(supplier_code)

        if not supplier_name and not supplier_code:
            return False

        cache_key = (supplier_name.lower(), supplier_code.lower())
        if cache_key in partner_cache:
            return partner_cache[cache_key]

        partner = False
        Partner = self.env['res.partner'].sudo()

        if supplier_code:
            partner = Partner.search([('ref', '=', supplier_code)], limit=1)

        if not partner and supplier_name:
            partner = Partner.search([('name', '=ilike', supplier_name)], limit=1)

        if not partner and supplier_code:
            partner = Partner.search([('name', '=ilike', supplier_code)], limit=1)

        if not partner and create_partner:
            vals = {
                'name': supplier_name or supplier_code,
                'supplier_rank': 1,
                'is_company': True,
            }
            if supplier_code:
                vals['ref'] = supplier_code
            partner = Partner.create(vals)
            _logger.info("Created new vendor partner: %s (ref: %s)", partner.name, partner.ref)

        partner_cache[cache_key] = partner
        return partner

    def resolve_company(self, company_val, company_cache):
        company_str = _clean_str(company_val)
        if not company_str:
            return False

        cache_key = company_str.lower()
        if cache_key in company_cache:
            return company_cache[cache_key]

        Company = self.env['res.company'].sudo()
        comp = False
        norm_val = _normalize_header(company_str)

        # 1. Direct ID if numeric
        if company_str.isdigit():
            c = Company.browse(int(company_str))
            if c.exists():
                comp = c

        # 2. Exact or ilike name
        if not comp:
            comp = Company.search([('name', '=ilike', company_str)], limit=1)

        # 3. Normalized name comparison
        if not comp:
            for c in Company.search([]):
                if _normalize_header(c.name) == norm_val:
                    comp = c
                    break

        # 4. Partial keyword matching (e.g. 'hyd', 'silver', 'llp')
        if not comp:
            for c in Company.search([]):
                c_norm = _normalize_header(c.name)
                if ('hyd' in norm_val and 'hyd' in c_norm) or ('silver' in norm_val and 'silver' in c_norm):
                    comp = c
                    break

        company_cache[cache_key] = comp
        return comp

    def resolve_branch(self, branch_val, company_record, branch_cache):
        branch_str = _clean_str(branch_val)
        if not branch_str:
            return False

        comp_id = company_record.id if company_record else False
        cache_key = (branch_str.lower(), comp_id)
        if cache_key in branch_cache:
            return branch_cache[cache_key]

        Branch = self.env['res.branch'].sudo()
        br = False
        norm_val = _normalize_header(branch_str)
        base_domain = [('company_id', '=', comp_id)] if comp_id else []

        # 1. Direct ID if numeric
        if branch_str.isdigit():
            b = Branch.browse(int(branch_str))
            if b.exists() and (not comp_id or b.company_id.id == comp_id):
                br = b

        # 2. Match by exact branch_code or name within company
        if not br:
            domain = base_domain + ['|', ('branch_code', '=ilike', branch_str), ('name', '=ilike', branch_str)]
            br = Branch.search(domain, limit=1)

        # 3. Normalized name / code comparison within company
        if not br:
            for b in Branch.search(base_domain):
                if _normalize_header(b.name) == norm_val or (b.branch_code and _normalize_header(b.branch_code) == norm_val):
                    br = b
                    break

        # 4. Fuzzy comparison (e.g. 'kasaragod' vs 'kasargod') within company
        if not br:
            for b in Branch.search(base_domain):
                b_norm = _normalize_header(b.name)
                if (b_norm in norm_val or norm_val in b_norm) or ('kasar' in norm_val and 'kasar' in b_norm):
                    br = b
                    break

        # 5. Search across all branches without company restriction if not found yet
        if not br and comp_id:
            for b in Branch.search([]):
                b_norm = _normalize_header(b.name)
                if b_norm == norm_val or (b_norm in norm_val or norm_val in b_norm) or ('kasar' in norm_val and 'kasar' in b_norm):
                    br = b
                    break

        branch_cache[cache_key] = br
        return br

    def find_label(self, label_name, barcode, barcode2, branch=False, company=False, match_by='auto'):
        """Search product.label according to Company, Branch, and identifier (name/barcode/barcode2)."""
        Label = self.env['product.label'].sudo().with_context(active_test=False)

        criteria = []
        if match_by in ('auto', 'name') and label_name:
            criteria.append(('name', label_name))
        if match_by in ('auto', 'barcode') and barcode:
            criteria.append(('barcode', barcode))
        if match_by in ('auto', 'barcode2') and barcode2:
            criteria.append(('barcode2', barcode2))

        # 1. High Priority: Search with both Company and Branch
        if branch and company:
            for field, val in criteria:
                lbl = Label.search([
                    (field, '=', val),
                    ('branch_id', '=', branch.id),
                    ('company_id', '=', company.id)
                ], limit=1)
                if lbl:
                    return lbl

        # 2. Search with Branch only
        if branch:
            for field, val in criteria:
                lbl = Label.search([
                    (field, '=', val),
                    ('branch_id', '=', branch.id)
                ], limit=1)
                if lbl:
                    return lbl

        # 3. Search with Company only
        if company:
            for field, val in criteria:
                lbl = Label.search([
                    (field, '=', val),
                    ('company_id', '=', company.id)
                ], limit=1)
                if lbl:
                    return lbl

        # 4. Fallback: Search by identifier alone
        for field, val in criteria:
            lbl = Label.search([(field, '=', val)], limit=1)
            if lbl:
                return lbl

        # 5. Secondary check for alternative name fields
        if match_by in ('auto', 'name') and label_name:
            domain_alt = ['|', ('label_number', '=', label_name), ('label_name', '=', label_name)]
            if branch:
                lbl = Label.search(domain_alt + [('branch_id', '=', branch.id)], limit=1)
                if lbl:
                    return lbl
            lbl = Label.search(domain_alt, limit=1)
            if lbl:
                return lbl

        return False

    def process_import(self, file_base64_or_bytes, match_by='auto', create_partner=True):
        """Main method to parse Excel, search according to company & branch, and update Product Labels."""
        _logger.info("ProductLabelImportService: Starting import...")

        if isinstance(file_base64_or_bytes, str):
            file_bytes = base64.b64decode(file_base64_or_bytes)
        elif isinstance(file_base64_or_bytes, bytes):
            try:
                file_bytes = base64.b64decode(file_base64_or_bytes)
            except Exception:
                file_bytes = file_base64_or_bytes
        else:
            raise UserError("Invalid file content provided for import.")

        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        sheet = wb.active
        rows_iter = sheet.iter_rows(values_only=True)

        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise UserError("The uploaded Excel file is empty.")

        col_map = self.build_header_col_map(header_row)
        _logger.info("ProductLabelImportService: mapped headers: %s", col_map)

        if 'label_name' not in col_map and 'barcode' not in col_map and 'barcode2' not in col_map:
            raise UserError(
                "Could not identify Label Number or Barcode columns in Excel.\n"
                "Please make sure your header includes 'Label No' or 'Barcode' or 'Old BarcodeNo'."
            )

        def get_val(r, key):
            if key in col_map and col_map[key] < len(r):
                return r[col_map[key]]
            return None

        partner_cache = {}
        company_cache = {}
        branch_cache = {}

        stats = {
            'total': 0,
            'updated': 0,
            'unchanged': 0,
            'not_found': 0,
            'vendors_count': 0,
        }
        unmatched_rows = []

        for row_idx, row in enumerate(rows_iter, start=2):
            if not any(row):
                continue

            stats['total'] += 1

            label_name = _clean_str(get_val(row, 'label_name'))
            barcode2 = _clean_str(get_val(row, 'barcode2'))
            barcode = _clean_str(get_val(row, 'barcode'))
            supplier_name = _clean_str(get_val(row, 'supplier_name'))
            supplier_code = _clean_str(get_val(row, 'supplier_code'))
            branch_str = _clean_str(get_val(row, 'branch'))
            company_str = _clean_str(get_val(row, 'company'))

            # Resolve Company and Branch
            company_rec = self.resolve_company(company_str, company_cache)
            branch_rec = self.resolve_branch(branch_str, company_rec, branch_cache)

            # Partner
            vendor_partner = self.find_or_create_partner(
                supplier_name, supplier_code,
                create_partner=create_partner,
                partner_cache=partner_cache
            )

            # Label search according to Company and Branch
            lbl = self.find_label(
                label_name=label_name,
                barcode=barcode,
                barcode2=barcode2,
                branch=branch_rec,
                company=company_rec,
                match_by=match_by
            )

            if lbl:
                vals = {}
                if vendor_partner and hasattr(lbl, 'partner_id') and lbl.partner_id != vendor_partner:
                    vals['partner_id'] = vendor_partner.id

                if barcode2 and lbl.barcode2 != barcode2:
                    vals['barcode2'] = barcode2

                if barcode and not lbl.barcode:
                    vals['barcode'] = barcode

                # Ensure branch and company are populated on label if missing
                if branch_rec and hasattr(lbl, 'branch_id') and not lbl.branch_id:
                    vals['branch_id'] = branch_rec.id
                if company_rec and hasattr(lbl, 'company_id') and not lbl.company_id:
                    vals['company_id'] = company_rec.id

                if vals:
                    lbl.write(vals)
                    stats['updated'] += 1
                else:
                    stats['unchanged'] += 1
            else:
                stats['not_found'] += 1
                unmatched_rows.append({
                    'row': row_idx,
                    'label': label_name or '-',
                    'barcode': barcode or '-',
                    'barcode2': barcode2 or '-',
                    'vendor': supplier_name or '-',
                    'branch': branch_str or '-',
                    'company': company_str or '-',
                })

            if stats['total'] % 200 == 0:
                self.env.cr.commit()
                _logger.info("ProductLabelImportService: processed %s rows...", stats['total'])

        self.env.cr.commit()
        stats['vendors_count'] = len(partner_cache)
        stats['unmatched_rows'] = unmatched_rows[:50]
        _logger.info("ProductLabelImportService: Finished. Stats: %s", stats)

        return stats
