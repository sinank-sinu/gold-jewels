# -*- coding: utf-8 -*-
{
    'name': 'Branch Label Verification & Stock Audit',
    'version': '17.0.1.0.0',
    'category': 'Jewellery',
    'summary': 'Check label counts in the default branch and verify each label individually via barcode scanner or audit check',
    'description': """
Branch Label Verification & Stock Audit
========================================
- Automatically detects and defaults to the logged-in user's default branch.
- Instant overview: Check how many total labels, active labels, and inactive/sold labels are in the branch.
- Breakdowns by Location and Product Category.
- Rapid Barcode Scanning: Scan labels with physical scanner guns or type references.
- Flags duplicate scans, foreign branch labels, and missing labels with real-time feedback.
- One-click verify/unverify on line items.
- Exports styled Excel reports (.xlsx) and printable sign-off PDF audit reports.
- Integrates seamlessly with Odoo 17, Product Labels App, and em_jewellery_management.
    """,
    'author': 'Antigravity',
    'depends': [
        'base',
        'stock',
        'product',
        'multi_branch_base',
        'em_jewellery_management',
        'ornament_label',
        'custom_label_user',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'report/report_actions.xml',
        'report/label_verification_report_template.xml',
        'views/branch_label_verification_views.xml',
        'views/branch_label_checker_views.xml',
        'views/product_label_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'branch_label_verification/static/src/css/branch_barcode_scanner.css',
            'branch_label_verification/static/src/xml/branch_barcode_scanner.xml',
            'branch_label_verification/static/src/js/branch_barcode_scanner.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
