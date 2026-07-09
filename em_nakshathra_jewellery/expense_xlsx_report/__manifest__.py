{
    'name': 'Expense Excel Report',
    'version': '17.0.1.0.0',
    'category': 'Accounting/Reporting',
    'summary': 'Generate an Excel report for expenses',
    'depends': ['account', 'purchase', 'report_xlsx', 'multi_branch_base'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/expense_report_wizard_view.xml',
        'views/expense_report_pivot_view.xml',
        'report/report_action.xml',
    ],
    'installable': True,
    'application': False,
}
