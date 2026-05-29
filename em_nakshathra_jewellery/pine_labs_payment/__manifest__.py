# -*- coding: utf-8 -*-
{
    'name': 'Pine Labs Payment Integration',
    'version': '17.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Integrate Pine Labs payment terminal for POS, Sales, and Purchase',
    'description': """
        Integrates Pine Labs payment gateway and POS terminal machines with Odoo.
        Supports:
        - Point of Sale (POS) terminal payment
        - Sales Order backend payment via Pine Labs
        - Purchase Order / Vendor Payment via Pine Labs
        - Transaction tracking and logging
        - Retry, refund, and partial payment support
    """,
    'author': 'Nakshathra Jewellery',
    'website': '',
    'depends': [
        'mail',
        'point_of_sale',
        'sale_management',
        'purchase',
        'account',
        'account_payment',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/pinelabs_payment_method_data.xml',
        'views/pinelabs_transaction_views.xml',
        'views/pos_payment_method_views.xml',
        'views/pinelabs_terminal_views.xml',
        # 'views/sale_order_views.xml',
        'views/account_move_views.xml',
        'views/account_payment_views.xml',
        'wizard/pinelabs_payment_wizard_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pine_labs_payment/static/src/js/payment_pinelabs.js',
            'pine_labs_payment/static/src/js/pos_pinelabs.js',
            'pine_labs_payment/static/src/js/model.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
