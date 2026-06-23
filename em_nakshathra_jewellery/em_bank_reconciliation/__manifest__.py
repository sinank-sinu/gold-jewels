{
    "name": "Bank Reconciliation Customizations",
    "version": "17.0.1.0.0",
    "category": "Accounting",
    "summary": "Add bank reference for reconciliation matching",
    "depends": ["account", "om_account_accountant", "account_statement_base", "base_accounting_kit"],
    "data": [
        "views/account_bank_statement_line_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
