{
    'name': 'Scheme Due XLSX Report',
    'version': '17.0.1.0.0',
    'category': 'Jewellery',
    'summary': 'Scheme Due Report with XLSX export',
    'description': 'Scheme Due Report Wizard with date range and branch selection, exports to XLSX format',
    'depends': ['em_jewellery_management', 'report_xlsx'],
    'data': [
        'security/ir.model.access.csv',
        'views/scheme_due_xlsx_wizard_view.xml',
        'report/scheme_due_xlsx_action.xml',
    ],
    'auto_install': False,
    'application': True,
    'installable': True,
}
