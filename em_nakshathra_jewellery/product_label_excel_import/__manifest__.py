{
    'name': 'Product Label Excel Import',
    'version': '17.0.1.0.0',
    'depends': [ "base",
        "stock",
        "product",
         "purchase",
        "uom",
        "em_jewellery_management",],
    'data': [
        'security/ir.model.access.csv',
        'wizard/product_label_import_wizard_view.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
}
