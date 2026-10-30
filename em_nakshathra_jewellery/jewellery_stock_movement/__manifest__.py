{
    'name': 'Jewellery Stock Movement Report',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Jewellery',
    'summary': 'Native Stock Movement Report by Warehouse & Product Variants',
    'description': """
        Native Odoo Stock Movement Report for Stock Checks module.
        - Native Odoo List/Tree view grouped by Product Template
        - Expandable groups showing all variants of each product
        - Top-level Warehouse selection dropdown
        - Stock In, Stock Out, and Balance metrics with totals
    """,
    'author': 'Antigravity',
    'depends': [
        'stock',
        'jewellery_weekly_stock_check',
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
