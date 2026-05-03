{
    'name': 'Sale Below Maximum Report',
    'version': '17.0.1.0.0',
    'summary': 'Report for sales below minimum making charge',
    'depends': [
        'sale',
        'report_xlsx',
        'em_jewellery_management',  
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_below_max_wizard_view.xml',
    ],
    'installable': True,
    'application': False,
}