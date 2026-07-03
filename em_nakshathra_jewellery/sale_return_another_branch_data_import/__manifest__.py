{
    'name': 'Sale Return Another Branch Import',
    'version': '17.0.1.0.0',
    'category': 'Sales',
    'summary': 'Data migration script for another branch sale return import from Excel',
    'description': '''
        Imports Excel data (TWO sheets):
        - Sheet "OTHER SHOP SR": Sale Return lines → sale.return.line (product, purity, weights, rate, amount)
        - Sheet "SALES": Sale Order header + lines + payments
        Workflow per voucher:
        1. Create/find customer & salesman
        2. Create Sale Order with header from SALES sheet
        3. Add sale order lines (products, labels, purity, MC, gold rate, taxes)
        4. Add sale return lines from SR sheet
        5. Apply gold scheme if present
        6. Confirm sale order
        7. Validate stock delivery
        8. Apply sale return (creates PO + vendor bill for return goods)
        9. Create invoice → post
        10. Register payments (Bank, UPI, Card, Cash)
    ''',
    'author': 'EM Nakshathra',
    'depends': ['base', 'sale_management', 'account', 'stock', 'em_jewellery_management', 'multi_branch_base'],
    'data': [],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
