{
    'name': 'PO Purity Updater',
    'version': '17.0.1.0.0',
    'summary': 'Upload the OG excel sheet and bulk-update purity on Purchase Order lines',
    'description': """
Upload the OG (old-gold) excel sheet (as shown in the DMD LLP sales file, "OG" tab)
and automatically update the purity field on the matching Purchase Order line(s).

Matching logic per row:
 1. Find the Purchase Order using the "Purchase Voucher No" column.
 2. If the PO has a single line -> update its purity.
 3. If the PO has multiple lines -> match the correct line by comparing the
    "Gross Wt" column against each line's gross-weight field (within a small tolerance).
 4. Purity is parsed out of the "Carat" column, e.g. "22CT(91.6)" -> 91.6.

All field names / column names are configurable at the top of
models/po_purity_updater.py - adjust them to match your actual Odoo fields.
""",
    'category': 'Purchases',
    'author': 'Custom',
    'depends': ['purchase', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/upload_templates.xml',
        'views/po_purity_update_log_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
