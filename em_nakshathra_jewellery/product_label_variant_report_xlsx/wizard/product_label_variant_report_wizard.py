from io import BytesIO
import base64
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.worksheet.views import Selection
from odoo import models, fields, _
from odoo.exceptions import UserError

VARIANTS = ["Metal Colour", "Variety", "Type", "Design", "Stone Colour", "Size"]


def get_date_val(val):
    if not val:
        return False
    if isinstance(val, datetime):
        return val.date()
    elif isinstance(val, (fields.Date, fields.Datetime)):
        return fields.Date.to_date(val)
    return False


def set_cell(ws, row, col, val, align=None, num_format=None, font=None, border=None):
    cell = ws.cell(row=row, column=col, value=val)
    if align:
        cell.alignment = align
    if num_format:
        cell.number_format = num_format
    if font:
        cell.font = font
    if border:
        cell.border = border
    return cell


class ProductLabelVariantReportWizard(models.TransientModel):
    _name = "product.label.variant.report.wizard"
    _inherit = "product.label.report.wizard"
    _description = "Label Closing Stock Report (With Variants & Vendor)"

    def action_print_report(self):
        self.ensure_one()
        if not (
            self.env.user.has_group("product_label_variant_report_xlsx.group_product_label_variant_report")
            or self.env.user.has_group("em_jewellery_management.group_jewellery_manager")
            or self.env.user.has_group("em_jewellery_management.label_user_purchase")
        ):
            raise UserError(_("You are not authorized to access this report."))

        today = fields.Date.today()
        local_start_dt = fields.Datetime.context_timestamp(self, self.start_datetime)

        # 1. Fetch internal locations
        loc_domain = [('usage', '=', 'internal')]
        if self.branch_ids:
            loc_domain.append(('branch_id', 'in', self.branch_ids.ids))
        loc_ids = self.env['stock.location'].sudo().search(loc_domain).ids

        # 2. Stock moves after start_datetime
        moves_after = self.env['stock.move'].sudo().search([
            ('state', '=', 'done'), ('date', '>', self.start_datetime),
            '|', ('location_id', 'in', loc_ids), ('location_dest_id', 'in', loc_ids)
        ])
        quants = self.env['stock.quant'].sudo().search([
            ('location_id', 'in', loc_ids), ('quantity', '>', 0)
        ])
        # Match the standard closing stock report: include inactive labels and
        # determine whether each label was active at the report cutoff.
        candidates = self.env['product.label'].sudo().with_context(active_test=False).search([
            ('create_date', '<=', self.start_datetime),
        ])
        tracking_model = self.env['mail.tracking.value'].sudo()
        tracking_values = tracking_model.search([
            ('field_id.model', '=', 'product.label'),
            ('field_id.name', '=', 'active'),
            ('mail_message_id.model', '=', 'product.label'),
            ('mail_message_id.res_id', 'in', candidates.ids),
        ])
        tracking_values = tracking_values.sorted(
            key=lambda tracking: (
                tracking.mail_message_id.date or datetime.min,
                tracking.mail_message_id.id,
                tracking.id,
            )
        )
        active_at_cutoff = {}
        active_before_cutoff = {}
        for tracking in tracking_values:
            label_id = tracking.mail_message_id.res_id
            message_date = tracking.mail_message_id.date
            if message_date and message_date <= self.start_datetime:
                active_before_cutoff[label_id] = bool(tracking.new_value_integer)
            elif message_date:
                active_at_cutoff.setdefault(label_id, bool(tracking.old_value_integer))
        active_at_cutoff.update(active_before_cutoff)

        label_moves = self.env['stock.move'].sudo().search([
            ('label_id', 'in', candidates.ids), ('state', '=', 'done')
        ], order='date asc')

        first_move, last_move = {}, {}
        for m in label_moves:
            first_move.setdefault(m.label_id.id, m)
            if m.date <= self.start_datetime:
                last_move[m.label_id.id] = m

        labels, label_locations, label_branches = [], {}, {}
        for l in candidates:
            if not active_at_cutoff.get(l.id, l.active):
                continue
            lm, fm = last_move.get(l.id), first_move.get(l.id)
            loc = lm.location_dest_id if lm else (fm.location_id if fm else l.branch_location_id)
            branch = (loc.branch_id or lm.branch_id) if lm else ((loc.branch_id or fm.branch_id) if fm else (loc.branch_id or l.branch_id))
            if loc.id in loc_ids and (not self.branch_ids or branch.id in self.branch_ids.ids):
                labels.append(l)
                label_locations[l.id] = loc
                label_branches[l.id] = branch

        # 4. Vault / Unlabeled Quants calculation
        prod_loc_pairs = {(q.product_id, q.location_id) for q in quants}
        for m in moves_after:
            if m.location_id.id in loc_ids: prod_loc_pairs.add((m.product_id, m.location_id))
            if m.location_dest_id.id in loc_ids: prod_loc_pairs.add((m.product_id, m.location_dest_id))

        vault_moves = self.env['stock.move'].sudo().search([
            ('product_id.product_tmpl_id.is_vault_item', '=', True), ('state', '=', 'done'),
            '|', ('location_id', 'in', loc_ids), ('location_dest_id', 'in', loc_ids)
        ], order='date asc')
        for m in vault_moves:
            if m.location_id.id in loc_ids: prod_loc_pairs.add((m.product_id, m.location_id))
            if m.location_dest_id.id in loc_ids: prod_loc_pairs.add((m.product_id, m.location_dest_id))

        incoming_after, outgoing_after = {}, {}
        for m in moves_after:
            if m.location_dest_id.id in loc_ids:
                k = (m.product_id.id, m.location_dest_id.id)
                incoming_after[k] = incoming_after.get(k, 0.0) + m.product_qty
            if m.location_id.id in loc_ids:
                k = (m.product_id.id, m.location_id.id)
                outgoing_after[k] = outgoing_after.get(k, 0.0) + m.product_qty

        current_quant_qty = {(q.product_id.id, q.location_id.id): q.quantity for q in quants}
        current_quant_in_date = {(q.product_id.id, q.location_id.id): (q.in_date or q.create_date) for q in quants}
        vault_before = {}
        for m in vault_moves:
            if m.date <= self.start_datetime:
                vault_before.setdefault(m.product_id.id, []).append(m)

        class HistoricalQuant:
            def __init__(self, **kw): self.__dict__.update(kw)

        unlabeled_quants = []
        for prod, loc in prod_loc_pairs:
            if not prod.is_vault_item:
                continue
            key = (prod.id, loc.id)
            if prod.detailed_type == 'consu' or prod.type == 'consu':
                m_bef = vault_before.get(prod.id, [])
                hist_qty = sum(m.product_qty for m in m_bef if m.location_dest_id.id == loc.id) - sum(m.product_qty for m in m_bef if m.location_id.id == loc.id)
            else:
                hist_qty = current_quant_qty.get(key, 0.0) - incoming_after.get(key, 0.0) + outgoing_after.get(key, 0.0)

            if hist_qty > 0.0001:
                in_date = current_quant_in_date.get(key)
                if not in_date:
                    em = self.env['stock.move'].sudo().search([('product_id', '=', prod.id), ('location_dest_id', '=', loc.id), ('state', '=', 'done')], order='date asc', limit=1)
                    in_date = em.date if em else self.start_datetime

                po_line = self.env['purchase.order.line'].sudo().search([('product_id', '=', prod.id), ('state', 'in', ('purchase', 'done'))], order='id desc', limit=1)
                if po_line:
                    scale = hist_qty / po_line.product_qty if po_line.product_qty else 1.0
                    pcs, gross = int(hist_qty), (po_line.gross_weight or po_line.product_qty or 0.0) * scale
                    di_g, di_ct = (po_line.diamond_weight_gm or 0.0) * scale, ((po_line.diamond_weight_gm or 0.0) / 0.2) * scale
                    stone, other, net = (po_line.stone_weight or 0.0) * scale, 0.0, (po_line.net_weight or 0.0) * scale
                    in_date = po_line.order_id.date_approve or po_line.order_id.date_order or in_date
                else:
                    uom_cat = prod.uom_id.category_id.name if prod.uom_id and prod.uom_id.category_id else ""
                    pcs = int(hist_qty) if uom_cat in ('Unit', 'Working Time') else 0
                    gross = hist_qty * (prod.weight or 0.0) if pcs else hist_qty
                    di_g, di_ct, stone, other, net = 0.0, 0.0, 0.0, 0.0, gross

                unlabeled_quants.append(HistoricalQuant(product_id=prod, location_id=loc, quantity=hist_qty, in_date=in_date,
                                                        branch_id=loc.branch_id, pcs=pcs, gross=gross, diamond_g=di_g,
                                                        diamond_ct=di_ct, stone=stone, other=other, net=net))

        # 5. Pre-build Variant Attributes Map (Metal Colour, Variety, Type, Design, Stone Colour, Size)
        all_prods = set(l.product_id for l in labels if l.product_id) | {q.product_id for q in unlabeled_quants if q.product_id}
        prod_attr_map = {}
        for p in all_prods:
            v_dict = {v: "None" for v in VARIANTS}
            for ptav in p.product_template_attribute_value_ids:
                val = (ptav.name or "").strip()
                attr = (ptav.attribute_id.name or "").strip()
                for v in VARIANTS:
                    if attr.lower() == v.lower():
                        v_dict[v] = val if val and val.lower() not in ("none", "0", "00") else "None"
            prod_attr_map[p.id] = v_dict

        # 6. Generate Excel
        wb = Workbook()
        font_header = Font(name="Arial", size=10, bold=True)
        font_data = Font(name="Arial", size=10)
        font_total = Font(name="Arial", size=10, bold=True)
        b_side = Side(border_style="thin", color="000000")
        border_all = Border(left=b_side, right=b_side, top=b_side, bottom=b_side)
        border_head = Border(top=b_side, bottom=b_side)
        border_tot = Border(top=b_side, bottom=Side(style='double', color='000000'))
        align_c = Alignment(horizontal="center", vertical="center")
        align_l = Alignment(horizontal="left", vertical="center")
        align_r = Alignment(horizontal="right", vertical="center")

        branch_text = ", ".join(self.branch_ids.mapped('name')) if self.branch_ids else "All Branches"
        start_str = local_start_dt.strftime('%d-%b-%y %I:%M:%S %p')

        def setup_sheet(ws, title, headers):
            ws.cell(row=1, column=2, value=title).font = font_total
            ws.cell(row=1, column=4, value=branch_text).font = font_total
            ws.cell(row=2, column=2, value="Date").font = font_total
            ws.cell(row=2, column=3, value=start_str).font = font_data
            ws.row_dimensions[3].height = 25
            for col_idx, h in enumerate(headers, 1):
                set_cell(ws, 3, col_idx, h, align=align_c, font=font_header, border=border_head)

        # SHEET 1: Label Closing Stock Report
        ws1 = wb.active
        ws1.title = "Label Closing Stock Report"
        headers1 = [
            "Branch Receipt Date", "Label No.", "Barcode", "Second Barcode", "Vendor Name", "Item Name",
            "Metal Colour", "Variety", "Type", "Design", "Stone Colour", "Size",
            "Carat", "Branch", "Location", "Pcs", "Gross Wt.",
            "Diamond Wt", "Diamond Wt ( Caret )", "Stone Weight", "Other Weight", "Net Wt.", "Aging Days"
        ]
        setup_sheet(ws1, "Closing Stock Label Wise", headers1)

        row_idx = 4
        tot_pcs, tot_gross, tot_di_g, tot_di_ct, tot_stone, tot_other, tot_net = 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        for l in labels:
            ws1.row_dimensions[row_idx].height = 20
            rec_date = get_date_val(l.create_date) or today
            days = max(0, (local_start_dt.date() - rec_date).days + 1)
            item_name = (l.product_template_id or l.product_tmpl_id or (l.product_id and l.product_id.product_tmpl_id)).name or ""
            p_attrs = prod_attr_map.get(l.product_id.id, {v: "None" for v in VARIANTS})

            # Vendor Name strictly from label.partner_id if present; otherwise blank
            vendor_name = l.partner_id.name.strip() if (l.partner_id and l.partner_id.name) else ""

            pcs = 1
            gross = l.purchase_gross_weight or 0.0
            di_g = l.purchase_diamond_weight_gm or 0.0
            di_ct = l.purchase_diamond_weight_ct or 0.0
            stone = l.purchase_stone_weight or 0.0
            other = l.other_weight_g or 0.0
            net = l.purchase_net_weight or 0.0

            tot_pcs += pcs
            tot_gross += gross
            tot_di_g += di_g
            tot_di_ct += di_ct
            tot_stone += stone
            tot_other += other
            tot_net += net

            cols1 = [
                (rec_date.strftime('%d-%b-%y'), align_c, None),
                (l.name or "", align_c, None),
                (l.barcode or "", align_c, None),
                (l.barcode2 or "", align_c, None),
                (vendor_name, align_l, None),
                (item_name, align_l, None),
                (p_attrs["Metal Colour"], align_c, None),
                (p_attrs["Variety"], align_l, None),
                (p_attrs["Type"], align_l, None),
                (p_attrs["Design"], align_l, None),
                (p_attrs["Stone Colour"], align_c, None),
                (p_attrs["Size"], align_c, None),
                (l.purity_id.name or "", align_c, None),
                (label_branches[l.id].name or "", align_c, None),
                (label_locations[l.id].complete_name or "", align_c, None),
                (pcs, align_r, "#,##0"),
                (gross, align_r, "#,##0.000"),
                (di_g, align_r, "#,##0.000"),
                (di_ct, align_r, "#,##0.00"),
                (stone, align_r, "#,##0.000"),
                (other, align_r, "#,##0.000"),
                (net, align_r, "#,##0.000"),
                (days, align_r, "#,##0"),
            ]
            for c_idx, (v, al, nf) in enumerate(cols1, 1):
                set_cell(ws1, row_idx, c_idx, v, align=al, num_format=nf, font=font_data, border=border_all)
            row_idx += 1

        ws1.row_dimensions[row_idx].height = 22
        tot_map1 = {
            6: ("Total", align_l, None),
            16: (tot_pcs, align_r, "#,##0"),
            17: (tot_gross, align_r, "#,##0.000"),
            18: (tot_di_g, align_r, "#,##0.000"),
            19: (tot_di_ct, align_r, "#,##0.00"),
            20: (tot_stone, align_r, "#,##0.000"),
            21: (tot_other, align_r, "#,##0.000"),
            22: (tot_net, align_r, "#,##0.000"),
        }
        for col_idx in range(1, 24):
            v, al, nf = tot_map1.get(col_idx, ("", None, None))
            set_cell(ws1, row_idx, col_idx, v, align=al, num_format=nf, font=font_total, border=border_tot)

        # SHEET 2: Vault Item Closing Stock
        ws2 = wb.create_sheet(title="Vault Item Closing Stock")
        headers2 = [
            "Branch Receipt Date", "Vendor Name", "Item Name",
            "Metal Colour", "Variety", "Type", "Design", "Stone Colour", "Size",
            "Carat", "Branch", "Location", "Gross Wt.",
            "Diamond Wt", "Diamond Wt ( Caret )", "Stone Weight", "Net Wt.", "Aging Days"
        ]
        setup_sheet(ws2, "Closing Stock Vault Item Wise", headers2)

        row_idx2 = 4
        tot_gross2, tot_di_g2, tot_di_ct2, tot_stone2, tot_net2 = 0.0, 0.0, 0.0, 0.0, 0.0
        for q in unlabeled_quants:
            ws2.row_dimensions[row_idx2].height = 20
            rec_date2 = get_date_val(q.in_date) or today
            days2 = max(0, (local_start_dt.date() - rec_date2).days + 1)
            b_name2 = q.branch_id.name or q.location_id.branch_id.name or q.location_id.warehouse_id.name or ""
            p_attrs2 = prod_attr_map.get(q.product_id.id, {v: "None" for v in VARIANTS})

            tot_gross2 += q.gross
            tot_di_g2 += q.diamond_g
            tot_di_ct2 += q.diamond_ct
            tot_stone2 += q.stone
            tot_net2 += q.net

            cols2 = [
                (rec_date2.strftime('%d-%b-%y'), align_c, None),
                ("", align_l, None),
                (q.product_id.product_tmpl_id.name or "", align_l, None),
                (p_attrs2["Metal Colour"], align_c, None),
                (p_attrs2["Variety"], align_l, None),
                (p_attrs2["Type"], align_l, None),
                (p_attrs2["Design"], align_l, None),
                (p_attrs2["Stone Colour"], align_c, None),
                (p_attrs2["Size"], align_c, None),
                (q.product_id.purity_id.name or "", align_c, None),
                (b_name2, align_c, None),
                (q.location_id.complete_name or "", align_c, None),
                (q.gross, align_r, "#,##0.000"),
                (q.diamond_g, align_r, "#,##0.000"),
                (q.diamond_ct, align_r, "#,##0.00"),
                (q.stone, align_r, "#,##0.000"),
                (q.net, align_r, "#,##0.000"),
                (days2, align_r, "#,##0"),
            ]
            for c_idx, (v, al, nf) in enumerate(cols2, 1):
                set_cell(ws2, row_idx2, c_idx, v, align=al, num_format=nf, font=font_data, border=border_all)
            row_idx2 += 1

        ws2.row_dimensions[row_idx2].height = 22
        tot_map2 = {
            3: ("Total", align_l, None),
            13: (tot_gross2, align_r, "#,##0.000"),
            14: (tot_di_g2, align_r, "#,##0.000"),
            15: (tot_di_ct2, align_r, "#,##0.00"),
            16: (tot_stone2, align_r, "#,##0.000"),
            17: (tot_net2, align_r, "#,##0.000"),
        }
        for col_idx in range(1, 19):
            v, al, nf = tot_map2.get(col_idx, ("", None, None))
            set_cell(ws2, row_idx2, col_idx, v, align=al, num_format=nf, font=font_total, border=border_tot)

        # Freeze panes, auto-width and view settings
        for ws in (ws1, ws2):
            for col_cells in ws.columns:
                m_len = max((len(str(c.value or "")) for c in col_cells), default=0)
                ws.column_dimensions[col_cells[0].column_letter].width = max(m_len + 3, 11)
            ws.freeze_panes = 'A4'
            ws.views.sheetView[0].topLeftCell = 'A1'
            ws.views.sheetView[0].selection = [Selection(activeCell='A1', sqref='A1', pane='bottomLeft')]

        wb.active = ws1
        ws1.views.sheetView[0].tabSelected = True

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        self.file_data = base64.b64encode(output.read())
        self.file_name = "label_closing_stock_variant_report.xlsx"
        output.close()

        return {
            "type": "ir.actions.act_url",
            "url": (
                "/web/content/?model=product.label.variant.report.wizard"
                "&id=%s"
                "&field=file_data"
                "&filename_field=file_name"
                "&download=true"
            ) % self.id,
            "target": "self",
        }
