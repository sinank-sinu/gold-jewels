# -*- coding: utf-8 -*-
{
    'name': 'Customer Payments Excel Import',
    'version': '17.0.1.0.0',
    'summary': 'Import customer payments from Excel sheets',
    'category': 'Accounting',
    'author': 'sinan',
    'depends': [
        'base',
        'account',
        'base_accounting_kit',
        'pine_labs_payment',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/scheme_suspense_import_wizard_view.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
