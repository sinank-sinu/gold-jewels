{
    'name': 'Jewellery Stock Movement Report',
    'version': '17.0.2.0.0',
    'category': 'Inventory/Jewellery',
    'summary': 'Dynamic Opening / In / Out / Closing Stock Movement Report by Date, Branch, Warehouse & Location',
    'description': """
        Native Odoo Stock Movement Report for Stock Checks module.
        - Native Odoo List/Tree view grouped by Product Template
        - Expandable groups showing all variants of each product
        - Top-level Warehouse selection dropdown
        - Branch, Warehouse and Location filters (multi branch aware)
        - Date based Opening, Stock In, Stock Out and Closing (quantity and weight)
    """,
    'author': 'Antigravity',
    'depends': [
        'stock',
        'jewellery_weekly_stock_check',
        'multi_branch_base',
        'em_jewellery_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_movement_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jewellery_stock_movement/static/src/views/stock_movement.css',
            'jewellery_stock_movement/static/src/views/stock_movement_list_view.js',
            'jewellery_stock_movement/static/src/views/stock_movement_list_view.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
