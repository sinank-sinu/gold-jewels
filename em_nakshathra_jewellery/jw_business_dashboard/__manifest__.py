# -*- coding: utf-8 -*-
{
    'name': 'JW Business Dashboard',
    'version': '17.0.1.0.0',
    'summary': 'Comprehensive Business Dashboard for Sales, Purchase, Inventory, Products, Jewellery & Expenses',
    'description': '''
        A modern Odoo 17/19-style business dashboard featuring:
        - Sales KPIs & Monthly Trend (Line Chart)
        - Purchase Analytics (Bar Chart)
        - Inventory Valuation (Pie Chart)
        - Product Category Distribution (Doughnut Chart)
        - Jewellery Purity Breakdown (Pie Chart)
        - Expense Analysis (Bar & Line Charts)
        - Real-time data with date-range filters
    ''',
    'category': 'Reporting/Dashboard',
    'author': 'EM Nakshathra',
    'company': 'EM Nakshathra',
    'website': '',
    'depends': [
        'base',
        'web',
        'sale',
        'purchase',
        'stock',
        'product',
        'account',
        'hr_expense',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/jw_dashboard_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jw_business_dashboard/static/src/css/jw_dashboard.css',
            'jw_business_dashboard/static/src/js/jw_dashboard.js',
            'jw_business_dashboard/static/src/xml/jw_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
