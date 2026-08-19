import sys
import openpyxl
import json
import xmlrpc.client

# We will just parse the excel and then print out some stats.
file_path = "/home/empireae/odoo17/custom_addons/em_nakshathra/em_nakshathra_jewellery/custom_sale_import/data/DMD LLPSALES 01-04-2026 TO 11-04-2026.xlsx"

try:
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    sales_sn = next((s for s in wb.sheetnames if s.strip().upper() == 'SALES' or s.strip().upper().startswith('SALE')), wb.sheetnames[0])
    
    sales_header_row = next(wb[sales_sn].iter_rows(min_row=1, max_row=1, values_only=True))
    headers = [str(h).lower().strip().replace(' ', '').replace('.', '').replace('-', '').replace('_', '') if h else '' for h in sales_header_row]

    c_m = {}
    for i, h in enumerate(headers):
        if 'company' in h: c_m['company'] = i
        elif 'branch' in h: c_m['branch'] = i
        elif 'vou' in h and 'no' in h: c_m['vou_no'] = i
        elif 'party' in h or 'cust' in h: c_m['party'] = i
        elif 'date' in h: c_m['vou_date'] = i

    vouchers = set()
    rows = []
    
    for row_idx, row in enumerate(wb[sales_sn].iter_rows(min_row=2, values_only=True), start=2):
        if not any(row):
            continue
        r = list(row) + [None] * 50
        vou = str(r[c_m.get('vou_no', 1)]).strip() if r[c_m.get('vou_no', 1)] is not None else ''
        if not vou:
            continue
        vouchers.add(vou)
        
        party = str(r[c_m.get('party', 2)]).strip() if r[c_m.get('party', 2)] is not None else ''
        date_str = str(r[c_m.get('vou_date', 3)]).strip() if r[c_m.get('vou_date', 3)] is not None else ''
        company = str(r[c_m.get('company', 38)]).strip() if r[c_m.get('company', 38)] is not None else ''
        
        rows.append({
            'row_idx': row_idx,
            'vou': vou,
            'party': party,
            'date': date_str,
            'company': company
        })
        
    print(f"Total unique vouchers in Excel: {len(vouchers)}")
    print(f"Total rows in Excel (excluding empty): {len(rows)}")

    # We output the unique vouchers to a file to use it in a DB query
    with open('/tmp/vouchers.json', 'w') as f:
        json.dump(list(vouchers), f)
        
    # Also dump rows for further analysis
    with open('/tmp/excel_rows.json', 'w') as f:
        json.dump(rows, f)
        
except Exception as e:
    print(f"Error parsing excel: {e}")
