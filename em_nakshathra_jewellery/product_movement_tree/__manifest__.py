{
    'name': 'Product Movement Tree Report',
    'version': '17.0.1.0.0',
    'depends': ['sale_management', 'point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        # 'wizard/product_movement_wizard_view.xml',
        'views/product_movement_tree_view.xml',
        'views/menu.xml',
    ],
    'installable': True,
}