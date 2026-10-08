{
    "name": "Purchase / Job Work Label Summary",
    "version": "17.0.1.0.0",
    "category": "Inventory",
    "summary": "Purchase & Job Work Label Summary Report",
    "author": "Custom",
    "depends": [
        "purchase",
        "stock",
        "product",
        "purchase",
        "em_jewellery_management",
        "old_gold_xlsx_report",
        "custom_label_user",
        "ornament_label"
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/label_summary_wizard_view.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}