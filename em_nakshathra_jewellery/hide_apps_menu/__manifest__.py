{
    'name': 'Hide Apps Menu',
    'version': '17.0.1.0.0',
    'category': 'Administration',
    'summary': 'Hides the main Apps menu by default',
    'description': """
        This module creates a new security group 'Show Apps Menu' and assigns the base Apps menu to it. 
        This completely hides the Apps menu for all users until they are explicitly added to this new group.
    """,
    'depends': ['base'],
    'data': [
        'security/security.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
