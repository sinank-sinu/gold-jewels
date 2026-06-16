{
    'name': 'Purchase Register Report',
    'version': '17.0.1.0.0',
    'summary': 'Report for Purchase Register with Branch Filter',
    'depends': ['purchase', 'report_xlsx', 'multi_branch_base'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/purchase_register_wizard_view.xml',
        'reports/purchase_register_report.xml',
    ],
    'installable': True,
    'application': False,
}
