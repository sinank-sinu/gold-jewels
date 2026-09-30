{
    'name': 'HR Mobile API',
    "version": "17.0.1.0.0",
    'depends': ['base', 'base_setup', 'hr', 'em_jewellery_management'],
    'data': [
        'security/ir.model.access.csv',
        'data/scheme_api_control_data.xml',
        'views/scheme_api_control_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
}