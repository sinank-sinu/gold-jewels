{
    'name': 'Stock Location Excess Weight',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Find and monitor excess and shortage weight across stock locations via physical inventory verification',
    'description': """
Stock Location Excess Weight & Verification
===========================================
This module enables jewellery businesses to track, audit, and analyze physical weighed stock vs system stock weight per location:
* Computes system weight from Active Product Labels (gross weight) and Stock Quants (on-hand weight)
* Allows entering and tracking physical scale weight per stock location
* Automatically calculates Difference, Excess Weight (surplus), and Shortage Weight (deficit) with tolerance support
* Provides dedicated list views, search filters for Excess/Shortage locations, and inline editing
* Maintains complete audit history of weight verifications per location
* Includes an Excel (.xlsx) export report for branch-wise excess weight audits
    """,
    'author': 'Sinan / EM Nakshathra',
    'depends': [
        'base',
        'stock',
        'product',
        'multi_branch_base',
        'em_jewellery_management',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'wizard/stock_location_weight_wizard_views.xml',
        'wizard/location_excess_weight_export_wizard_views.xml',
        'wizard/stock_location_product_load_wizard_views.xml',
        'wizard/stock_location_product_excess_transfer_wizard_views.xml',
        'views/stock_location_weight_check_views.xml',
        'views/stock_location_product_weight_views.xml',
        'views/stock_location_views.xml',
        'views/excess_weight_menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
