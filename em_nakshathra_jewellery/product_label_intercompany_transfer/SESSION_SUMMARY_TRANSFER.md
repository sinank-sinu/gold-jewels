# Inter-Company Product Label Transfer — Session Summary & Documentation

**Session Date**: November 4, 2026  
**Module**: `product_label_intercompany_transfer`  
**Databases**: `pro_5` & `pro_4`  
**Port**: `8019`  

---

## 1. Executive Summary

This session focused on finalizing and stabilizing the **Jewellery Inter-Company Product Label Transfer** workflow across sister concerns (`NAKSHATHRA GOLD AND DIAMOND LLP` and `NAKSHATHRA 916 GOLD AND DIAMONDS SILVER LLP`). The primary accomplishments include:
1. Resolving label creation crashes (`purchase_metal_value`).
2. Professionalizing the **Delivery Challan PDF Report** into a 1-page high-contrast luxury jewellery format.
3. Adding configurable **Sales & Purchase Tax** selectors with dynamic defaults on the Transfer form.
4. Aligning **Original Vendor** reporting across companies.
5. Fixing a critical **₹ 23,380.00 price mismatch** between the Source Sale Order and Destination Purchase Order, achieving exact paisa-level financial parity across all 4 documents (SO, Customer Invoice, PO, Vendor Bill).

---

## 2. Key Issues & Technical Solutions

### Issue 1: `KeyError: 'purchase_metal_value'` on Destination Label Creation
- **Root Cause**: An obsolete/invalid field `purchase_metal_value` was being passed during `product.label.create()`.
- **Solution**: Replaced with standard jewellery fields: `purchase_price_per_gram` (board rate) and `purchase_metal_rate` (`net_weight * board_rate`).

### Issue 2: Delivery Challan PDF Layout Overhaul
- **Requirement**: The Delivery Challan looked cluttered, spilled onto multiple pages, and had low-contrast table borders.
- **Solution**:
  - Re-designed the report using luxury jewellery executive formatting (`#0f172a` headers, crisp `#cbd5e1` cell borders).
  - Consolidated header into a clean side-by-side Consignor/Consignee box with statutory GSTIN, State code, and Transfer Challan metadata.
  - Formatted the item table with exact columns: `#`, `Label No`, `Barcode`, `Product`, `Purity`, `Gross (g)`, `Net (g)`, `Fine (g)`, `Rate/g (₹)`, `Taxable (₹)`.
  - Added a two-column summary section at the bottom (Left: GST Tax Breakup & Goods Condition Note; Right: Weight and Financial Totals).
  - Configured `@page` margins and padding to guarantee the document fits cleanly on a single page for standard transfers.

### Issue 3: Tax Selectors on Inter-Company Transfer Form
- **Requirement**: Users needed to view and select the appropriate GST rates for both Source (Sale) and Destination (Purchase) directly on the transfer form.
- **Solution**:
  - Added `sale_tax_id` (`account.tax` domain `[('type_tax_use', '=', 'sale')]`) and `purchase_tax_id` (`[('type_tax_use', '=', 'purchase')]`) fields on `label.intercompany.transfer`.
  - Implemented `@api.onchange('source_company_id', 'dest_company_id')` to dynamically default to 3% GST (Intra-state CGST+SGST or Inter-state IGST).
  - Updated transfer line computation and Delivery Challan report to compute taxes using the selected taxes.

### Issue 4: Vendor Name Preservation in Reports
- **Requirement**: Destination labels must preserve the original vendor name for accurate purchase/valuation reporting, rather than overwriting it with the transferring sister company name.
- **Solution**:
  - `_create_destination_labels` stores `orig_vendor = label.original_vendor_id or label.partner_id`.
  - `new_label.partner_id` and `new_label.original_vendor_id` are explicitly set and verified to match the original vendor.
  - Accounting documents (Purchase Order and Vendor Bill) properly reference the sister company partner for inter-company balance tracking.

