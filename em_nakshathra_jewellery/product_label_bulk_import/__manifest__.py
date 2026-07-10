{
    'name': 'Product Label Bulk Import',
    'version': '17.0.1.0.0',
    'summary': 'Import 10,000+ Product Labels per batch from CSV/XLSX and auto-transfer (stock-in)',
    'category': 'Inventory',
    'author': 'Custom',
    'depends': ['stock', 'product', 'em_jewellery_management'],
    'external_dependencies': {
        'python': ['openpyxl', 'xlsxwriter'],
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/label_import_job_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'product_label_bulk_import/static/src/css/label_import.css',
            'product_label_bulk_import/static/src/xml/label_bulk_import.xml',
            'product_label_bulk_import/static/src/js/label_bulk_import.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}