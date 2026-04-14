# -*- coding: utf-8 -*-
{
    'name': 'Inventory Validation Custom',
    "version": "17.0",
    'summary': 'Restrict the Validation button visibility to the responsible users if contact selected ',
    'category': 'Accounting',
    'author': 'Anjali',
    'depends': ['stock','base','mail','em_jewellery_management'],
    'data': [
        'views/stock_pickings.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}