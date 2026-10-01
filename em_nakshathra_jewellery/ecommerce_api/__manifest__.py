{
    'name': 'Ecommerce API',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'API for Ecommerce products filtering by branch',
    'description': 'Provides a REST endpoint to fetch products based on branch selection, and customer register/login APIs.',
    'depends': ['base', 'base_setup', 'product', 'multi_branch_base'],
    'data': [
        'security/ir.model.access.csv',
        'data/ecommerce_api_control_data.xml',
        'views/ecommerce_api_control_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
