{
    'name': 'Sales Target Report',
    'version': '17.0.1.0.0',
    'depends': ['base', 'salesman_target_incentive', 'em_jewellery_management', 'hr','sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/sales_target_report_views.xml',
    ],
    'installable': True,
}
