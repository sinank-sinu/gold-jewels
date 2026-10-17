# -*- coding: utf-8 -*-
{
    'name': 'Product Variant Multiple Images',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Allow uploading up to 4 images for Product Variants and Products',
    'description': """
Product Variant Multiple Images
================================
This module allows uploading up to 4 images on Product Variants and Products:
- Image 1 (Primary / Main Image)
- Image 2
- Image 3
- Image 4
Both on Product Variants (product.product) and Product Templates (product.template).
    """,
    'author': 'Antigravity',
    'depends': [
        'product',
        'stock',
    ],
    'data': [
        'views/product_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'product_multiple_images/static/src/fields/multi_image_box/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
