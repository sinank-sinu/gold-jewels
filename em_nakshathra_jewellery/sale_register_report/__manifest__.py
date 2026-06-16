{
    'name': 'Sale Register Report',
    'version': '17.0.1.0.0',
    'summary': 'Report for Sale Register with Branch Filter',
    'depends': ['sale', 'report_xlsx', 'multi_branch_base'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/sale_register_wizard_view.xml',
        'reports/sale_register_report.xml',
    ],
    'installable': True,
    'application': False,
}
