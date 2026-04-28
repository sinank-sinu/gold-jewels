{
    'name': 'Product Movement Report',
    'version': '17.0.1.0.0',
    'depends': ['sale_management', 'point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/product_movement_wizard_view.xml',
        'report/product_movement_report_action.xml',
        'report/product_movement_xlsx.xml',
        'report/product_movement_report_template.xml',
        'views/product_movement_menu.xml',
    ],
    'installable': True,
    'application':False
}