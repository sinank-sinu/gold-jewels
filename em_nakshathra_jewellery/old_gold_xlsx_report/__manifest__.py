{
    'name': 'Old Gold XLSX Report',
    "version": "17.0.1.0.0",
    'summary': 'Old Gold XLSX Report',
    'depends': [
        'base',
        'web',
        'report_xlsx',
        'em_jewellery_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/menu.xml',
        'views/old_gold_margin_wizard_view.xml',
        'views/old_gold_refine_margin_wizard_view.xml',
        'report/old_gold_margin_report.xml',
        'report/old_gold_refine_margin_report.xml',
    ],
    'installable': True,
    'application': False
}
