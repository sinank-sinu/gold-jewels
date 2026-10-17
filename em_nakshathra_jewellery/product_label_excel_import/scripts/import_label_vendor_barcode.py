#!/usr/bin/env python3
"""
Standalone Script: Import Vendor & Second Barcode into Product Label
===================================================================

Usage:
    /home/empireae/odoo17/venv/bin/python custom_addons/em_nakshathra/em_nakshathra_jewellery/product_label_excel_import/scripts/import_label_vendor_barcode.py [OPTIONS]

Options:
    --file PATH         Path to the Excel file (.xlsx)
                        (Default: custom_addons/em_nakshathra/label barcode and vendor import .xlsx)
    --conf PATH         Path to Odoo configuration file
                        (Default: debian/odoo.conf)
    --db DBNAME         Target Odoo database name
                        (Default: server_production1)
    --match-by MODE     Matching mode: auto, name, barcode, barcode2
                        (Default: auto)
    --no-create-vendor  Do not create new vendor partners if not found
    --dry-run           Test run without committing changes to the database
"""

import os
import sys
import argparse
import re
import openpyxl

# Add Odoo root to python path
ODOO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../"))
if ODOO_ROOT not in sys.path:
    sys.path.insert(0, ODOO_ROOT)


def normalize_header(header):
    if not header:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(header).lower())


def clean_str(val):
    if val is None or val is False:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    val_str = str(val).strip()
    if val_str.endswith(".0") and val_str[:-2].isdigit():
        return val_str[:-2]
    return val_str


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
        'branchname', 'branch', 'branch_id', 'shop', 'branch_name', 'branchcode'
    ],
    'company': [
        'companyname', 'company', 'company_id', 'company_name'
    ],
}


def build_header_col_map(header_row):
    col_map = {}
    for idx, cell_val in enumerate(header_row):
        if not cell_val:
            continue
        norm = normalize_header(cell_val)
        for field_key, aliases in ALIAS_MAP.items():
            if norm == field_key or norm in aliases:
                if field_key not in col_map:
                    col_map[field_key] = idx
    return col_map


def find_or_create_partner(env, supplier_name, supplier_code, create_partner, partner_cache):
    supplier_name = clean_str(supplier_name)
    supplier_code = clean_str(supplier_code)

    if not supplier_name and not supplier_code:
        return False

    cache_key = (supplier_name.lower(), supplier_code.lower())
    if cache_key in partner_cache:
        return partner_cache[cache_key]

    partner = False
    Partner = env['res.partner'].sudo()

    # 1. Match by ref (Supplier Code)
    if supplier_code:
        partner = Partner.search([('ref', '=', supplier_code)], limit=1)

    # 2. Match by exact name
    if not partner and supplier_name:
        partner = Partner.search([('name', '=ilike', supplier_name)], limit=1)

    # 3. Match by name = supplier_code
    if not partner and supplier_code:
        partner = Partner.search([('name', '=ilike', supplier_code)], limit=1)

    # 4. Create partner if enabled
    if not partner and create_partner:
        vals = {
            'name': supplier_name or supplier_code,
            'supplier_rank': 1,
            'is_company': True,
        }
        if supplier_code:
            vals['ref'] = supplier_code
        partner = Partner.create(vals)
        print(f"  [+] Created new vendor partner: '{partner.name}' (Code: {partner.ref or '-'}, ID: {partner.id})")

    partner_cache[cache_key] = partner
    return partner


def resolve_company(env, company_val, company_cache):
    company_str = clean_str(company_val)
    if not company_str:
        return False

    cache_key = company_str.lower()
    if cache_key in company_cache:
        return company_cache[cache_key]

    Company = env['res.company'].sudo()
    comp = False
    norm_val = normalize_header(company_str)

    if company_str.isdigit():
        c = Company.browse(int(company_str))
        if c.exists():
            comp = c

    if not comp:
        comp = Company.search([('name', '=ilike', company_str)], limit=1)

    if not comp:
        for c in Company.search([]):
            if normalize_header(c.name) == norm_val:
                comp = c
                break

    if not comp:
        for c in Company.search([]):
            c_norm = normalize_header(c.name)
            if ('hyd' in norm_val and 'hyd' in c_norm) or ('silver' in norm_val and 'silver' in c_norm):
                comp = c
                break

    company_cache[cache_key] = comp
    return comp


