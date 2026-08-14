# -*- coding: utf-8 -*-
{
    'name': 'Custom Cash Book Branch Filter',
    'version': '17.0.1.1.2',
    'summary': 'Extend Cash Book Report with Branch Filters',
    'category': 'Accounting',
    'depends': ['base', 'account', 'dynamic_accounts_report'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_cash_book_branch/static/src/js/cash_book_extend.js',
            'custom_cash_book_branch/static/src/xml/cash_book_templates.xml',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}