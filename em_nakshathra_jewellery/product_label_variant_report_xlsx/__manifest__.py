{
    "name": "Product Label Variant & Vendor Excel Report",
    "version": "17.0.1.0.0",
    "category": "Jewellery",
    "summary": "Label Closing Stock Report with 6 Product Variants and Vendor Name",
    "depends": [
        "product_label_report_xlsx",
        "purchase",
        "em_jewellery_management",
        "old_gold_xlsx_report",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/res_users_views.xml",
        "wizard/product_label_variant_report_wizard_view.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
