import openpyxl
import psycopg2
import sys
import datetime

file_path = "/home/empireae/odoo17/custom_addons/em_nakshathra/em_nakshathra_jewellery/custom_sale_import/data/DMD LLPSALES 01-04-2026 TO 11-04-2026.xlsx"
print(f"Loading {file_path}...")
try:
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
except Exception as e:
    print(f"Failed to load excel: {e}")
    sys.exit(1)

sales_sn = next((s for s in wb.sheetnames if s.strip().upper() == 'SALES' or s.strip().upper().startswith('SALE')), wb.sheetnames[0])
sheet = wb[sales_sn]
print(f"Using sheet: {sales_sn}")

headers = []
for row in sheet.iter_rows(min_row=1, max_row=1, values_only=True):
    headers = row
    break

vou_no_idx = None
company_idx = None
date_idx = None
party_idx = None
product_idx = None

for i, h in enumerate(headers):
    if h:
        hl = str(h).lower()
        if 'vou' in hl and 'no' in hl: vou_no_idx = i
        if 'company' in hl: company_idx = i
        if 'date' in hl: date_idx = i
        if 'party' in hl or 'cust' in hl: party_idx = i
        if 'variant' in hl or ('prod' in hl and 'name' in hl) or 'item' in hl: product_idx = i

if vou_no_idx is None:
    print("Could not find 'Vou No' column.")
    sys.exit(1)

excel_vouchers = set()
excel_rows = []

for row in sheet.iter_rows(min_row=2, values_only=True):
    if not any(row):
        continue
    vou_no = str(row[vou_no_idx]).strip() if row[vou_no_idx] else ''
    if vou_no:
        excel_vouchers.add(vou_no)
        excel_rows.append(row)

print(f"Found {len(excel_vouchers)} unique vouchers in Excel.")

try:
    conn = psycopg2.connect(
        dbname='nakshathra_db_23',
        user='odoo17',
        password='odoo17',
        host='localhost',
        port='5432'
    )
    cur = conn.cursor()
    cur.execute("SELECT origin FROM sale_order WHERE origin IS NOT NULL;")
    rows = cur.fetchall()
    db_vouchers = set([r[0] for r in rows if r[0]])
    print(f"Found {len(db_vouchers)} sale orders in DB with an origin.")
    
    missing = excel_vouchers - db_vouchers
    print(f"\nMissing {len(missing)} vouchers in database!")
    
    if missing:
        print("\nChecking Excel data for the missing vouchers...")
        missing_reasons = {}
        for row in excel_rows:
            vou_no = str(row[vou_no_idx]).strip() if row[vou_no_idx] else ''
            if vou_no in missing:
                if vou_no in missing_reasons:
                    continue # already checked
                
                company = row[company_idx] if company_idx is not None else None
                date_val = row[date_idx] if date_idx is not None else None
                party = row[party_idx] if party_idx is not None else None
                
                reason = []
                if not company: reason.append("Missing Company")
                if not date_val: reason.append("Missing Date")
                if not party: reason.append("Missing Customer")
                
                if not reason:
                    missing_reasons[vou_no] = "Data looks OK (likely skipped due to Company name mismatch or another DB lookup failure)"
                else:
                    missing_reasons[vou_no] = ", ".join(reason)
                    
        for v, r in list(missing_reasons.items())[:56]:
            print(f"{v}: {r}")

except Exception as e:
    print("DB Error:", e)
