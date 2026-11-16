{
    'name': 'Product Label HTTP Import',
    'version': '17.0.1.0.0',
    'summary': 'Import 10,000+ Product Labels from Excel via HTTP Controller , Import ui through',
    'category': 'Inventory',
    'depends': ['stock', 'purchase', 'product', 'em_jewellery_management'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/product_label_import_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'product_label_http_import/static/src/xml/import_progress.xml',
            'product_label_http_import/static/src/js/import_progress.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
