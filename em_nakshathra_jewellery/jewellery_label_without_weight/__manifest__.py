# -*- coding: utf-8 -*-
{
    'name': 'Jewellery Labels Without Weight',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Jewellery',
    'summary': 'View, audit, and manage product labels that do not have weight',
    'description': """
        Track and Audit Product Labels Without Weight.
        - Dedicated view and audit list for labels with zero or missing weight
        - Filter by active and inactive / sold / in-transit labels
        - Group by Branch, Product Template, Location, and Creation Date
        - Integrated under Jewellery Products and Stock Checks menus
    """,
    'author': 'Antigravity',
    'depends': [
        'em_jewellery_management',
        'jewellery_weekly_stock_check',
    ],
    'data': [
        'views/product_label_without_weight_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
