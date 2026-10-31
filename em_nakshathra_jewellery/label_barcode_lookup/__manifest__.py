# -*- coding: utf-8 -*-
{
    'name': 'Barcode Label Lookup Wizard',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'Temporary wizard in Sales to view jewellery label details when searching a barcode without saving to database',
    'description': """
Barcode Label Details Lookup Wizard (Sales Only)
================================================
- Opens a dedicated modal popup to scan or enter a barcode.
- Accessible directly from the top navigation bar right before the messages icon when in the Sales app.
- Also accessible from Sales -> Products and Sales -> Orders menus, and directly from Sales Orders.
- Instantly searches and displays all product label details (ornament photo, variant, weights, purity, branch, current location, pricing, status).
- Temporary inspection only: when closing the wizard, all data is immediately discarded and nothing is saved in the database.
    """,
    'author': 'Nakshathra Jewellery',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'sale',
        'em_jewellery_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/label_barcode_lookup_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'label_barcode_lookup/static/src/scss/barcode_lookup_systray.scss',
            'label_barcode_lookup/static/src/xml/barcode_lookup_systray.xml',
            'label_barcode_lookup/static/src/js/barcode_lookup_systray.js',
            'label_barcode_lookup/static/src/js/barcode_auto_search_field.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
