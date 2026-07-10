{
    'name': 'Ecommerce API',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'API for Ecommerce products filtering by branch',
    'description': 'Provides a REST endpoint to fetch products based on branch selection, and customer register/login APIs.',
    'depends': ['base', 'product', 'multi_branch_base'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
