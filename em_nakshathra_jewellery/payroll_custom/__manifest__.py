{
    'name': 'Payroll Customisation',
    'version': '17.0.1.0.0',
    'summary': 'Custom payroll rules based on salary sheet',
    'category': 'Human Resources/Payroll',
    
    'depends': [
        'hr_payroll_community',
    ],

    'data': [
        'data/salary_rules.xml',
    ],

    'installable': True,
    'application': False,
    'auto_install': False,
}