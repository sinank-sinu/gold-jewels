{
    'name': 'Contact Customisation',
    'version': '1.0',
    'depends': ['base', 'contacts', 'report_xlsx'],
    'data': [
        'views/res_partner_views.xml',
        'reports/contact_xlsx.xml',
        'views/menu.xml',
    ],

    'auto_install': False,
    'application': False,
    'installable': True,
}