### Issue 5: Purchase Order Amount Mismatch (₹ 130,109.28 vs ₹ 153,489.28)
- **Problem**: On Transfer `ICT/2026/00005`, the Source Sale Order (`HOM/S16901`) was ₹ 153,489.28, but the Destination Purchase Order (`HO/P01477`) was only ₹ 130,109.28 (diff: ₹ 23,380.00).
- **Root Cause**:
  1. *Inverted Fallback*: In `_create_destination_purchase_order` and `_create_destination_labels`, the code checked:
     `diamond_rate = l.purchase_diamond_rate or l.sale_diamond_rate or 0.0`.
     The source labels contained old historical purchase rates (₹ 500 and ₹ 29,120) from years ago, so the destination PO lines used those rates instead of the transfer rates (₹ 1,000 and ₹ 52,000).
  2. *Bullion Fine Weight Override*: In `purchase.order.line` (`em_jewellery_management`), setting `gold_rate` triggers `_compute_metal_amount = gold_rate * fine_weight` (pure gold bullion formula) instead of `net_weight * rate`.
  3. *Unit Price Rounding*: 2-decimal rounding caused minor paise discrepancies on division by gross weight.
- **Solution**:
  1. Updated `_create_destination_purchase_order` to accept `so=so` from the confirmed Sale Order.
  2. PO lines are now built directly from `so.order_line`, setting `price_unit = round(so_line.price_subtotal / gross_wt, 4)` and `taxes_id = purchase_taxes`.
  3. Left `gold_rate`, `metal_amount`, `stone_rate`, and `diamond_rate` unpopulated on the PO line so standard line pricing (`price_subtotal = price_unit * qty`) is used without fine-weight distortion.
  4. Corrected `_create_destination_labels` to assign `purchase_diamond_rate = label.sale_diamond_rate or label.purchase_diamond_rate or 0.0`.
  5. Retroactively updated `HO/P01477`, `BILL/2026/11/0006`, and destination labels `DMDL/44774` and `DMDNK/33226`.

---

## 3. Financial Parity Verification Table (`ICT/2026/00005`)

| Document / Entity | Record Reference | Untaxed Amount (₹) | 3% GST (₹) | Total (₹) | Status |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Inter-Company Transfer** | `ICT/2026/00005` | 153,489.28 | 4,604.68 | 158,093.96 | Transferred |
| **Sale Order (Source)** | `HOM/S16901` | 153,489.28 | 4,604.68 | 158,093.96 | Sale Order (Delivered) |
| **Customer Invoice (Source)** | `HOS/2026/00023` | 153,489.28 | 4,604.68 | 158,093.96 | Posted |
| **Purchase Order (Dest)** | `HO/P01477` | 153,489.28 | 4,604.68 | 158,093.96 | Purchase Order |
| **Vendor Bill (Dest)** | `BILL/2026/11/0006` | 153,489.28 | 4,604.68 | 158,093.96 | Posted |

---

## 4. Modified Source Code Files

1. `custom_addons/em_nakshathra/em_nakshathra_jewellery/product_label_intercompany_transfer/models/label_intercompany_transfer.py`
   - Added tax fields and dynamic defaults.
   - Enhanced `action_transfer` to pass `so` to `_create_destination_purchase_order`.
   - Updated PO line creation for exact SO price parity.
   - Fixed stone/diamond rate fallbacks in `_create_destination_labels`.
2. `custom_addons/em_nakshathra/em_nakshathra_jewellery/product_label_intercompany_transfer/views/label_intercompany_transfer_views.xml`
   - Added `sale_tax_id` and `purchase_tax_id` fields to the form view.
3. `custom_addons/em_nakshathra/em_nakshathra_jewellery/product_label_intercompany_transfer/report/intercompany_transfer_report.xml`
   - Complete visual revamp into 1-page luxury executive delivery challan.

---

## 5. Deployment Status

- **Module Upgrade**: Successfully upgraded on both `pro_5` and `pro_4` databases.
- **Server Status**: Running as daemon on `http://localhost:8019` (`werkzeug`).
- **Data Integrity**: Verified and committed to PostgreSQL database `pro_5`.

