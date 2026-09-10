{
    'name': 'Scheme Data Cleanup',
    'version': '17.0.1.0.0',
    'category': 'Jewellery Management',
    'summary': 'Revert and cleanup scheme enrollments, installments, payments, and journal entries safely',
    'author': 'Nakshathra',
    'depends': [
        'base',
        'account',
        'em_jewellery_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/scheme_cleanup_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
