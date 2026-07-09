{
    "name": "Non Labelled Ornament Report",
    "version": "17.0.1.0.0",
    "category": "Purchase",
    "summary": "Non Labelled Ornament XLSX Report",
    "depends": [
        "purchase",
        "em_jewellery_management",
        "old_gold_xlsx_report"
    ],
    'data': [
    'security/ir.model.access.csv',

    'wizard/non_labelled_report_wizard.xml',


    'views/menu.xml',
],
    "installable": True,
    "application": False,
}