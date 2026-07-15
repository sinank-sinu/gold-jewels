{
    "name": "Account Stock Summary",
    "version": "17.0.1.0.0",
    "category": "Accounting",
    "summary": "Consolidated Stock Summary Report",
    "depends": ["account", "stock", "base", "em_jewellery_management"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/account_stock_summary_wizard_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
