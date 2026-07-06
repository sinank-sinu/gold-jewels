{
    'name': 'Sale Order Excel Import',
    'version': '17.0.1.0.0',
    'summary': 'Import Sale Orders from Excel',
    'description': """Import Sale Orders from XLS and XLSX files.""",
    'author': 'OpenAI',
    'website': '',
    'category': 'Sales',
    'license': 'LGPL-3',

    'depends': [
        'sale_management',
    ],

    'data': [
        'security/ir.model.access.csv',
        'views/sale_order_import_views.xml',
    ],

    'installable': True,
    'application': False,
}