def resolve_branch(env, branch_val, company_record, branch_cache):
    branch_str = clean_str(branch_val)
    if not branch_str:
        return False

    comp_id = company_record.id if company_record else False
    cache_key = (branch_str.lower(), comp_id)
    if cache_key in branch_cache:
        return branch_cache[cache_key]

    Branch = env['res.branch'].sudo()
    br = False
    norm_val = normalize_header(branch_str)
    base_domain = [('company_id', '=', comp_id)] if comp_id else []

    if branch_str.isdigit():
        b = Branch.browse(int(branch_str))
        if b.exists() and (not comp_id or b.company_id.id == comp_id):
            br = b

    if not br:
        domain = base_domain + ['|', ('branch_code', '=ilike', branch_str), ('name', '=ilike', branch_str)]
        br = Branch.search(domain, limit=1)

    if not br:
        for b in Branch.search(base_domain):
            if normalize_header(b.name) == norm_val or (b.branch_code and normalize_header(b.branch_code) == norm_val):
                br = b
                break

    if not br:
        for b in Branch.search(base_domain):
            b_norm = normalize_header(b.name)
            if (b_norm in norm_val or norm_val in b_norm) or ('kasar' in norm_val and 'kasar' in b_norm):
                br = b
                break

    if not br and comp_id:
        for b in Branch.search([]):
            b_norm = normalize_header(b.name)
            if b_norm == norm_val or (b_norm in norm_val or norm_val in b_norm) or ('kasar' in norm_val and 'kasar' in b_norm):
                br = b
                break

    branch_cache[cache_key] = br
    return br


def find_label(env, label_name=False, branch=False, company=False, **kwargs):
    """Search product.label only by Label Reference/Number according to Company and Branch."""
    if not label_name:
        return False

    Label = env['product.label'].sudo().with_context(active_test=False)
    domain_name = [('name', '=', label_name)]
    domain_alt = ['|', ('label_number', '=', label_name), ('label_name', '=', label_name)]

    # 1. Branch + Company
    if branch and company:
        lbl = Label.search(domain_name + [('branch_id', '=', branch.id), ('company_id', '=', company.id)], limit=1)
        if lbl:
            return lbl
        lbl = Label.search(domain_alt + [('branch_id', '=', branch.id), ('company_id', '=', company.id)], limit=1)
        if lbl:
            return lbl

    # 2. Branch only
    if branch:
        lbl = Label.search(domain_name + [('branch_id', '=', branch.id)], limit=1)
        if lbl:
            return lbl
        lbl = Label.search(domain_alt + [('branch_id', '=', branch.id)], limit=1)
        if lbl:
            return lbl

    # 3. Company only
    if company:
        lbl = Label.search(domain_name + [('company_id', '=', company.id)], limit=1)
        if lbl:
            return lbl
        lbl = Label.search(domain_alt + [('company_id', '=', company.id)], limit=1)
        if lbl:
            return lbl

    # 4. Fallback identifier alone
    lbl = Label.search(domain_name, limit=1)
    if lbl:
        return lbl
    lbl = Label.search(domain_alt, limit=1)
    if lbl:
        return lbl

    return False


