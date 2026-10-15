# -*- coding: utf-8 -*-
{
    "name": "PO Label Tracker",
    "version": "17.0.1.0.0",
    "category": "Inventory",
    "summary": "Track Purchase Order labels, weights, locations, remaining unlabelled weights, and active status",
    "author": "Custom",
    "depends": [
        "base",
        "purchase",
        "stock",
        "product",
        "em_jewellery_management",
        "ornament_label",
        "custom_label_user",
        "em_jewellery_customisation",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/po_label_tracker_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": False,
}
