{
    'name': 'Job Work Revert',
    'version': '17.0.1.0.0',
    'summary': 'Adds a Revert button to Job Work to undo all related vouchers, stock moves and sequence numbers',
    'category': 'Jewellery',
    'author': 'Custom',
    'depends': [
        'em_jewellery_management',
    ],
    'data': [
        'views/job_work_revert.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
