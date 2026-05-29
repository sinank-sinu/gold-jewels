# -*- coding: utf-8 -*-
{
    'name': 'Jewelry DMS Extension',
    'version': '17.0.1.0.0',
    'summary': 'Tracks Start and Expiry dates for Jewelry DMS with Automated Alerts.',
    'category': 'Document Management',
    'depends': ['base', 'mail', 'document_management_system'], 
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        # 'views/category_views.xml',
        'views/document_views.xml',
        'views/document_document_views.xml',
        'wizard/document_renew_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}