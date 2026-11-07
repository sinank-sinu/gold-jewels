# -*- coding: utf-8 -*-
{
    'name': 'Jewellery Inter-Company Label Transfer',
    'version': '17.0.1.0.0',
    'summary': 'Dedicated document and workflow to transfer product labels directly between sister companies with automated stock movements, purchase order, vendor bill, and label creation.',
    'description': """
Jewellery Inter-Company Label Transfer
======================================
This module provides a dedicated Inter-Company Transfer document (like Internal Transfers) under Jewellery -> Ornaments:
- Dedicated menu item: Jewellery -> Ornaments -> Inter-Company Transfers.
- Create transfer document with Source Company/Branch/Location and Destination Company/Branch/Location.
- Barcode Scanner support: scan or type label barcode or number to immediately add rows to transfer lines.
- Deducts stock from the source company.
- Archives source labels in the originating company to prevent double-selling.
- Automatically generates and confirms a Purchase Order in the destination company.
- Automatically receives incoming stock (stock-in) and posts the Vendor Bill.
- Automatically creates new active Product Labels in the destination company linked to the new PO.
- Preserves original barcodes, label numbers (names), tag weights, gross weights, purities, and jewelry attributes.
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
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'report/intercompany_transfer_report.xml',
        'views/label_intercompany_transfer_views.xml',
        'views/product_label_views.xml',
        'wizard/label_intercompany_transfer_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
