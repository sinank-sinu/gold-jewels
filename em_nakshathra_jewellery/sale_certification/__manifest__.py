{
    'name': 'Sale Certification',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'Add certification fields to sale orders',
    'description': 'This module adds image upload and diamond certification fields to the sale order other info section.',
    'depends': ['sale', 'em_jewellery_management'],
    'data': [
        'views/sale_order_views.xml',
    ],
    'auto_install': False,
    'application': True,
    'installable': True,
}
