{
    'name': 'Internal Transfer Script Import',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Stock',
    'summary': 'Import Internal Transfers from Excel for existing Product Labels',
    'depends': [
        'base',
        'stock',
        'product',
        'em_jewellery_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/inter_branch_transfer_import_wizard_view.xml',
    ],
    'installable': True,
    'application': False,
}
