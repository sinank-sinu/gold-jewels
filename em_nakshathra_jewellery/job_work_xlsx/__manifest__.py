{
    'name': 'Job Work XLSX Report',
    'version': '17.0.1.0.0',
    'category': 'Jewellery',
    'summary': 'Job Work Report with XLSX export functionality',
    'description': 'Job Work Report Wizard with XLSX export for job work transactions.',
    'depends': ['em_jewellery_management'],
    'data': [
        'views/job_work_report_view.xml',
        'views/job_work_report_wizard_view.xml',
    ],
    'auto_install': False,
    'application': True,
    'installable': True,
}
