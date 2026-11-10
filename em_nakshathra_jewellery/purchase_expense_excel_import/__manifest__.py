{
    "name": "Purchase Expense Excel Import",
    "version": "17.0.1.0.0",
    "category": "Accounting/Vendors",
    "summary": "Import and pay vendor expense bills from Excel",
    "description": """
Import purchase expenses from an Excel workbook with company and branch data.

Rows with the same vendor and bill reference are grouped into one vendor bill.
The importer posts each bill and registers its payment using a bank or cash
journal configured for the workbook branch. Taxes and subtotals are calculated
by Odoo from the imported lines.
    """,
    "license": "LGPL-3",
    "depends": [
        "account",
        "purchase",
        "purchase_stock",
        "em_jewellery_management",
        "multi_branch_base",
    ],
    "external_dependencies": {"python": ["openpyxl"]},
    "data": [
        "security/ir.model.access.csv",
        "views/purchase_expense_import_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
