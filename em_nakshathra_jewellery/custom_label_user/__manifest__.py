{
    "name": "Custom Label User",
    'version': '17.0.1.0.0',
    "category": "Tools",
    "summary": "Custom label for user",
    "depends": ["base", "hr", "product", "em_jewellery_management", "stock"],
    "data": [
        "security/security.xml",
        "security/product_label_groups.xml",
        "security/ir.model.access.csv",
        "security/product_label_security.xml",
        "views/product_label_views.xml",
        "views/location_wise_stock_views.xml",
        "views/jeweller_menu.xml",
        "views/hr_employee_views.xml",
    ],
    "installable": True,
    "auto_install": False
}
