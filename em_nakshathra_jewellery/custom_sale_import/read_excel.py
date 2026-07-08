import zipfile
import xml.etree.ElementTree as ET

def get_shared_strings(zf):
    try:
        ss_xml = zf.read('xl/sharedStrings.xml')
        root = ET.fromstring(ss_xml)
        ns = {'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        return [t.text for t in root.findall('.//main:t', ns)]
    except Exception:
        return []

def get_sheet1_rows(zf, ss):
    sheet_xml = zf.read('xl/worksheets/sheet2.xml') # OG is usually sheet2, but we can look for it. Let's just list sheet1, sheet2, sheet3...
    root = ET.fromstring(sheet_xml)
    ns = {'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rows = []
    for row in root.findall('.//main:row', ns):
        row_data = []
        for c in row.findall('.//main:c', ns):
            val = c.find('main:v', ns)
            if val is not None:
                if c.attrib.get('t') == 's':
                    row_data.append(ss[int(val.text)])
                else:
                    row_data.append(val.text)
            else:
                row_data.append('')
        rows.append(row_data)
    return rows

with zipfile.ZipFile('/home/empireae/odoo17/custom_addons/em_nakshathra/em_nakshathra_jewellery/custom_sale_import/data/DUMMY SALES(1)(1).xlsx', 'r') as zf:
    # First find which sheet is OG
    workbook_xml = zf.read('xl/workbook.xml')
    root = ET.fromstring(workbook_xml)
    ns = {'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    sheet_id = None
    for sheet in root.findall('.//main:sheet', ns):
        if sheet.attrib.get('name') == 'OG':
            sheet_id = sheet.attrib.get('sheetId')
            break
            
    if sheet_id:
        ss = get_shared_strings(zf)
        # sheet path might be different, let's just find the corresponding relationship
        rels_xml = zf.read('xl/_rels/workbook.xml.rels')
        rels_root = ET.fromstring(rels_xml)
        ns_rel = {'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'}
        target = None
        for sheet in root.findall('.//main:sheet', ns):
            if sheet.attrib.get('name') == 'OG':
                rId = sheet.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                for rel in rels_root.findall('.//rel:Relationship', ns_rel):
                    if rel.attrib.get('Id') == rId:
                        target = rel.attrib.get('Target')
                        break
        
        if target:
            sheet_xml = zf.read('xl/' + target)
            s_root = ET.fromstring(sheet_xml)
            for i, row in enumerate(s_root.findall('.//main:row', ns)):
                row_data = []
                for c in row.findall('.//main:c', ns):
                    val = c.find('main:v', ns)
                    if val is not None:
                        if c.attrib.get('t') == 's':
                            row_data.append(ss[int(val.text)])
                        else:
                            row_data.append(val.text)
                    else:
                        row_data.append('')
                print(row_data)
                if i > 2:
                    break
