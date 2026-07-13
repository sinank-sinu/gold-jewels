{
    'name': 'eSSL Attendance Integration',
    'version': '17.0.1.0.0',
    'category': 'Human Resources/Attendance',
    'summary': 'Fetch Attendance from eSSL API daily via Cron',
    'description': """
        This module integrates with the eSSL API to fetch attendance records.
        It runs a cron job daily at 12 AM to pull records, matches the employee code,
        and creates standard Odoo hr.attendance records.
    """,
    'author': 'Antigravity',
    'depends': ['hr_attendance'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/hr_employee_views.xml',
        'views/essl_location_views.xml',
        'views/hr_attendance_views.xml',
        'wizard/essl_sync_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
