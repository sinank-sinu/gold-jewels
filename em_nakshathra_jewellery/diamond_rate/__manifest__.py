# -*- coding: utf-8 -*-
{
    'name': 'Diamond Rate',
    'version': '17.0.1.0.0',
    'category': 'Jewellery Management',
    'summary': 'Diamond Rate Master and Automatic Sale Diamond Amount Calculation on Product Labels',
    'description': """
Diamond Rate Management
=======================
* Tab directly after the GOLD tab in Jewellery navbar.
* Diamond Rate master with rate per carat, date, purity, and rate type.
* Matches the rate management layout with Update action and logging.
* Automatic calculation of Sale Diamond Amount on Product Labels: Diamond Weight (ct) * Diamond Rate.
    """,
    'author': 'Sinan k Ahammed',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'em_jewellery_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/diamond_rate_views.xml',
        'views/diamond_menu.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