def main():
    parser = argparse.ArgumentParser(description="Import Vendor & Second Barcode into Product Labels.")
    default_excel = os.path.join(ODOO_ROOT, "custom_addons/em_nakshathra/label barcode and vendor import .xlsx")
    default_conf = os.path.join(ODOO_ROOT, "debian/odoo.conf")

    parser.add_argument("--file", default=default_excel, help=f"Path to Excel file (default: {default_excel})")
    parser.add_argument("--conf", default=default_conf, help=f"Path to odoo.conf (default: {default_conf})")
    parser.add_argument("--db", default="server_production1", help="Target database name (default: server_production1)")
    parser.add_argument("--match-by", default="auto", choices=["auto", "name", "barcode", "barcode2"], help="Match labels by")
    parser.add_argument("--no-create-vendor", action="store_true", help="Do not create vendor if not found")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without committing changes")

    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"ERROR: Excel file not found: {args.file}")
        sys.exit(1)

    if not os.path.isfile(args.conf):
        print(f"ERROR: Odoo config file not found: {args.conf}")
        sys.exit(1)

    print("=" * 70)
    print(" Product Label Vendor & Second Barcode Import Script")
    print("=" * 70)
    print(f" Excel File  : {args.file}")
    print(f" Database    : {args.db}")
    print(f" Config      : {args.conf}")
    print(f" Match By    : {args.match_by}")
    print(f" Dry Run     : {'YES (Changes will NOT be saved)' if args.dry_run else 'NO (Changes will be committed)'}")
    print("=" * 70)

    # Initialize Odoo
    import odoo
    odoo.tools.config.parse_config(['-c', args.conf, '-d', args.db])
    registry = odoo.registry(args.db)

    wb = openpyxl.load_workbook(args.file, data_only=True)
    sheet = wb.active
    rows_iter = sheet.iter_rows(values_only=True)

    try:
        header_row = next(rows_iter)
    except StopIteration:
        print("ERROR: Excel file is empty.")
        sys.exit(1)

    col_map = build_header_col_map(header_row)
    print(f"Mapped columns: {col_map}")

    def get_val(r, key):
        if key in col_map and col_map[key] < len(r):
            return r[col_map[key]]
        return None

    stats = {
        'total': 0,
        'updated': 0,
        'unchanged': 0,
        'not_found': 0,
    }
    unmatched_rows = []
    partner_cache = {}
    company_cache = {}
    branch_cache = {}

    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})

        for row_idx, row in enumerate(rows_iter, start=2):
            if not any(row):
                continue

            stats['total'] += 1

            label_name = clean_str(get_val(row, 'label_name'))
            barcode2 = clean_str(get_val(row, 'barcode2'))
            barcode = clean_str(get_val(row, 'barcode'))
            supplier_name = clean_str(get_val(row, 'supplier_name'))
            supplier_code = clean_str(get_val(row, 'supplier_code'))
            branch_str = clean_str(get_val(row, 'branch'))
            company_str = clean_str(get_val(row, 'company'))

            # Resolve Company and Branch
            company_rec = resolve_company(env, company_str, company_cache)
            branch_rec = resolve_branch(env, branch_str, company_rec, branch_cache)

            # Partner
            vendor_partner = find_or_create_partner(
                env, supplier_name, supplier_code,
                create_partner=not args.no_create_vendor,
                partner_cache=partner_cache
            )

            # Label search according to company and branch (matched by label reference/number)
            lbl = find_label(env, label_name=label_name, branch=branch_rec, company=company_rec)

            if lbl:
                vals = {}
                if vendor_partner and hasattr(lbl, 'partner_id') and lbl.partner_id != vendor_partner:
                    vals['partner_id'] = vendor_partner.id

                if barcode2 and lbl.barcode2 != barcode2:
                    vals['barcode2'] = barcode2

                if barcode and not lbl.barcode:
                    vals['barcode'] = barcode

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
                unmatched_rows.append((row_idx, label_name, barcode, barcode2, branch_str, company_str))

        if args.dry_run:
            cr.rollback()
            print("\n>> Dry run complete. Database rolled back.")
        else:
            cr.commit()
            print("\n>> Changes successfully committed to database.")

    print("\n" + "=" * 70)
    print(" Import Summary Results")
    print("=" * 70)
    print(f" Total Rows Processed : {stats['total']}")
    print(f" Labels Updated       : {stats['updated']}")
    print(f" Already Up-To-Date   : {stats['unchanged']}")
    print(f" Not Found in Odoo    : {stats['not_found']}")
    print(f" Vendors Processed    : {len(partner_cache)}")

    if unmatched_rows:
        print("\n Unmatched Rows Details:")
        for r_no, l_name, bc, bc2, br, co in unmatched_rows[:20]:
            print(f"  Row {r_no:3d} | Label: {l_name or '-':15s} | Barcode: {bc or '-':15s} | Branch: {br or '-':15s} | Company: {co or '-'}")
        if len(unmatched_rows) > 20:
            print(f"  ...and {len(unmatched_rows) - 20} more unmatched rows.")
    print("=" * 70)


if __name__ == "__main__":
    main()
