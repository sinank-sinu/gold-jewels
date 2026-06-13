{
    'name': 'Job Work XLSX Report',
    'version': '17.0.1.0.0',
    'category': 'Jewellery',
    'summary': 'Job Work Report with XLSX export',
    'description': 'Job Work Report Wizard with date range and branch selection, exports to XLSX format',
    'depends': ['em_metal_ledger', 'em_jewellery_management', 'report_xlsx'],
    'data': [
        'security/ir.model.access.csv',
        'views/job_work_xlsx_wizard_view.xml',
        'report/job_work_xlsx_action.xml',
    ],
    'auto_install': False,
    'application': True,
    'installable': True,
}
