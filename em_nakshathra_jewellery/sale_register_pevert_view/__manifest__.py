{
    'name': 'Sale Register Pivot View',
    'version': '17.0.1.0.0',
    'summary': 'Sale Register – Tree, Pivot & Graph View Report',
    'description': 'Adds a Sale Register submenu under Reporting > Sales with tree, pivot and graph views for all confirmed/done sale orders.',
    'category': 'Sales',
    'author': 'EM Jewellery',
    'depends': ['sale', 'multi_branch_base', 'em_jewellery_management'],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_register_line_view.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
