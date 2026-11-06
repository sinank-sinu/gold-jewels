{
    'name': 'PO Label Manufacture',
    'version': '1.0.0',
    'category': 'Manufacturing/Jewellery',
    'summary': 'Create Manufacturing Order directly from Product Label with components from Purchase Order',
    'description': """
PO Label Manufacture
====================
Adds a 1-click Manufacture button on Product Label form:
- Only visible when Product, Product Variant, Purchase Order, and Sale Gross Weight (g) are provided.
- Creates an MRP Production Order for that product and variant with weight = Sale Gross Weight (g).
- Automatically sources raw components from the matching lines on the Purchase Order.
- Confirms/completes the manufacturing process.
- Displays celebratory interactive animation (Rainbow Man) upon manufacture.
- Disables the button and shows Manufactured status badge.
    """,
    'author': 'Sinan K Ahammed',
    'depends': [
        'mrp',
        'stock',
        'purchase',
        'product',
        'em_jewellery_management',
        'ornament_label',
        'em_jewellery_customisation',
        'em_manufacture_label',
    ],
    'data': [
        'views/product_label_views.xml',
        'views/res_company_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
