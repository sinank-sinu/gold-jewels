{
    'name': 'Jewellery Management Customisations',
    'version': '17.0.1.0.0',
    'category': 'Technical/Technical',
    'sequence': 1,
    'summary': """module manage jewellery""",
    'description': 'Jewellery Management Customisations',

    'depends': ['em_jewellery_management','report_xlsx'],
    'data': [
        'security/ir.model.access.csv',
        'views/jewellery_menu.xml',
        'views/jewellery_scheme_enrollment_views.xml',
        'reports/scheme_margin_report.xml',
        'views/product_label.xml',
        'views/fine_rate_master_view.xml',
        'views/stock_picking_views.xml',
        'views/sale_order_views.xml',

    ],

    'auto_install': False,
    'application': False,
    'installable': True,
}