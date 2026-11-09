# -*- coding: utf-8 -*-
{
    'name': 'Inter-Company Transfer',
    'version': '17.0.1.0.0',
    'summary': 'Dedicated document and workflow to transfer product labels directly between other companies with automated stock movements, purchase order, vendor bill, and label creation.',
    'description': """
Inter-Company Transfer
======================
Dedicated application to manage and execute inter-company product label transfers:
- Standalone top-level application in Odoo.
- Create transfer documents with Source Company/Branch/Location and Destination Company/Branch/Location.
- Barcode Scanner support: scan or type label barcode or number to immediately add rows to transfer lines.
- Deducts stock from the source company.
- Archives source labels in the originating company to prevent double-selling.
- Automatically generates and confirms a Sale Order / Purchase Order between companies.
- Automatically creates customer invoice / vendor bill and stock delivery/receipt.
- Automatically creates new active Product Labels in the destination company linked to the new PO.
- Preserves original barcodes, label numbers, tag weights, gross weights, purities, and jewelry attributes.
    """,
    'category': 'Jewellery Management',
    'author': 'Nakshathra ERP Team',
    'depends': [
        'base',
        'mail',
        'stock',
        'purchase',
        'account',
        'em_jewellery_management',
        'jewellery_sequence_custom',
    ],
    'data': [
        'security/intercompany_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'report/intercompany_transfer_report.xml',
        'views/label_intercompany_transfer_views.xml',
        'views/product_label_views.xml',
        'views/res_users_views.xml',
        'wizard/label_intercompany_transfer_wizard_views.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
