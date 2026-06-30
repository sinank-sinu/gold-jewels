# -*- coding: utf-8 -*-
{
    'name': 'Activity Report',
    'version': '1.0.0',
    'category': 'Reporting',
    'summary': 'Activity Report with transaction counts',
    'description': """
        Activity Report Module
        ======================
        This module provides a wizard to generate activity reports with:
        - Date range selection (from/to date)
        - Branch selection (multiple branches)
        - User selection
        - Export to xlsx with counts for:
          * Number of transactions
          * Number of sale orders
          * Number of purchase orders
          * Number of vendor bills
          * Number of customer invoices
    """,
    'author': 'EM Nakshathra',
    'depends': ['base', 'sale', 'purchase', 'account', 'multi_branch_base'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/activity_report_wizard_views.xml',
        'views/activity_report_menu.xml',
        'views/account_payment_views.xml',
    ],
    'installable': True,
    'application': True,
}
