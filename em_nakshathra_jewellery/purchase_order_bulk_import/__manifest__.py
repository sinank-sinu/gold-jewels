{
    'name': 'Purchase Order Bulk Import',
    'version': '17.0.1.9.0',
    'summary': 'Import 100,000+ Purchase Orders from CSV/XLSX with batch processing',
    'category': 'Purchase',
    'author': 'Custom',
    'depends': ['purchase', 'base_setup'],
    'external_dependencies': {
        'python': ['openpyxl', 'xlsxwriter'],
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/po_import_job_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'purchase_order_bulk_import/static/src/css/po_import.css',
            'purchase_order_bulk_import/static/src/xml/po_bulk_import.xml',
            'purchase_order_bulk_import/static/src/js/po_bulk_import.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}