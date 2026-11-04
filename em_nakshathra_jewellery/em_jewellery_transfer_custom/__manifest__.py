{
    'name': 'Jewellery Transfer Custom',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'Custom transfer logic for sales orders.',
    'depends': ['em_jewellery_management', 'multi_branch_base'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_branch_views.xml',
        'views/sale_order_views.xml',
        'views/stock_quant_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
