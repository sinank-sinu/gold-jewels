{
    'name': 'Sale Order Scheme Outstanding Credit',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'Display customer scheme outstanding credits in Invoice Other Info tab',
    'description': """
        This module adds a Many2many field for Customer Schemes (Outstanding Credits) in Invoice Other Info tab.
    """,
    'depends': ['sale', 'account', 'em_jewellery_management', 'em_jewellery_customisation'],
    'data': [
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
