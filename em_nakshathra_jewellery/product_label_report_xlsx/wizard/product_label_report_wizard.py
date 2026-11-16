from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from io import BytesIO
import base64
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

class ProductLabelReportWizard(models.TransientModel):
    _name = "product.label.report.wizard"
    _description = "Label Closing Stock Report Wizard"

    @api.model
    def _default_start_datetime(self):
        today_local = fields.Date.context_today(self)
        dt_local = datetime.combine(today_local, datetime.min.time())
        user_tz = self.env.user.tz
        if user_tz:
            import pytz
            local_tz = pytz.timezone(user_tz)
            local_dt = local_tz.localize(dt_local, is_dst=None)
            utc_dt = local_dt.astimezone(pytz.utc)
            return utc_dt.replace(tzinfo=None)
        return dt_local

    start_datetime = fields.Datetime(string="Up to Date & Time", required=True, default=fields.Datetime.now)
    branch_ids = fields.Many2many("res.branch", string="Branches")

    file_data = fields.Binary(readonly=True)
    file_name = fields.Char(readonly=True)

    def action_print_report(self):
        self.ensure_one()
        today = fields.Date.today()

        # Helper to convert dates safely
        def get_date_from_val(val):
            if not val:
                return False
            if isinstance(val, datetime):
                return val.date()
            elif isinstance(val, (fields.Date, fields.Datetime)):
                return fields.Date.to_date(val)
            return False

        # 1. Fetch internal locations matching branch filters
        loc_domain = [('usage', '=', 'internal')]
        if self.branch_ids:
            loc_domain.append(('branch_id', 'in', self.branch_ids.ids))
        locations = self.env['stock.location'].sudo().search(loc_domain)
        loc_ids = locations.ids
        loc_ids_set = set(loc_ids)
        loc_by_id = {loc.id: loc for loc in locations}
        loc_branch_id_map = {loc.id: loc.branch_id.id for loc in locations}
        loc_complete_name_map = {loc.id: (loc.complete_name or "") for loc in locations}
        branch_name_map = {
            b.id: (b.name or "")
            for b in self.env['res.branch'].sudo().search([])
        }
        purity_name_map = {
            p.id: (p.name or "")
            for p in self.env['gold.purity'].sudo().search([])
        }

        # Only vault-item quants are needed for the unlabeled vault sheet.
        quants = self.env['stock.quant'].sudo().search([
            ('location_id', 'in', loc_ids),
            ('quantity', '>', 0),
            ('product_id.product_tmpl_id.is_vault_item', '=', True)
        ]) if loc_ids else self.env['stock.quant'].sudo()

        import pytz
        local_start_dt = fields.Datetime.context_timestamp(self, self.start_datetime)

        # Include inactive labels too; stock moves determine their location at the cutoff.
        # Use direct SQL queries instead of ORM recordset prefetching to avoid MemoryError on large datasets.
        active_at_cutoff = {}
        active_before_cutoff = {}
        self.env.cr.execute("""
            SELECT mm.res_id, mm.date, mtv.old_value_integer, mtv.new_value_integer
            FROM mail_tracking_value mtv
            JOIN ir_model_fields imf ON mtv.field_id = imf.id
            JOIN mail_message mm ON mtv.mail_message_id = mm.id
            JOIN product_label pl ON mm.res_id = pl.id
            WHERE imf.model = 'product.label'
              AND imf.name = 'active'
              AND mm.model = 'product.label'
              AND pl.create_date <= %s
            ORDER BY COALESCE(mm.date, '-infinity'::timestamp) ASC, mm.id ASC, mtv.id ASC
        """, (self.start_datetime,))
        for label_id, message_date, old_val, new_val in self.env.cr.fetchall():
            if message_date and message_date <= self.start_datetime:
                active_before_cutoff[label_id] = bool(new_val)
            elif message_date:
                active_at_cutoff.setdefault(label_id, bool(old_val))
        active_at_cutoff.update(active_before_cutoff)
        del active_before_cutoff

        # Get first and last done stock moves per candidate label via SQL without ORM prefetch
        first_move_by_label = {}
        last_move_before_by_label = {}
        self.env.cr.execute("""
            SELECT sm.label_id, sm.date, sm.location_id, sm.location_dest_id, sm.branch_id
            FROM stock_move sm
            JOIN product_label pl ON sm.label_id = pl.id
            WHERE sm.state = 'done'
              AND sm.label_id IS NOT NULL
              AND pl.create_date <= %s
            ORDER BY sm.date ASC, sm.id ASC
        """, (self.start_datetime,))
        for label_id, m_date, loc_id, loc_dest_id, m_branch_id in self.env.cr.fetchall():
            if label_id not in first_move_by_label:
                first_move_by_label[label_id] = (loc_id, m_branch_id)
            if m_date <= self.start_datetime:
                last_move_before_by_label[label_id] = (loc_dest_id, m_branch_id)

        valid_label_ids = []
        label_loc_id_map = {}
        label_branch_id_map = {}
        branch_filter_set = set(self.branch_ids.ids) if self.branch_ids else None

        if loc_ids_set:
            self.env.cr.execute("""
                SELECT id, active, branch_location_id, branch_id
                FROM product_label
                WHERE create_date <= %s
                ORDER BY id ASC
            """, (self.start_datetime,))
            for label_id, is_active, branch_loc_id, label_branch_id in self.env.cr.fetchall():
                if not active_at_cutoff.get(label_id, bool(is_active)):
                    continue

                # Find the last move of this label done before or at start_datetime
                last_move = last_move_before_by_label.get(label_id)
                if last_move:
                    hist_loc_id, fallback_branch_id = last_move
                else:
                    first_move = first_move_by_label.get(label_id)
                    if first_move:
                        hist_loc_id, fallback_branch_id = first_move
                    else:
                        hist_loc_id, fallback_branch_id = branch_loc_id, label_branch_id

                # Filter by branch / location
                if not hist_loc_id or hist_loc_id not in loc_ids_set:
                    continue
                hist_branch_id = loc_branch_id_map.get(hist_loc_id) or fallback_branch_id
                if branch_filter_set and hist_branch_id not in branch_filter_set:
                    continue

                valid_label_ids.append(label_id)
                label_loc_id_map[label_id] = hist_loc_id
                label_branch_id_map[label_id] = hist_branch_id

        del active_at_cutoff
        del first_move_by_label
        del last_move_before_by_label

        # Collect current quant information
        current_quant_qty = {(q.product_id.id, q.location_id.id): q.quantity for q in quants}
        current_quant_in_date = {(q.product_id.id, q.location_id.id): q.in_date for q in quants}
        current_quant_create_date = {(q.product_id.id, q.location_id.id): q.create_date for q in quants}

        # Collect all unique (product_id, location_id) pairs for vault items.
        prod_loc_id_pairs = set()
        for q in quants:
            prod_loc_id_pairs.add((q.product_id.id, q.location_id.id))

        # Query all completed done stock moves of vault items in the selected locations via SQL
        incoming_after = {}
        outgoing_after = {}
        vault_moves_before_by_product = {}
        vault_moves_dest_before_by_product_loc = {}

        if loc_ids:
            self.env.cr.execute("""
                SELECT sm.product_id, sm.location_id, sm.location_dest_id, sm.product_qty, sm.date
                FROM stock_move sm
                JOIN product_product pp ON sm.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE pt.is_vault_item IS TRUE
                  AND sm.state = 'done'
                  AND (sm.location_id IN %s OR sm.location_dest_id IN %s)
                ORDER BY sm.date ASC, sm.id ASC
            """, (tuple(loc_ids), tuple(loc_ids)))
            for prod_id, m_loc_id, m_loc_dest_id, qty, m_date in self.env.cr.fetchall():
                qty = qty or 0.0
                if m_loc_id in loc_ids_set:
                    prod_loc_id_pairs.add((prod_id, m_loc_id))
                if m_loc_dest_id in loc_ids_set:
                    prod_loc_id_pairs.add((prod_id, m_loc_dest_id))

                if m_date > self.start_datetime:
                    if m_loc_dest_id in loc_ids_set:
                        key = (prod_id, m_loc_dest_id)
                        incoming_after[key] = incoming_after.get(key, 0.0) + qty
                    if m_loc_id in loc_ids_set:
                        key = (prod_id, m_loc_id)
                        outgoing_after[key] = outgoing_after.get(key, 0.0) + qty
                else:
                    vault_moves_before_by_product.setdefault(prod_id, []).append(
                        (m_loc_id, m_loc_dest_id, qty, m_date)
                    )
                    key_loc = (prod_id, m_loc_dest_id)
                    vault_moves_dest_before_by_product_loc.setdefault(key_loc, []).append(m_date)

        class HistoricalQuantMock:
            def __init__(self, product, location, qty, in_date, branch=None, label_no="", is_labeled=False,
                         pcs=None, gross=None, diamond_g=0.0, diamond_ct=0.0, stone=0.0, other=0.0, net=None):
                self.product_id = product
                self.location_id = location
                self.quantity = qty
                self.in_date = in_date
                self.create_date = in_date
                self.branch_id = branch or location.branch_id
                self.label_no = label_no
                self.is_labeled = is_labeled
                self.pcs = pcs
                self.gross = gross
                self.diamond_g = diamond_g
                self.diamond_ct = diamond_ct
                self.stone = stone
                self.other = other
                self.net = net

        vault_product_ids = list({pid for pid, _ in prod_loc_id_pairs})
        vault_products_by_id = {
            p.id: p for p in self.env['product.product'].sudo().browse(vault_product_ids)
        } if vault_product_ids else {}

        # Collect vault items
        unlabeled_quants = []
        for prod_id, loc_id in prod_loc_id_pairs:
            product = vault_products_by_id.get(prod_id)
            location = loc_by_id.get(loc_id)
            if not product or not location or not product.is_vault_item:
                continue

            key = (product.id, location.id)
            
            # If the product type is 'consu' (Consumable), compute historical qty directly from moves
            if product.detailed_type == 'consu' or product.type == 'consu':
                moves_before = vault_moves_before_by_product.get(product.id, [])
                in_qty = sum(m_qty for _, m_dest_id, m_qty, _ in moves_before if m_dest_id == location.id)
                out_qty = sum(m_qty for m_src_id, _, m_qty, _ in moves_before if m_src_id == location.id)
                historical_qty = in_qty - out_qty
            else:
                current_qty = current_quant_qty.get(key, 0.0)
                historical_qty = current_qty - incoming_after.get(key, 0.0) + outgoing_after.get(key, 0.0)

            # If there is remaining stock
            if historical_qty > 0.0001:
                in_date = None
                if product.detailed_type == 'consu' or product.type == 'consu':
                    moves_before_dest = vault_moves_dest_before_by_product_loc.get(key, [])
                    if moves_before_dest:
                        in_date = moves_before_dest[0]
                else:
                    in_date = current_quant_in_date.get(key) or current_quant_create_date.get(key)

                if not in_date:
                    earliest_move = self.env['stock.move'].sudo().search([
                        ('product_id', '=', product.id),
                        ('location_dest_id', '=', location.id),
                        ('state', '=', 'done')
                    ], order='date asc', limit=1)
                    in_date = earliest_move.date if earliest_move else self.start_datetime

                # Since it is a vault item, retrieve its purchase details
                po_line = self.env['purchase.order.line'].sudo().search([
                    ('product_id', '=', product.id),
                    ('state', 'in', ('purchase', 'done'))
                ], order='id desc', limit=1)

                if po_line:
                    scale_factor = historical_qty / po_line.product_qty if po_line.product_qty else 1.0
                    pcs = int(historical_qty)
                    gross = (po_line.gross_weight or po_line.product_qty or 0.0) * scale_factor
                    diamond_g = (po_line.diamond_weight_gm or 0.0) * scale_factor
                    diamond_ct = ((po_line.diamond_weight_gm or 0.0) / 0.2) * scale_factor
                    stone = (po_line.stone_weight or 0.0) * scale_factor
                    other = 0.0
                    net = (po_line.net_weight or 0.0) * scale_factor
                    
                    po_date = po_line.order_id.date_approve or po_line.order_id.date_order
                    if po_date:
                        in_date = po_date
                else:
                    # Fallback to standard product defaults if no PO line is found
                    uom_id = product.uom_id
                    uom_cat = uom_id.category_id.name if uom_id and uom_id.category_id else ""
                    if uom_cat in ('Unit', 'Working Time'):
                        pcs = int(historical_qty)
                        gross = historical_qty * (product.weight or 0.0)
                    else:
                        pcs = 0
                        gross = historical_qty
                    diamond_g = 0.0
                    diamond_ct = 0.0
                    stone = 0.0
                    other = 0.0
                    net = gross

                unlabeled_quants.append(HistoricalQuantMock(
                    product=product,
                    location=location,
                    qty=historical_qty,
                    in_date=in_date,
                    is_labeled=False,
                    pcs=pcs,
                    gross=gross,
                    diamond_g=diamond_g,
                    diamond_ct=diamond_ct,
                    stone=stone,
                    other=other,
                    net=net
                ))
        wb = Workbook()

        # Styles
        font_header = Font(name="Arial", size=10, bold=True)
        font_data = Font(name="Arial", size=10)
        font_total = Font(name="Arial", size=10, bold=True)

        border_side_black = Side(border_style="thin", color="000000")
        border_all_cells = Border(left=border_side_black, right=border_side_black, top=border_side_black, bottom=border_side_black)

        border_header_row = Border(
            top=Side(style='thin', color='000000'),
            bottom=Side(style='thin', color='000000')
        )

        border_total_row = Border(
            top=Side(style='thin', color='000000'),
            bottom=Side(style='double', color='000000')
        )

        align_center = Alignment(horizontal="center", vertical="center")
        align_left = Alignment(horizontal="left", vertical="center")
        align_right = Alignment(horizontal="right", vertical="center")

        headers_sheet1 = [
            "Branch Receipt Date",
            "Label No.",
            "Barcode",
            "Second Barcode",
            "Item Name",
            "Variety Name",
            "Carat",
            "Branch",
            "Location",
            "Pcs",
            "Gross Wt.",
            "Diamond Wt",
            "Diamond Wt ( Caret )",
            "Stone Weight",
            "Other Weight",
            "Net Wt.",
            "Aging Days"
        ]

        headers_sheet2 = [
            "Branch Receipt Date",
            "Item Name",
            "Variety Name",
            "Carat",
            "Branch",
            "Location",
            "Gross Wt.",
            "Diamond Wt",
            "Diamond Wt ( Caret )",
            "Stone Weight",
            "Net Wt.",
            "Aging Days"
        ]

        # Branch name header text
        branch_name_text = ", ".join(self.branch_ids.mapped('name')) if self.branch_ids else "All Branches"
        start_date_str = local_start_dt.strftime('%d-%b-%y %I:%M:%S %p')

        def setup_sheet_headers(ws, title_text, sheet_headers):
            # Row 1
            ws.cell(row=1, column=2, value=title_text).font = font_total
            ws.cell(row=1, column=4, value=branch_name_text).font = font_total

            # Row 2
            ws.cell(row=2, column=2, value="Date").font = font_total
            ws.cell(row=2, column=3, value=start_date_str).font = font_data
            ws.cell(row=2, column=4, value="").font = font_total
            ws.cell(row=2, column=5, value="").font = font_data

            # Row 3 - Table headers
            ws.row_dimensions[3].height = 25
            for col_idx, header in enumerate(sheet_headers, start=1):
                cell = ws.cell(row=3, column=col_idx, value=header)
                cell.font = font_header
                cell.alignment = align_center
                cell.border = border_header_row

        # ==========================================
        # SHEET 1: Label Closing Stock Report
        # ==========================================
        ws1 = wb.active
        ws1.title = "Label Closing Stock Report"
        setup_sheet_headers(ws1, "Closing Stock Label Wise", headers_sheet1)

        row_idx = 4
        tot_pcs = 0
        tot_gross = 0.0
        tot_diamond_g = 0.0
        tot_diamond_ct = 0.0
        tot_stone = 0.0
        tot_other = 0.0
        tot_net = 0.0

        label_model = self.env['product.label'].sudo().with_context(active_test=False)
        has_product_template_id = 'product_template_id' in label_model._fields
        label_read_fields = [
            'create_date', 'name', 'barcode', 'barcode2',
            'product_id', 'product_tmpl_id', 'purity_id',
            'purchase_gross_weight', 'purchase_diamond_weight_gm',
            'purchase_diamond_weight_ct', 'purchase_stone_weight',
            'other_weight_g', 'purchase_net_weight',
        ]
        if has_product_template_id:
            label_read_fields.append('product_template_id')

        product_info_cache = {}
        template_name_cache = {}
        batch_size = 2000

        for start_idx in range(0, len(valid_label_ids), batch_size):
            batch_ids = valid_label_ids[start_idx:start_idx + batch_size]
            batch_rows = label_model.browse(batch_ids).read(label_read_fields, load='_classic_write')

            missing_prod_ids = {
                r['product_id'] for r in batch_rows
                if r.get('product_id') and r['product_id'] not in product_info_cache
            }
            if missing_prod_ids:
                for p in self.env['product.product'].sudo().with_context(active_test=False).browse(list(missing_prod_ids)):
                    product_info_cache[p.id] = (
                        p.display_name or "",
                        p.product_tmpl_id.name if p.product_tmpl_id else "",
                    )

            missing_tmpl_ids = set()
            for r in batch_rows:
                t1 = r.get('product_template_id')
                t2 = r.get('product_tmpl_id')
                if t1 and t1 not in template_name_cache:
                    missing_tmpl_ids.add(t1)
                if t2 and t2 not in template_name_cache:
                    missing_tmpl_ids.add(t2)
            if missing_tmpl_ids:
                for t in self.env['product.template'].sudo().with_context(active_test=False).browse(list(missing_tmpl_ids)):
                    template_name_cache[t.id] = t.name or ""

            for row in batch_rows:
                label_id = row['id']
                ws1.row_dimensions[row_idx].height = 20

                # Receipt Date
                receipt_date_val = get_date_from_val(row.get('create_date')) or today
                receipt_date_str = receipt_date_val.strftime('%d-%b-%y')

                # Aging Days
                days = (local_start_dt.date() - receipt_date_val).days + 1
                if days < 0:
                    days = 0

                prod_id = row.get('product_id')
                prod_display_name, prod_tmpl_name = product_info_cache.get(prod_id, ("", ""))

                # Variety Name
                variety_name = prod_display_name

                # Item Name resolution
                item_name = ""
                if row.get('product_template_id'):
                    item_name = template_name_cache.get(row['product_template_id'], "")
                elif row.get('product_tmpl_id'):
                    item_name = template_name_cache.get(row['product_tmpl_id'], "")
                elif prod_tmpl_name:
                    item_name = prod_tmpl_name

                # Values
                pcs = 1
                gross = row.get('purchase_gross_weight') or 0.0
                diamond_g = row.get('purchase_diamond_weight_gm') or 0.0
                diamond_ct = row.get('purchase_diamond_weight_ct') or 0.0
                stone = row.get('purchase_stone_weight') or 0.0
                other = row.get('other_weight_g') or 0.0
                net = row.get('purchase_net_weight') or 0.0

                tot_pcs += pcs
                tot_gross += gross
                tot_diamond_g += diamond_g
                tot_diamond_ct += diamond_ct
                tot_stone += stone
                tot_other += other
                tot_net += net

                hist_branch_id = label_branch_id_map.get(label_id)
                hist_loc_id = label_loc_id_map.get(label_id)

                # Write data row
                ws1.cell(row=row_idx, column=1, value=receipt_date_str).alignment = align_center
                ws1.cell(row=row_idx, column=2, value=row.get('name') or "").alignment = align_center
                ws1.cell(row=row_idx, column=3, value=row.get('barcode') or "").alignment = align_center
                ws1.cell(row=row_idx, column=4, value=row.get('barcode2') or "").alignment = align_center
                ws1.cell(row=row_idx, column=5, value=item_name or "").alignment = align_left
                ws1.cell(row=row_idx, column=6, value=variety_name or "").alignment = align_left
                ws1.cell(row=row_idx, column=7, value=purity_name_map.get(row.get('purity_id'), "")).alignment = align_center
                ws1.cell(row=row_idx, column=8, value=branch_name_map.get(hist_branch_id, "")).alignment = align_center
                ws1.cell(row=row_idx, column=9, value=loc_complete_name_map.get(hist_loc_id, "")).alignment = align_center

                c_pcs = ws1.cell(row=row_idx, column=10, value=pcs)
                c_pcs.alignment = align_right
                c_pcs.number_format = "#,##0"

                c_gross = ws1.cell(row=row_idx, column=11, value=gross)
                c_gross.alignment = align_right
                c_gross.number_format = "#,##0.000"

                c_di_g = ws1.cell(row=row_idx, column=12, value=diamond_g)
                c_di_g.alignment = align_right
                c_di_g.number_format = "#,##0.000"

                c_di_ct = ws1.cell(row=row_idx, column=13, value=diamond_ct)
                c_di_ct.alignment = align_right
                c_di_ct.number_format = "#,##0.00"

                c_stone = ws1.cell(row=row_idx, column=14, value=stone)
                c_stone.alignment = align_right
                c_stone.number_format = "#,##0.000"

                c_other = ws1.cell(row=row_idx, column=15, value=other)
                c_other.alignment = align_right
                c_other.number_format = "#,##0.000"

                c_net = ws1.cell(row=row_idx, column=16, value=net)
                c_net.alignment = align_right
                c_net.number_format = "#,##0.000"

                c_days = ws1.cell(row=row_idx, column=17, value=days)
                c_days.alignment = align_right
                c_days.number_format = "#,##0"

                for col in range(1, 18):
                    cell = ws1.cell(row=row_idx, column=col)
                    cell.font = font_data
                    cell.border = border_all_cells

                row_idx += 1

            self.env.invalidate_all()

        # Sheet 1 Totals
        ws1.row_dimensions[row_idx].height = 22
        ws1.cell(row=row_idx, column=6, value="Total").alignment = align_left
        ws1.cell(row=row_idx, column=10, value=tot_pcs).number_format = "#,##0"
        ws1.cell(row=row_idx, column=10).alignment = align_right

        ws1.cell(row=row_idx, column=11, value=tot_gross).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=11).alignment = align_right

        ws1.cell(row=row_idx, column=12, value=tot_diamond_g).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=12).alignment = align_right

        ws1.cell(row=row_idx, column=13, value=tot_diamond_ct).number_format = "#,##0.00"
        ws1.cell(row=row_idx, column=13).alignment = align_right

        ws1.cell(row=row_idx, column=14, value=tot_stone).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=14).alignment = align_right

        ws1.cell(row=row_idx, column=15, value=tot_other).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=15).alignment = align_right

        ws1.cell(row=row_idx, column=16, value=tot_net).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=16).alignment = align_right

        for col in range(1, 18):
            cell = ws1.cell(row=row_idx, column=col)
            cell.font = font_total
            cell.border = border_total_row

        # ==========================================
        # SHEET 2: Vault Item Closing Stock
        # ==========================================
        ws2 = wb.create_sheet(title="Vault Item Closing Stock")
        setup_sheet_headers(ws2, "Closing Stock Vault Item Wise", headers_sheet2)

        row_idx2 = 4
        tot_pcs2 = 0
        tot_gross2 = 0.0
        tot_diamond_g2 = 0.0
        tot_diamond_ct2 = 0.0
        tot_stone2 = 0.0
        tot_other2 = 0.0
        tot_net2 = 0.0

        for quant in unlabeled_quants:
            ws2.row_dimensions[row_idx2].height = 20

            # Receipt Date
            receipt_date_val = get_date_from_val(quant.in_date) or get_date_from_val(quant.create_date) or today
            receipt_date_str = receipt_date_val.strftime('%d-%b-%y')

            # Aging Days
            days = (local_start_dt.date() - receipt_date_val).days + 1
            if days < 0:
                days = 0

            # Branch Name
            branch_name = quant.branch_id.name or quant.location_id.branch_id.name or quant.location_id.warehouse_id.name or ""

            # Check if labeled or not
            if quant.is_labeled or quant.product_id.is_vault_item:
                pcs = quant.pcs
                gross = quant.gross
                diamond_g = quant.diamond_g
                diamond_ct = quant.diamond_ct
                stone = quant.stone
                other = quant.other
                net = quant.net
            else:
                # Check UOM Category
                uom_id = quant.product_id.uom_id
                uom_cat = uom_id.category_id.name if uom_id and uom_id.category_id else ""
                if uom_cat in ('Unit', 'Working Time'):
                    pcs = int(quant.quantity)
                    gross = quant.quantity * (quant.product_id.weight or 0.0)
                else:
                    pcs = 0
                    gross = quant.quantity
                diamond_g = 0.0
                diamond_ct = 0.0
                stone = 0.0
                other = 0.0
                net = gross  # For unlabeled weight fallback

            tot_pcs2 += pcs
            tot_gross2 += gross
            tot_diamond_g2 += diamond_g
            tot_diamond_ct2 += diamond_ct
            tot_stone2 += stone
            tot_other2 += other
            tot_net2 += net

            # Write data row
            ws2.cell(row=row_idx2, column=1, value=receipt_date_str).alignment = align_center
            ws2.cell(row=row_idx2, column=2, value=quant.product_id.product_tmpl_id.name or "").alignment = align_left
            
            variety_name2 = quant.product_id.display_name or ""
            ws2.cell(row=row_idx2, column=3, value=variety_name2).alignment = align_left
            
            ws2.cell(row=row_idx2, column=4, value=quant.product_id.purity_id.name or "").alignment = align_center
            ws2.cell(row=row_idx2, column=5, value=branch_name).alignment = align_center
            ws2.cell(row=row_idx2, column=6, value=quant.location_id.complete_name or "").alignment = align_center

            c_gross = ws2.cell(row=row_idx2, column=7, value=gross)
            c_gross.alignment = align_right
            c_gross.number_format = "#,##0.000"

            c_di_g = ws2.cell(row=row_idx2, column=8, value=diamond_g)
            c_di_g.alignment = align_right
            c_di_g.number_format = "#,##0.000"

            c_di_ct = ws2.cell(row=row_idx2, column=9, value=diamond_ct)
            c_di_ct.alignment = align_right
            c_di_ct.number_format = "#,##0.00"

            c_stone = ws2.cell(row=row_idx2, column=10, value=stone)
            c_stone.alignment = align_right
            c_stone.number_format = "#,##0.000"

            c_net = ws2.cell(row=row_idx2, column=11, value=net)
            c_net.alignment = align_right
            c_net.number_format = "#,##0.000"

            c_days = ws2.cell(row=row_idx2, column=12, value=days)
            c_days.alignment = align_right
            c_days.number_format = "#,##0"

            for col in range(1, 13):
                cell = ws2.cell(row=row_idx2, column=col)
                cell.font = font_data
                cell.border = border_all_cells

            row_idx2 += 1

        # Sheet 2 Totals
        ws2.row_dimensions[row_idx2].height = 22
        ws2.cell(row=row_idx2, column=3, value="Total").alignment = align_left

        ws2.cell(row=row_idx2, column=7, value=tot_gross2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=7).alignment = align_right

        ws2.cell(row=row_idx2, column=8, value=tot_diamond_g2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=8).alignment = align_right

        ws2.cell(row=row_idx2, column=9, value=tot_diamond_ct2).number_format = "#,##0.00"
        ws2.cell(row=row_idx2, column=9).alignment = align_right

        ws2.cell(row=row_idx2, column=10, value=tot_stone2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=10).alignment = align_right

        ws2.cell(row=row_idx2, column=11, value=tot_net2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=11).alignment = align_right

        for col in range(1, 13):
            cell = ws2.cell(row=row_idx2, column=col)
            cell.font = font_total
            cell.border = border_total_row

        # Auto-size columns on both sheets
        for ws in (ws1, ws2):
            for column_cells in ws.columns:
                max_length = 0
                column_letter = column_cells[0].column_letter
                for cell in column_cells:
                    try:
                        if cell.value:
                            max_length = max(max_length, len(str(cell.value)))
                    except Exception:
                        pass
                ws.column_dimensions[column_letter].width = max(max_length + 3, 11)

        # Output workbook bytes
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        self.file_data = base64.b64encode(output.read())
        self.file_name = "label_closing_stock_report.xlsx"
        output.close()

        return {
            "type": "ir.actions.act_url",
            "url": (
                "/web/content/?model=product.label.report.wizard"
                "&id=%s"
                "&field=file_data"
                "&filename_field=file_name"
                "&download=true"
            ) % self.id,
            "target": "self",
        }
