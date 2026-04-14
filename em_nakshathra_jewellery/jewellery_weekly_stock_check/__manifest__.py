{
    'name': 'Jewellery Weekly Stock Check',
    'version': '1.0',
    'summary': 'Weekly stock checking for jewellery with privacy features for counters.',
    'description': """
        This module provides a weekly stock checking mechanism for jewellery.
        It allows counters to perform stock counts without seeing the theoretical system values.
        Managers can then verify and match these counts against the system records.
    """,
    'author': 'Antigravity',
    'depends': ['base', 'stock', 'product', 'multi_branch_base', 'em_jewellery_management'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'report/stock_check_reports.xml',
        'report/stock_check_templates.xml',
        'views/weekly_stock_check_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
