{
    'name': 'Manufacture Label',
    'version': '1.0.0',
    'category': 'Manufacturing',
    'summary': 'Add Manufacture Order to Product Label and Label selection to stock moves in MO',
    'depends': ['mrp', 'em_jewellery_management'],
    'data': [
        'views/product_label_views.xml',
        'views/mrp_production_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
