# -*- coding: utf-8 -*-
{
    'name': 'Jewellery Label Customizations',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'Customizations for product label printing and fields',
    'description': """
        Customizes the product label PDF report and form views:
        - Adds Diamond Weight (D.Wt) to the printed label.
        - Renames 'Max MC' to 'MC' in the label print layout.
        - Adds Diamond Weight fields to the main form view and tree view for easier access.
    """,
    'author': 'Antigravity',
    'depends': ['em_jewellery_management'],
    'data': [
        'report/label_template.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
