# Purchase Expense Excel Import

Install this addon, then open **Invoicing → Vendors → Import Purchase Expenses**.

Upload an `.xlsx` workbook with one expense line per row and these column
headers:

| Column | Required | Meaning |
| --- | --- | --- |
| Vendor | Yes | Exact name of an existing supplier |
| Bill Reference | Yes | Vendor bill reference; rows for the same vendor/reference are grouped |
| Product | Yes | Exact product name or internal reference |
| Quantity | Yes | Expense quantity |
| Unit Price | Yes | Price per unit before taxes |
| Bill Date | No | Invoice date; defaults to today |
| Tax | No | Exact purchase tax name; separate multiple taxes with `|` |
| Subtotal | No | Optional per-line untaxed subtotal used as a validation check |

The selected bank journal must belong to the active company and have an
outbound payment method. The import posts each vendor bill and registers a
payment dated today through Odoo's payment workflow. Bill totals, tax, and
subtotals are calculated by Odoo. An existing bill with the same vendor and
reference is rejected to help prevent duplicate imports.
