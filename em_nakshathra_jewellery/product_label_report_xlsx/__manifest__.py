{
    "name": "Product Label Excel Report",
    "version": "17.0.1.0.0",
    "category": "Jewellery",
    "summary": "Product Label XLSX Report with filters by branch and date",
    "depends": [
        "purchase",
        "em_jewellery_management",
        "old_gold_xlsx_report"
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/product_label_report_wizard_view.xml",
        "views/menu.xml",
        "views/product_template_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
