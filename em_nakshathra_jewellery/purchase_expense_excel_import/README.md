# Purchase Expense Excel Import

Install this addon, then open **Invoicing → Vendors → Import Purchase Expenses**.

Upload an `.xlsx` workbook with one expense line per row and these column
headers:

| Column | Required | Meaning |
| --- | --- | --- |
| Vendor | Yes | Exact name of an existing supplier. If no supplier exists, one is created for the selected company. |
| Bill Reference | Yes | Vendor bill reference; rows for the same vendor/reference are grouped |
| Product | Yes | Exact product name or internal reference |
| Company | Yes | Company name; must match the company selected in the import wizard |
| Branch | Yes | Branch name belonging to the company |
| Narration | No | Added to the Purchase Order narration; distinct row narrations for a grouped bill are combined |
| Quantity | Yes | Expense quantity |
| Unit Price | Yes | Price per unit before taxes |
| Bill Date | No | Invoice date; defaults to today |
| Tax | No | Exact purchase tax name; separate multiple taxes with `|` |
| Subtotal | No | Optional per-line untaxed subtotal used as a validation check |

Each workbook must contain one company and one branch. Company and branch names
are matched case-insensitively with repeated whitespace ignored; the branch must
belong to the workbook company. Select that company in the wizard and select an
outbound Bank or Cash journal belonging to the workbook branch.

Rows with the same vendor and bill reference create one confirmed Purchase
Expense order with its Purchase Expense flag enabled. The Excel Bill Date is
used for the Purchase Order, its incoming receipt schedule and completion date,
and the vendor bill date. The imported branch is assigned to the order, its
incoming receipt, the generated vendor bill, and the payment. The importer
creates the vendor bill from that order, posts it, and registers a payment dated
with the Excel Bill Date through Odoo's payment workflow. Odoo calculates bill
totals, taxes, and subtotals.
Existing bills and Purchase Expense orders with the same vendor and reference
are rejected to prevent duplicate imports.
After a successful import, the wizard stays open and displays the created
Purchase Orders, with an option to open them in the Purchase Orders list.

Purchase Expense orders accept Consumable and Service products only. If the
company requires a second purchase-order approval, a purchase manager must
approve the order before the importer can generate and pay its bill.
For Consumable products whose control policy uses stock receipts, the importer
validates the PO's incoming receipt before creating the bill. This does not
change the product's global purchase control policy.

Imports made by an Odoo administrator, accounting administrator, or jewellery
manager mark the created bills approved before posting. Other users remain
subject to the vendor-bill manager approval rule.

Product lookup checks purchasable products belonging to the workbook company
first, then falls back to shared products with no company assigned. Product-name
matching ignores leading/trailing and repeated spaces and is case-insensitive.
If multiple products match, set a unique Internal Reference on the intended
product and put that reference in the Product column, or archive the duplicate.

If a vendor name does not match an existing supplier, the importer reuses and
marks a unique matching contact as a supplier, or creates a new company-scoped
supplier containing the name from the workbook. If multiple contacts have the
same name, the import stops so the duplicate can be resolved instead of choosing
the wrong vendor.
