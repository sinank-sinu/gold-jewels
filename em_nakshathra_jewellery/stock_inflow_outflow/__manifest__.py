# -*- coding: utf-8 -*-
{
    'name': 'Stock Inflow & Outflow',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Jewellery',
    'summary': 'Branch & Date-wise Stock Inflow / Outflow Dashboard with Vendor-Wise Label Tracking',
    'description': """
Stock Inflow & Outflow
======================

Dedicated standalone app for Jewellery Stock Inflow / Outflow analytics and Vendor-Wise Label reporting:

- Unified Branch & Date filtering (with multi-branch user access control & quick date presets)
- Tab 1: Stock Inflow & Outflow (Opening + Inflow - Outflow = Closing equation KPIs, movement category breakdown, Product-Wise Flow, Branch-Wise Summary, and Movement Ledger)
- Tab 2: Vendor-Wise Labels using the exact same Branch & Date filter setup (Movement In/Out, Created in Period, and Closing Stock modes with Gross/Stone/Diamond/Net/Fine weights and label drill-down)
- Styled multi-sheet Excel (.xlsx) export
    """,
    'author': 'Nakshathra Jewellery',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'stock',
        'purchase',
        'sale_stock',
        'multi_branch_base',
        'em_jewellery_management',
        'em_jewellery_customisation',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_inflow_outflow_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'stock_inflow_outflow/static/src/css/stock_inflow_outflow.css',
            'stock_inflow_outflow/static/src/js/stock_inflow_outflow.js',
            'stock_inflow_outflow/static/src/xml/stock_inflow_outflow.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
