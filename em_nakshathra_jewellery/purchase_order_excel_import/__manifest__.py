# -*- coding: utf-8 -*-

{
    "name": "Purchase Order Excel Import",
    "version": "17.0.1.0.0",
    "category": "Purchases",
    "summary": "Import Purchase Orders from Excel",
    "description": """
Purchase Order Excel Import

Features
--------
* Import Purchase Orders from Excel
* Automatically groups rows by Order Reference
* Creates Purchase Orders
* Creates Purchase Order Lines
* Supports custom jewellery fields
* Validates mandatory columns
* Searches Vendor, Buyer, Branch, Product, Purity, Taxes and UOM
    """,
    "author": "OpenAI",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "purchase",
        "stock",
        "product",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/purchase_order_import_view.xml",
        # "views/purchase_import_menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}