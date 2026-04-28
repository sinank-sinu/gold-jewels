{
    'name': 'POS Premium Theme',
    'version': '17.0.1.0.0',
    'summary': 'Modern, professional premium theme for Odoo POS',
    'description': """
        A premium Point of Sale theme inspired by modern retail POS systems
        (Square, Shopify POS). Features:
        - Clean, minimal, professional design
        - Card-based product grid with hover & click animations
        - Soft shadows, rounded corners, smooth spacing
        - Premium color palette with #714b67 / #432c3d gradient
        - Fully responsive: desktop, tablet, touchscreen
    """,
    'category': 'Sales/Point of Sale',
    'author': 'Nakshathra Jewellery',
    'depends': ['point_of_sale'],
    'data': [
        'views/assets.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_premium_theme/static/src/scss/pos_premium_theme.scss',
            'pos_premium_theme/static/src/xml/navbar.xml',
        ],
    },
    'images': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
