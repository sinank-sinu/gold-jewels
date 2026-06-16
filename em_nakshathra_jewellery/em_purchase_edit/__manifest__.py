{
    'name': 'EM Purchase Order Edit',
    'version': '17.0.1.0.0',
    'category': 'Purchases',
    'summary': 'Adds an Edit Order workflow to confirmed Purchase Orders',
    'description': """
        This module introduces an "Edit Order" and "Save Order" workflow for Purchase Orders,
        allowing safe modification of quantities by automatically returning received stock and
        updating vendor bills, similar to the Sale Order edit flow.
    """,
    'depends': ['purchase', 'stock', 'account', 'em_jewellery_management'],
    'data': [
        'views/purchase_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
