{
    'name': 'Scheme Payment Receipt Correction',
    'version': '17.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Utility to correct existing Scheme Payment Receipt journal entries',
    'description': """
This module corrects the debit side of already posted Scheme Payment Receipt journal entries.
It changes the debit account to the journal's Outstanding Receipts account.
    """,
    'author': 'Deepmind',
    'depends': ['account', 'base'],
    'data': [
        'security/ir.model.access.csv',
        'views/correction_log_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
