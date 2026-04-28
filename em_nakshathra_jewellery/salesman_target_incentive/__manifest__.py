{
    'name': 'Salesman Target & Incentive',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'Track salesman targets (amount + GMS) and compute fixed incentives',
    'description': 'Set periodic amount and gram targets for salespersons. Auto-compute achievements from confirmed sale orders. Earn fixed incentive when both targets are hit.',
    'depends': ['sale', 'hr', 'em_jewellery_management'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/salesman_target_views.xml',
        'views/hr_employee_inherit.xml',
    ],
    'auto_install': False,
    'application': False,
    'installable': True,
}
