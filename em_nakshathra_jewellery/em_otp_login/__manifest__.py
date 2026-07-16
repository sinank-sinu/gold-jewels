{
    'name': 'eSSL Nakshathra OTP Login',
    'version': '1.0',
    'category': 'Website/Privacy',
    'summary': 'Adds OTP verification step after standard login credentials submission.',
    'description': 'Validates email/password, then redirects user to verify a dynamic OTP sent to their mobile number before fully authenticating.',
    'author': 'Antigravity',
    'depends': ['web', 'base', 'sms', 'website', 'base_setup'],
    'data': [
        'data/sms_data.xml',
        'views/login_templates.xml',
        'views/sms_sms_views.xml',
        'views/res_users_views.xml',
        'views/res_config_settings_views.xml',
        'views/sms_template_views.xml',
    ],

    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
