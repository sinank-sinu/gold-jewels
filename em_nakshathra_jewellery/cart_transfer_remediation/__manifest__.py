# -*- coding: utf-8 -*-
{
    'name': 'Cart Transfer Remediation',
    'version': '17.0.1.0.0',
    'category': 'Jewellery Management',
    'summary': 'Standalone Web Console to purge duplicate cart transfers, restore stock to FINAL, and align picking headers',
    'author': 'Nakshathra',
    'depends': [
        'base',
        'stock',
        'em_jewellery_management',
    ],
    'data': [
        'views/views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
