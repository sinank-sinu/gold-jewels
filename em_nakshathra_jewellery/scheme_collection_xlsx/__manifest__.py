{
    'name': 'Scheme Collection XLSX Report',
    'version': '17.0.1.0.0',
    'category': 'Jewellery',
    'summary': 'Scheme Collection Report with XLSX export',
    'description': 'Scheme Collection Report Wizard with date range and branch selection, exports to XLSX format',
    'depends': ['em_jewellery_management', 'report_xlsx'],
    'data': [
        'security/ir.model.access.csv',
        'views/scheme_collection_xlsx_wizard_view.xml',
        'report/scheme_collection_xlsx_action.xml',
    ],
    'auto_install': False,
    'application': True,
    'installable': True,
}
