{
    'name': 'Barcode Scanner – Jewellery Lines',
    'version': '17.0.1.0.0',
    'category': 'Jewellery',
    'summary': 'Integrate Honeywell USB barcode scanner into jewellery product lines',
    'description': """
        Adds a barcode scan input to the Receive Voucher and Issue Voucher Ornaments tab.
        Scanning a product label barcode automatically populates a new product line
        with product, purity, and weight details from the product.label record.
    """,
    'author': 'Nakshathra Jewellery',
    'depends': ['em_jewellery_management', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/receive_voucher_inherit.xml',
        'views/issue_voucher_inherit.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'em_barcode_scanner/static/src/css/barcode_scanner.css',
            'em_barcode_scanner/static/src/xml/barcode_scanner_widget.xml',
            'em_barcode_scanner/static/src/js/barcode_scanner_widget.js',
        ],
    },
    'auto_install': False,
    'application': False,
    'installable': True,
}
