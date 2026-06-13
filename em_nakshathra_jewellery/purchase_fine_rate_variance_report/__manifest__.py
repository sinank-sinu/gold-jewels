{
    'name': 'Purchase Fine Rate Variance Report',
    'version': '17.0.1.0.0',
    'summary': 'Report for Purchase Fine Rate Variance Report',
    'depends': ['purchase','report_xlsx'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/purchase_fine_rate_wizard_view.xml',
        'wizard/capital_gain_wizard_view.xml',
        'reports/purchase_fine_rate_report.xml',
        'reports/capital_gain_report.xml'
    ],
    'installable': True,
    'application': False,
}