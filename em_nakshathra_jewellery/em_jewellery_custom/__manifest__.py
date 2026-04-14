{
    'name': 'Jewellery Management Custom',
     "version": "17.0.1.0.0",
    'category': 'Technical/Technical',
    'sequence': 2,
    'summary': """module manage jewellery""",
    'description': 'module manage jewellerymodule manage jewellery custom',

    'depends': ['em_jewellery_management'],
    'data': [
        'views/res_partner_view.xml',
        'views/job_work.xml',
        'views/issue_voucher.xml',
        'views/receive_voucher.xml',
        'views/requisition.xml',
    ],

    'auto_install': False,
    'application': True,
    'installable': True,
}