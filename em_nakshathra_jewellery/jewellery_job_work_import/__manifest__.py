{
    "name": "Jewellery Job Work Import",
    "version": "17.0.1.0.0",
    "category": "",
    "summary": "Import Jewellery Job Work from Excel",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": [
        "base",
        "stock",
        "product",
        "uom",
        "em_jewellery_management",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/job_work_import_wizard_view.xml",
    ],
    "application": False,
    "installable": True,
    "auto_install": False,
}