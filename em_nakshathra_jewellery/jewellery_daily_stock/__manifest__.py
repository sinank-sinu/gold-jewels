{
    'name': 'Jewellery Daily Stock Check',
    'version': '1.0',
    'depends': ['base', 'stock', 'product','multi_branch_base','em_jewellery_management'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_check_line_views.xml',
    ],
    'installable': True,
    'application': True,
}
