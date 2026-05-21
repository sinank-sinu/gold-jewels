{
    'name': 'Jewellery Salesman Tablet Cart',
    "version": "17.0.1.0.0",
    'category': 'Sales/Jewellery',
    'summary': 'Interactive Floor Tray Cart Management for Salesmen via Tablet Dashboards',
    'depends': ['stock', 'sale', 'mail', 'crm', 'em_jewellery_management'],
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'salesman_cart_custom/static/src/components/salesman_cart/salesman_cart_dashboard.js',
            'salesman_cart_custom/static/src/components/salesman_cart/salesman_cart_dashboard.xml',
        ],
    },
    'installable': True,
    'application': False,
}