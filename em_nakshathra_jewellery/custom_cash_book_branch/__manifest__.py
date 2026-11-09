# -*- coding: utf-8 -*-
{
    'name': 'Branch Treasury & Payment Balances (Bank, Cash, Card, UPI)',
    'version': '17.0.2.0.16',
    'summary': 'Beautiful Treasury & Payment Balance UI for Bank, Cash, Card and UPI by Branch and Date',
    'category': 'Accounting',
    'depends': ['base', 'account', 'dynamic_accounts_report', 'multi_branch_base', 'em_jewellery_management'],
    'data': [
        'security/ir.model.access.csv',
        'views/branch_payment_balance_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_cash_book_branch/static/src/css/branch_payment_balance.css',
            'custom_cash_book_branch/static/src/js/branch_payment_balance.js',
            'custom_cash_book_branch/static/src/xml/branch_payment_balance.xml',
            'custom_cash_book_branch/static/src/js/cash_book_extend.js',
            'custom_cash_book_branch/static/src/xml/cash_book_templates.xml',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
