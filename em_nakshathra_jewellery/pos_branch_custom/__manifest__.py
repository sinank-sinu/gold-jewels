{
    'name': 'POS Branch wise product listing Custom',
    'version': '17.0.1.0.0',
    'summary': 'POS Branch wise product listing Custom',
    'category': 'Sales/Point of Sale',
    
    'depends': [
        'point_of_sale','multi_branch_base'
    ],

    'data': [
        'views/pos_config_view.xml',
    ],

    'installable': True,
    'application': False,
    'auto_install': False,
}