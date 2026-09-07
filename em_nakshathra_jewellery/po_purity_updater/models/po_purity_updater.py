# -*- coding: utf-8 -*-
import io
import logging
import re

from odoo import models, api
from odoo.exceptions import UserError

try:
    import openpyxl
except ImportError:
    openpyxl = None

_logger = logging.getLogger(__name__)


class PoPurityUpdater(models.AbstractModel):
    """Reads the 'OG' sheet of the uploaded excel and updates purity on the
    matching purchase.order.line(s).

    ============================================================
    CONFIG -- adjust these to match YOUR Odoo fields / sheet columns
    ============================================================
    """
    _name = 'po.purity.updater'
    _description = 'Update PO line purity from OG excel sheet'

    # --- excel column names (must match the header row exactly) ---
    # NOTE: the sheet is no longer looked up by a fixed name (e.g. 'OG') because
    # different uploads may call it 'OG', 'Sheet1', etc. Instead we scan every
    # sheet in the workbook and use whichever one contains all the required
    # columns in its header row.
    COL_SALES_VOUCHER = 'Sales Voucher no'     # used to find the Sale Order
    COL_PURCHASE_VOUCHER = 'Purchase Voucher No'  # kept as a fallback lookup only
    COL_GROSS_WT = 'Gross Wt'
    COL_CARAT = 'Carat'          # e.g. "22CT(91.6)"  or  "18KTD(75)"

    # --- sale.order: field used to look up the sales voucher number ---
    # This maps to the "Source Document" field shown on the SO's Other Info
    # tab (Tracking section), e.g. holding "SYT/5380". Leave as-is; if it's
    # wrong the script auto-detects the real field by its on-screen label.
    SO_VOUCHER_FIELD = 'origin'
    SO_VOUCHER_FIELD_LABEL = 'Source Document'

    # --- sale.order: many2one field pointing DIRECTLY to its Purchase Order ---
    # This is the "Source Purchase Order" field visible on the SO form
    # (e.g. showing "VTY/P15283"). Same auto-detect fallback applies.
    SO_TO_PO_FIELD = 'source_purchase_order_id'
    SO_TO_PO_FIELD_LABEL = 'Source Purchase Order'

    # fallback only, used if the SO -> PO traversal above finds nothing:
    # a reverse many2one on purchase.order pointing back to the sale.order
    PO_SALE_ORDER_FIELD = 'x_sale_order_id'

    # fallback only: field used if neither of the above finds anything
    PO_VOUCHER_FIELD = 'partner_ref'

    # --- purchase.order.line: fields to read/write ---
    # These are auto-detected by on-screen label at runtime (like the SO/PO
    # fields above), because "Purity" is a Many2one to a purity master here,
    # not a plain number - the configured names below are just seed guesses.
    LINE_GROSS_WT_FIELD = 'gross_weight'
    LINE_GROSS_WT_FIELD_LABEL = 'Gross Weight'
    LINE_PURITY_FIELD = 'purity_id'
    LINE_PURITY_FIELD_LABEL = 'Purity'

    # --- sale.order: many2one field pointing to the related Vendor Bill ---
    # This is the "Old Gold Vendor Bill" field visible on the SO form
    # (e.g. showing "BILL5/2026/09/0826"). Auto-detected by label like the rest.
    SO_TO_BILL_FIELD = 'old_gold_vendor_bill_id'
    SO_TO_BILL_FIELD_LABEL = 'Old Gold Vendor Bill'

    # --- account.move.line (vendor bill line): fields to read/write ---
    # Bill lines don't show a separate "Gross Weight" column in this DB - the
    # "Quantity" column lines up with the PO line's gross weight instead, so
    # that's what's used to pick the right line when a bill has several.
    BILL_LINE_QTY_FIELD = 'quantity'
    BILL_LINE_QTY_FIELD_LABEL = 'Quantity'
    BILL_LINE_PURITY_FIELD = 'purity_id'
    BILL_LINE_PURITY_FIELD_LABEL = 'Purity'

    # allowed difference (in same unit as Gross Wt) when matching a line
    GROSS_WT_TOLERANCE = 0.01
    # ============================================================

    @api.model
    def _parse_purity(self, carat_raw):
        """'22CT(91.6)' -> 91.6 ; '18KTD(75)' -> 75.0 ; '21 KT OLD GOLD' -> False (no number in parens)"""
        if carat_raw is None:
            return False
        text = str(carat_raw).strip()
        m = re.search(r'\(([\d.]+)\)', text)
        if m:
            return float(m.group(1))
        m = re.search(r'([\d.]+)', text)
        return float(m.group(1)) if m else False

    @api.model
    def _find_data_sheet(self, wb, max_header_scan_rows=5):
        """Scan every sheet (and the first few rows of each, in case the
        header isn't row 1) for one containing all required columns.
        Returns (worksheet, header_list, header_row_index) or (None, None, None).
        header_row_index is 0-based: the number of rows consumed up to and
        including the header row.
        """
        required = (self.COL_SALES_VOUCHER, self.COL_PURCHASE_VOUCHER, self.COL_GROSS_WT, self.COL_CARAT)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            for row_idx, row in enumerate(
                    ws.iter_rows(min_row=1, max_row=max_header_scan_rows, values_only=True), start=1):
                header = [str(h).strip() if h else '' for h in row]
                if all(col in header for col in required):
                    return ws, header, row_idx
        return None, None, None

    @api.model
    def _model_has_field(self, model_name, field_name):
        """Safely check a field exists before using it in a domain/getattr,
        so a wrong/placeholder config value is skipped instead of crashing
        the whole upload."""
        if not field_name:
            return False
        return field_name in self.env[model_name]._fields

    @api.model
    def _autodetect_field(self, model_name, label, ttype=None, comodel_name=None):
        """Find the technical field name on `model_name` whose on-screen
        label matches `label` (case-insensitive), optionally restricted to
        a field type / related model. Lets the script work without knowing
        the real technical name of a custom field."""
        domain = [('model', '=', model_name), ('field_description', '=ilike', label)]
        if ttype:
            domain.append(('ttype', '=', ttype))
        if comodel_name:
            domain.append(('relation', '=', comodel_name))
        fld = self.env['ir.model.fields'].sudo().search(domain, limit=1)
        return fld.name if fld else False

    @api.model
    def _resolve_field(self, model_name, configured_field, label, ttype=None, comodel_name=None):
        """Use the configured field name if it actually exists on the model;
        otherwise fall back to auto-detecting it by its on-screen label."""
        if self._model_has_field(model_name, configured_field):
            return configured_field
        return self._autodetect_field(model_name, label, ttype=ttype, comodel_name=comodel_name)

    @api.model
    def _find_sale_order(self, sales_voucher_no, so_voucher_field):
        Sale = self.env['sale.order']
        if not sales_voucher_no:
            return Sale
        so = Sale
        if self._model_has_field('sale.order', so_voucher_field):
            so = Sale.search([(so_voucher_field, '=', sales_voucher_no)], limit=1)
        if not so and self._model_has_field('sale.order', 'client_order_ref'):
            # fallbacks in case Source Document isn't populated for some records
            so = Sale.search([('client_order_ref', '=', sales_voucher_no)], limit=1)
        if not so:
            so = Sale.search([('name', '=', sales_voucher_no)], limit=1)
        return so

    @api.model
    def _find_order(self, sales_voucher_no, purchase_voucher_no, fields):
        Purchase = self.env['purchase.order']
        Sale = self.env['sale.order']
        so_voucher_field = fields['so_voucher_field']
        so_to_po_field = fields['so_to_po_field']
        po_sale_order_field = fields['po_sale_order_field']

        # 1) primary path: Sale Order (matched by "Source Document") ->
        #    read its "Source Purchase Order" many2one directly.
        so = self._find_sale_order(sales_voucher_no, so_voucher_field)
        if so:
            po = False
            if self._model_has_field('sale.order', so_to_po_field):
                po = getattr(so, so_to_po_field, False)
            if po:
                return po, so
            # 1b) fallback: relation stored the other way round (PO -> SO)
            if self._model_has_field('purchase.order', po_sale_order_field):
                order = Purchase.search([(po_sale_order_field, '=', so.id)], limit=1)
                if order:
                    return order, so

        # 2) fallback: try matching the Purchase Voucher No directly against
        #    a field on purchase.order (old behaviour, kept as a safety net).
        if purchase_voucher_no and self._model_has_field('purchase.order', self.PO_VOUCHER_FIELD):
            order = Purchase.search(
                [(self.PO_VOUCHER_FIELD, '=', purchase_voucher_no)], limit=1)
            if not order:
                order = Purchase.search([('name', '=', purchase_voucher_no)], limit=1)
            if order:
                return order, so or Sale
        elif purchase_voucher_no:
            order = Purchase.search([('name', '=', purchase_voucher_no)], limit=1)
            if order:
                return order, so or Sale

        return Purchase, so or Sale

    @api.model
    def _match_line(self, lines, target_value, field_name, target_purity=None):
        """Pick the line in `lines` (any recordset - PO lines or bill lines)
        whose `field_name` value (or fallback quantity/weight) is closest to
        `target_value`, within GROSS_WT_TOLERANCE.
        If there's only one line, return it regardless.
        If no line matches by weight and `target_purity` is provided, fall back
        to matching by the purity name mentioned in line.name (needed when
        multiple old-gold items were consolidated into a single PO line)."""
        empty = lines.browse([]) if lines is not False else lines
        if not lines:
            return empty
        if len(lines) == 1:
            return lines
        if target_value in (None, False) and not target_purity:
            return empty

        # Pass 1: Weight matching with fallback to product_qty / quantity
        best_line = empty
        best_diff = None
        if target_value not in (None, False):
            try:
                target_wt = float(target_value)
            except (ValueError, TypeError):
                target_wt = None

            if target_wt is not None:
                for line in lines:
                    val = getattr(line, field_name, False) if field_name and hasattr(line, field_name) else False
                    if val in (None, False) or (isinstance(val, (int, float)) and float(val) == 0.0):
                        for alt in ('product_qty', 'product_uom_qty', 'quantity', 'gross_weight'):
                            if hasattr(line, alt):
                                alt_val = getattr(line, alt, False)
                                if alt_val not in (None, False):
                                    try:
                                        if float(alt_val) != 0.0:
                                            val = alt_val
                                            break
                                    except (ValueError, TypeError):
                                        pass
                    if val in (None, False):
                        continue
                    try:
                        diff = abs(float(val) - target_wt)
                    except (ValueError, TypeError):
                        continue
                    if diff <= self.GROSS_WT_TOLERANCE and (best_diff is None or diff < best_diff):
                        best_diff = diff
                        best_line = line

        if best_line:
            return best_line

        # Pass 2: Fallback to purity in line description (consolidated old-gold lines)
        if target_purity not in (None, False):
            try:
                p_num = float(target_purity)
                candidates = [('%f' % p_num).rstrip('0').rstrip('.'), '%.2f' % p_num]
                if p_num.is_integer():
                    candidates.append(str(int(p_num)))
                candidates = list(dict.fromkeys(candidates))

                for line in lines:
                    lname = getattr(line, 'name', '') or ''
                    for c in candidates:
                        if f'({c}' in lname or f'({c})' in lname or f'{c})' in lname or f' {c}' in lname or f'{c}%' in lname:
                            return line
            except (ValueError, TypeError):
                pass

        return empty

    @api.model
    def get_diagnostics(self):
        """Lightweight check: resolve the sale.order -> purchase.order fields
        and report exactly what was found, without processing any excel file.
        Useful to verify the module upgraded correctly and the field
        auto-detection is working before running a full upload."""
        so_voucher_field = self._resolve_field(
            'sale.order', self.SO_VOUCHER_FIELD, self.SO_VOUCHER_FIELD_LABEL)
        so_to_po_field = self._resolve_field(
            'sale.order', self.SO_TO_PO_FIELD, self.SO_TO_PO_FIELD_LABEL,
            ttype='many2one', comodel_name='purchase.order')
        po_sale_order_field = self._resolve_field(
            'purchase.order', self.PO_SALE_ORDER_FIELD, 'Sale Order',
            ttype='many2one', comodel_name='sale.order')
        line_gross_wt_field = self._resolve_field(
            'purchase.order.line', self.LINE_GROSS_WT_FIELD, self.LINE_GROSS_WT_FIELD_LABEL)
        line_purity_field = self._resolve_field(
            'purchase.order.line', self.LINE_PURITY_FIELD, self.LINE_PURITY_FIELD_LABEL)
        so_to_bill_field = self._resolve_field(
            'sale.order', self.SO_TO_BILL_FIELD, self.SO_TO_BILL_FIELD_LABEL,
            ttype='many2one', comodel_name='account.move')
        bill_line_qty_field = self._resolve_field(
            'account.move.line', self.BILL_LINE_QTY_FIELD, self.BILL_LINE_QTY_FIELD_LABEL)
        bill_line_purity_field = self._resolve_field(
            'account.move.line', self.BILL_LINE_PURITY_FIELD, self.BILL_LINE_PURITY_FIELD_LABEL)

        purity_field_type = False
        purity_comodel = False
        if line_purity_field and line_purity_field in self.env['purchase.order.line']._fields:
            f = self.env['purchase.order.line']._fields[line_purity_field]
            purity_field_type = f.type
            purity_comodel = f.comodel_name if f.type == 'many2one' else False

        bill_purity_field_type = False
        bill_purity_comodel = False
        if bill_line_purity_field and bill_line_purity_field in self.env['account.move.line']._fields:
            f = self.env['account.move.line']._fields[bill_line_purity_field]
            bill_purity_field_type = f.type
            bill_purity_comodel = f.comodel_name if f.type == 'many2one' else False

        # also list every many2one on sale.order pointing to purchase.order,
        # and vice versa, so you can see all candidates even if auto-detect
        # picked the wrong one
        so_to_po_candidates = self.env['ir.model.fields'].sudo().search([
            ('model', '=', 'sale.order'), ('ttype', '=', 'many2one'),
            ('relation', '=', 'purchase.order'),
        ]).mapped(lambda f: '%s (%s)' % (f.name, f.field_description))
        po_to_so_candidates = self.env['ir.model.fields'].sudo().search([
            ('model', '=', 'purchase.order'), ('ttype', '=', 'many2one'),
            ('relation', '=', 'sale.order'),
        ]).mapped(lambda f: '%s (%s)' % (f.name, f.field_description))

        return {
            'so_voucher_field': so_voucher_field,
            'so_to_po_field': so_to_po_field,
            'po_sale_order_field': po_sale_order_field,
            'line_gross_wt_field': line_gross_wt_field,
            'line_purity_field': line_purity_field,
            'purity_field_type': purity_field_type,
            'purity_comodel': purity_comodel,
            'so_to_bill_field': so_to_bill_field,
            'bill_line_qty_field': bill_line_qty_field,
            'bill_line_purity_field': bill_line_purity_field,
            'bill_purity_field_type': bill_purity_field_type,
            'bill_purity_comodel': bill_purity_comodel,
            'so_to_po_candidates': so_to_po_candidates,
            'po_to_so_candidates': po_to_so_candidates,
        }

    @api.model
    def _resolve_purity_write_value(self, line, purity_field, purity_number):
        """Return (value_to_write, note) for writing purity onto `line`.
        Handles both a plain numeric field and a Many2one to a purity master
        (matches an existing record by name/value; never creates one).
        Raises ValueError with a clear message if it can't be resolved."""
        if purity_number in (None, False):
            raise ValueError("could not parse a purity number from the Carat column")

        field_obj = line._fields.get(purity_field)
        if field_obj is None:
            raise ValueError("field '%s' does not exist on purchase.order.line" % purity_field)

        if field_obj.type in ('float', 'integer', 'monetary'):
            return purity_number, None

        if field_obj.type == 'many2one':
            comodel = field_obj.comodel_name
            Model = self.env[comodel].sudo()
            # build the likely display strings for this purity, e.g. 91.6 -> "91.6", "91.60", "92"
            candidates = []
            if float(purity_number).is_integer():
                candidates.append(str(int(purity_number)))
            candidates.append(str(purity_number))
            candidates.append('%.2f' % purity_number)

            rec = Model.browse()
            # 1. Exact match on name
            for val in candidates:
                rec = Model.search([('name', '=', val)], limit=1)
                if rec:
                    break
            if not rec:
                # 2. Try common numeric field names on the purity master (exact and float tolerance)
                for fname in ('value', 'purity', 'percentage', 'karat_value'):
                    if fname in Model._fields:
                        rec = Model.search([(fname, '=', purity_number)], limit=1)
                        if not rec and hasattr(Model._fields[fname], 'type') and Model._fields[fname].type in ('float', 'integer'):
                            rec = Model.search([
                                (fname, '>=', purity_number - 0.1),
                                (fname, '<=', purity_number + 0.1)
                            ], limit=1)
                        if rec:
                            break
            if not rec:
                # 3. Try substring / ilike match on name, e.g. "21CT(87.5)" matching "87.5"
                for val in candidates:
                    rec = Model.search([('name', 'ilike', f'%({val})%')], limit=1)
                    if not rec:
                        rec = Model.search([('name', 'ilike', f'%{val}%')], limit=1)
                    if rec:
                        break
            if not rec:
                raise ValueError(
                    "no matching '%s' record found for purity %s (tried: %s)"
                    % (comodel, purity_number, ', '.join(candidates)))
            return rec.id, None

        raise ValueError("field '%s' has unsupported type '%s'" % (purity_field, field_obj.type))

    @api.model
    def _log_update(self, target, status, sales_voucher_no=False, purchase_voucher_no=False,
                     row_number=False, purity_value=False, message=False,
                     purchase_order=None, purchase_order_line=None,
                     vendor_bill=None, vendor_bill_line=None):
        """Persist one audit-log row for a single purity-update attempt
        (success or failure), so every upload leaves a permanent trail
        that's browsable in Odoo (Purchases > Purity Update Log), not just
        the transient result web page or the server log file.

        Runs inside its own SQL savepoint: if the insert itself fails (bad
        value, constraint, etc.) only this savepoint is rolled back, so the
        rest of the upload - and the whole HTTP request's DB transaction -
        keeps working instead of getting poisoned (InFailedSqlTransaction)."""
        vals = {
            'target': target,
            'status': status,
            'sales_voucher_no': sales_voucher_no or False,
            'purchase_voucher_no': purchase_voucher_no or False,
            'row_number': row_number or False,
            'purity_value': purity_value or 0.0,
            'message': message or False,
        }
        if purchase_order:
            vals['purchase_order_id'] = purchase_order.id
        if purchase_order_line:
            vals['purchase_order_line_id'] = purchase_order_line.id
        if vendor_bill:
            vals['vendor_bill_id'] = vendor_bill.id
        if vendor_bill_line:
            vals['vendor_bill_line_id'] = vendor_bill_line.id
        try:
            with self.env.cr.savepoint():
                self.env['po.purity.update.log'].sudo().create(vals)
        except Exception:
            # logging must never break the actual update run or poison
            # the transaction for the rows/queries that come after it
            _logger.exception("Row %s: failed to write audit log entry", row_number)

    @api.model
    def process_excel(self, file_bytes):
        """Entry point called by the controller. Returns a summary dict."""
        if not openpyxl:
            raise UserError("The 'openpyxl' python library is not installed on the server "
                             "(pip install openpyxl).")

        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        except Exception as e:
            raise UserError("Could not read the excel file: %s" % e)

        ws, header, header_row_num = self._find_data_sheet(wb)
        if ws is None:
            raise UserError(
                "Could not find a sheet containing the columns %s / %s / %s / %s. "
                "Sheets found: %s"
                % (self.COL_SALES_VOUCHER, self.COL_PURCHASE_VOUCHER, self.COL_GROSS_WT, self.COL_CARAT,
                   ', '.join(wb.sheetnames)))

        # Resolve the sale.order -> purchase.order fields once per run,
        # auto-detecting by on-screen label if the configured technical
        # name doesn't actually exist on this database.
        so_voucher_field = self._resolve_field(
            'sale.order', self.SO_VOUCHER_FIELD, self.SO_VOUCHER_FIELD_LABEL)
        so_to_po_field = self._resolve_field(
            'sale.order', self.SO_TO_PO_FIELD, self.SO_TO_PO_FIELD_LABEL,
            ttype='many2one', comodel_name='purchase.order')
        po_sale_order_field = self._resolve_field(
            'purchase.order', self.PO_SALE_ORDER_FIELD, 'Sale Order',
            ttype='many2one', comodel_name='sale.order')
        line_gross_wt_field = self._resolve_field(
            'purchase.order.line', self.LINE_GROSS_WT_FIELD, self.LINE_GROSS_WT_FIELD_LABEL)
        line_purity_field = self._resolve_field(
            'purchase.order.line', self.LINE_PURITY_FIELD, self.LINE_PURITY_FIELD_LABEL)
        so_to_bill_field = self._resolve_field(
            'sale.order', self.SO_TO_BILL_FIELD, self.SO_TO_BILL_FIELD_LABEL,
            ttype='many2one', comodel_name='account.move')
        bill_line_qty_field = self._resolve_field(
            'account.move.line', self.BILL_LINE_QTY_FIELD, self.BILL_LINE_QTY_FIELD_LABEL)
        bill_line_purity_field = self._resolve_field(
            'account.move.line', self.BILL_LINE_PURITY_FIELD, self.BILL_LINE_PURITY_FIELD_LABEL)
        resolved_fields = {
            'so_voucher_field': so_voucher_field,
            'so_to_po_field': so_to_po_field,
            'po_sale_order_field': po_sale_order_field,
            'line_gross_wt_field': line_gross_wt_field,
            'line_purity_field': line_purity_field,
            'so_to_bill_field': so_to_bill_field,
            'bill_line_qty_field': bill_line_qty_field,
            'bill_line_purity_field': bill_line_purity_field,
        }

        rows = list(ws.iter_rows(values_only=True))[header_row_num:]

        idx_sales_voucher = header.index(self.COL_SALES_VOUCHER)
        idx_voucher = header.index(self.COL_PURCHASE_VOUCHER)
        idx_gross = header.index(self.COL_GROSS_WT)
        idx_carat = header.index(self.COL_CARAT)

        updated, not_found, no_line_match, errors = [], [], [], []
        bill_updated, bill_not_found, bill_no_line_match, bill_errors = [], [], [], []
        # consolidated, sale-voucher-centric list of every row whose purity
        # was NOT updated on the PO line, with a plain-English reason -
        # this is what should be shown to the user as "not updated" list.
        not_updated = []

        # Commit progress periodically instead of holding one huge
        # transaction open for the whole file. On a big upload a single
        # long-running transaction is exactly what tends to get killed by
        # a DB idle/statement timeout or a proxy/worker timeout - and once
        # the connection is actually closed (not just the transaction
        # aborted), nothing already processed can be saved and every
        # further query fails with "cursor already closed". Committing
        # every COMMIT_EVERY rows keeps each transaction short and makes
        # sure earlier rows' updates + log entries survive even if a later
        # row triggers a fatal connection problem.
        COMMIT_EVERY = 50
        processed_rows = 0

        for row_num, row in enumerate(rows, start=header_row_num + 1):
            if row is None or all(v is None for v in row):
                continue

            sales_voucher_no = row[idx_sales_voucher] if idx_sales_voucher < len(row) else None
            voucher_no = row[idx_voucher] if idx_voucher < len(row) else None
            gross_wt = row[idx_gross] if idx_gross < len(row) else None
            carat_raw = row[idx_carat] if idx_carat < len(row) else None

            if not sales_voucher_no and not voucher_no:
                continue

            processed_rows += 1
            if processed_rows % COMMIT_EVERY == 0:
                try:
                    self.env.cr.commit()
                    self.env.invalidate_all()
                except Exception:
                    # If the connection is already gone there's nothing left
                    # to commit or continue with - stop the loop cleanly
                    # instead of hammering a dead connection row after row.
                    _logger.exception(
                        "Row %s: periodic commit failed, stopping upload early", row_num)
                    break

            sales_voucher_no = str(sales_voucher_no).strip() if sales_voucher_no else False
            voucher_no = str(voucher_no).strip() if voucher_no else False
            purity = self._parse_purity(carat_raw)

            voucher_label = sales_voucher_no or voucher_no or '(blank)'

            try:
                order, so = self._find_order(sales_voucher_no, voucher_no, resolved_fields)
            except Exception as e:
                _logger.exception("Row %s: failed while locating order", row_num)
                errors.append((row_num, sales_voucher_no or voucher_no, "lookup error: %s" % e))
                not_updated.append((row_num, voucher_label, "lookup error: %s" % e))
                self._log_update('po_line', 'failed', sales_voucher_no, voucher_no, row_num,
                                  purity, "lookup error: %s" % e)
                continue

            if not order:
                not_found.append((row_num, sales_voucher_no or voucher_no))
                not_updated.append((row_num, voucher_label, "Purchase Order not found for this voucher"))
                self._log_update('po_line', 'failed', sales_voucher_no, voucher_no, row_num,
                                  purity, "Purchase Order not found for this voucher")
                continue

            try:
                line = self._match_line(order.order_line, gross_wt, line_gross_wt_field, target_purity=purity)
            except Exception as e:
                _logger.exception("Row %s: failed while matching line", row_num)
                errors.append((row_num, sales_voucher_no or voucher_no, "line match error: %s" % e))
                not_updated.append((row_num, voucher_label, "line match error: %s" % e))
                self._log_update('po_line', 'failed', sales_voucher_no, voucher_no, row_num,
                                  purity, "line match error: %s" % e, purchase_order=order)
                continue

            if not line:
                no_line_match.append((row_num, sales_voucher_no or voucher_no, gross_wt))
                not_updated.append(
                    (row_num, voucher_label, "No PO line matched Gross Wt %s" % gross_wt))
                self._log_update('po_line', 'failed', sales_voucher_no, voucher_no, row_num,
                                  purity, "No PO line matched Gross Wt %s" % gross_wt, purchase_order=order)
                continue

            try:
                with self.env.cr.savepoint():
                    write_value, _note = self._resolve_purity_write_value(line, line_purity_field, purity)
                    line.write({line_purity_field: write_value})
                    self._log_update('po_line', 'success', sales_voucher_no, voucher_no, row_num,
                                      purity, "Purity updated", purchase_order=order, purchase_order_line=line)
                updated.append((row_num, sales_voucher_no or voucher_no, order.id, line.id, purity))
                _logger.info("Row %s: updated PO %s line %s purity -> %s",
                             row_num, order.id, line.id, purity)
            except Exception as e:
                _logger.exception("Row %s: failed to update line %s", row_num, line.id)
                errors.append((row_num, sales_voucher_no or voucher_no, str(e)))
                not_updated.append((row_num, voucher_label, str(e)))
                self._log_update('po_line', 'failed', sales_voucher_no, voucher_no, row_num,
                                  purity, str(e), purchase_order=order, purchase_order_line=line)
                continue

            # --- also update the matching line on the related Vendor Bill ---
            try:
                with self.env.cr.savepoint():
                    bill = getattr(so, so_to_bill_field, False) if so and so_to_bill_field else False
                    if not bill:
                        bill = self.env['account.move'].browse()

                    bill_line = self.env['account.move.line'].browse()
                    if bill:
                        bill_lines = getattr(bill, 'invoice_line_ids', bill.browse([]))
                        bill_line = self._match_line(bill_lines, gross_wt, bill_line_qty_field, target_purity=purity)

                    if not bill:
                        bill_not_found.append((row_num, sales_voucher_no or voucher_no))
                        self._log_update('bill_line', 'failed', sales_voucher_no, voucher_no, row_num,
                                          purity, "Vendor Bill not found for this voucher",
                                          purchase_order=order, purchase_order_line=line)
                        continue

                    if not bill_line:
                        bill_no_line_match.append((row_num, sales_voucher_no or voucher_no, gross_wt))
                        self._log_update('bill_line', 'failed', sales_voucher_no, voucher_no, row_num,
                                          purity, "No Vendor Bill line matched Gross Wt %s" % gross_wt,
                                          purchase_order=order, purchase_order_line=line, vendor_bill=bill)
                        continue

                    bill_write_value, _note = self._resolve_purity_write_value(
                        bill_line, bill_line_purity_field, purity)
                    bill_line.write({bill_line_purity_field: bill_write_value})
                    self._log_update('bill_line', 'success', sales_voucher_no, voucher_no, row_num,
                                      purity, "Purity updated", purchase_order=order, purchase_order_line=line,
                                      vendor_bill=bill, vendor_bill_line=bill_line)
                bill_updated.append((row_num, sales_voucher_no or voucher_no, bill.id, bill_line.id, purity))
                _logger.info("Row %s: updated Vendor Bill %s line %s purity -> %s",
                             row_num, bill.id, bill_line.id, purity)
            except Exception as e:
                _logger.exception("Row %s: failed to update vendor bill line", row_num)
                bill_errors.append((row_num, sales_voucher_no or voucher_no, str(e)))
                self._log_update('bill_line', 'failed', sales_voucher_no, voucher_no, row_num,
                                  purity, str(e), purchase_order=order, purchase_order_line=line)

        # Final commit to ensure all remaining rows are saved and cache cleared
        try:
            self.env.cr.commit()
            self.env.invalidate_all()
        except Exception:
            _logger.exception("Final commit failed")

        return {
            'updated': updated,
            'not_found': not_found,
            'no_line_match': no_line_match,
            'errors': errors,
            'not_updated': not_updated,
            'bill_updated': bill_updated,
            'bill_not_found': bill_not_found,
            'bill_no_line_match': bill_no_line_match,
            'bill_errors': bill_errors,
            'resolved_fields': resolved_fields,
        }
