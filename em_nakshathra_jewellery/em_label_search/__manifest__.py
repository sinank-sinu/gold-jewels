{
    'name': 'Jewellery Label Search',
    'version': '17.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Search jewellery labels by scanning their barcodes',
    'depends': [
        'em_jewellery_management',
        'em_barcode_scanner',
        'custom_label_user',
        'ornament_label',
        'em_jewellery_customisation',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/label_search_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'em_label_search/static/src/css/label_search.css',
        ],
    },
    'installable': True,
    'application': False,
}
