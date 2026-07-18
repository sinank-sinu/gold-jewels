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

        # Get all done stock moves after start_datetime in these locations
        moves_after = self.env['stock.move'].sudo().search([
            ('state', '=', 'done'),
            ('date', '>', self.start_datetime),
            '|',
            ('location_id', 'in', loc_ids),
            ('location_dest_id', 'in', loc_ids)
        ])

        # Query stock quants with quantity > 0 in those locations
        quants = self.env['stock.quant'].sudo().search([
            ('location_id', 'in', loc_ids),
            ('quantity', '>', 0)
        ])

        # Get all sale order lines for labels sold after start_datetime
        sold_after_datetime_lines = self.env['sale.order.line'].sudo().search([
            ('label_id', '!=', False),
            ('state', '=', 'sale'),
            ('order_id.date_order', '>', self.start_datetime)
        ])
        sold_after_label_ids = sold_after_datetime_lines.mapped('label_id').ids

        # Combine all product IDs that might have had stock at start_datetime
        product_ids = list(set(
            quants.mapped('product_id').ids +
            moves_after.mapped('product_id').ids +
            sold_after_datetime_lines.mapped('product_id').ids
        ))

        import pytz
        local_start_dt = fields.Datetime.context_timestamp(self, self.start_datetime)
        # Get all labels created before/at start_datetime that are active or sold after
        labels_domain = [
            ('create_date', '<=', self.start_datetime),
            '|',
            ('active', '=', True),
            ('id', 'in', sold_after_label_ids)
        ]
        candidates = self.env['product.label'].sudo().search(labels_domain)

        # Get all stock moves for these candidate labels
        label_moves = self.env['stock.move'].sudo().search([
            ('label_id', 'in', candidates.ids),
            ('state', '=', 'done')
        ], order='date asc')

        # Pre-process label moves in a single pass to avoid looping and list comprehensions
        first_move_by_label = {}
        last_move_before_by_label = {}
        for m in label_moves:
            label_id = m.label_id.id
            if label_id not in first_move_by_label:
                first_move_by_label[label_id] = m
            if m.date <= self.start_datetime:
                last_move_before_by_label[label_id] = m

        labels = []
        label_locations = {}
        label_branches = {}

        for label in candidates:
            # Find the last move of this label done before or at start_datetime
            last_move = last_move_before_by_label.get(label.id)
            if last_move:
                historical_loc = last_move.location_dest_id
                historical_branch = last_move.branch_id or historical_loc.branch_id
            else:
                first_move = first_move_by_label.get(label.id)
                if first_move:
                    historical_loc = first_move.location_id
                    historical_branch = first_move.branch_id or historical_loc.branch_id
                else:
                    historical_loc = label.branch_location_id
                    historical_branch = label.branch_id

            # Filter by branch / location
            if historical_loc.id not in loc_ids:
                continue
            if self.branch_ids and historical_branch.id not in self.branch_ids.ids:
                continue

            labels.append(label)
            label_locations[label.id] = historical_loc
            label_branches[label.id] = historical_branch

        # Build dictionaries to quickly look up incoming and outgoing quantities after start_datetime
        incoming_after = {}
        outgoing_after = {}
        for m in moves_after:
            prod_id = m.product_id.id
            qty = m.product_qty
            if m.location_dest_id.id in loc_ids:
                key = (prod_id, m.location_dest_id.id)
                incoming_after[key] = incoming_after.get(key, 0.0) + qty
            if m.location_id.id in loc_ids:
                key = (prod_id, m.location_id.id)
                outgoing_after[key] = outgoing_after.get(key, 0.0) + qty

        # Collect current quant information
        current_quant_qty = {(q.product_id.id, q.location_id.id): q.quantity for q in quants}
        current_quant_in_date = {(q.product_id.id, q.location_id.id): q.in_date for q in quants}
        current_quant_create_date = {(q.product_id.id, q.location_id.id): q.create_date for q in quants}

        # Collect all unique (product, location) pairs
        prod_loc_pairs = set()
        for q in quants:
            prod_loc_pairs.add((q.product_id, q.location_id))
        for m in moves_after:
            if m.location_id.id in loc_ids:
                prod_loc_pairs.add((m.product_id, m.location_id))
            if m.location_dest_id.id in loc_ids:
                prod_loc_pairs.add((m.product_id, m.location_dest_id))

        # Query all completed done stock moves of vault items in the selected locations
        vault_product_moves = self.env['stock.move'].sudo().search([
            ('product_id.product_tmpl_id.is_vault_item', '=', True),
            ('state', '=', 'done'),
            '|',
            ('location_id', 'in', loc_ids),
            ('location_dest_id', 'in', loc_ids)
        ], order='date asc')

        for m in vault_product_moves:
            if m.location_id.id in loc_ids:
                prod_loc_pairs.add((m.product_id, m.location_id))
            if m.location_dest_id.id in loc_ids:
                prod_loc_pairs.add((m.product_id, m.location_dest_id))

        # Group vault product moves by product ID for quick lookups
        vault_moves_by_product = {}
        for m in vault_product_moves:
            vault_moves_by_product.setdefault(m.product_id.id, []).append(m)

        # Pre-group vault moves before or at start_datetime by product ID and destination location
        vault_moves_before_by_product = {}
        vault_moves_dest_before_by_product_loc = {}
        for m in vault_product_moves:
            if m.date <= self.start_datetime:
                vault_moves_before_by_product.setdefault(m.product_id.id, []).append(m)
                key_loc = (m.product_id.id, m.location_dest_id.id)
                vault_moves_dest_before_by_product_loc.setdefault(key_loc, []).append(m)

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

        # Query all vault labels (active or inactive) created before or at start_datetime
        vault_labels_domain = [
            ('create_date', '<=', self.start_datetime),
            ('product_tmpl_id.is_vault_item', '=', True),
            '|',
            ('active', '=', True),
            ('active', '=', False)
        ]
        vault_candidates = self.env['product.label'].sudo().with_context(active_test=False).search(vault_labels_domain)

        # Get all stock moves for these vault candidate labels
        vault_label_moves = self.env['stock.move'].sudo().search([
            ('label_id', 'in', vault_candidates.ids),
            ('state', '=', 'done')
        ], order='date asc')

        # Pre-process vault label moves in a single pass to avoid nested looping and list comprehensions
        first_vault_move_by_label = {}
        last_vault_move_before_by_label = {}
        internal_dest_vault_moves_before_by_label = {}
        internal_src_vault_moves_overall_by_label = {}

        for m in vault_label_moves:
            label_id = m.label_id.id
            if label_id not in first_vault_move_by_label:
                first_vault_move_by_label[label_id] = m
            if m.location_id.usage == 'internal':
                internal_src_vault_moves_overall_by_label.setdefault(label_id, []).append(m)

            if m.date <= self.start_datetime:
                last_vault_move_before_by_label[label_id] = m
                if m.location_dest_id.usage == 'internal':
                    internal_dest_vault_moves_before_by_label.setdefault(label_id, []).append(m)

        vault_labels_by_prod_loc = {}
        for label in vault_candidates:
            # Find the last move of this label done before or at start_datetime
            last_move = last_vault_move_before_by_label.get(label.id)
            if last_move:
                historical_loc = last_move.location_dest_id
                historical_branch = last_move.branch_id or historical_loc.branch_id
                
                # If the last location before/at start_datetime is not internal (e.g. Customers, Inventory Loss),
                # trace its last internal location before that!
                if historical_loc.usage != 'internal':
                    internal_moves = internal_dest_vault_moves_before_by_label.get(label.id, [])
                    if internal_moves:
                        historical_loc = internal_moves[-1].location_dest_id
                        historical_branch = internal_moves[-1].branch_id or historical_loc.branch_id
                    else:
                        # Fallback to source of last move if it was internal
                        if last_move.location_id.usage == 'internal':
                            historical_loc = last_move.location_id
                            historical_branch = last_move.branch_id or historical_loc.branch_id
                        else:
                            historical_loc = label.branch_location_id
                            historical_branch = label.branch_id
            else:
                first_move = first_vault_move_by_label.get(label.id)
                if first_move:
                    internal_moves = internal_src_vault_moves_overall_by_label.get(label.id, [])
                    if internal_moves:
                        historical_loc = internal_moves[0].location_id
                        historical_branch = internal_moves[0].branch_id or historical_loc.branch_id
                    else:
                        historical_loc = first_move.location_id
                        historical_branch = first_move.branch_id or historical_loc.branch_id
                else:
                    historical_loc = label.branch_location_id
                    historical_branch = label.branch_id

            # Filter by branch / location
            if historical_loc.id not in loc_ids:
                continue
            if self.branch_ids and (not historical_branch or historical_branch.id not in self.branch_ids.ids):
                continue

            # Check if this label was physically in-stock (internal location) at start_datetime
            is_in_stock = False
            if last_move:
                is_in_stock = (last_move.location_dest_id.usage == 'internal')
            else:
                is_in_stock = label.active

            key = (label.product_id.id, historical_loc.id)
            vault_labels_by_prod_loc.setdefault(key, []).append((label, historical_loc, historical_branch, is_in_stock))

        # Ensure prod_loc_pairs includes any product/location combination that has vault labels
        for (prod_id, loc_id), items in vault_labels_by_prod_loc.items():
            if items:
                prod_loc_pairs.add((items[0][0].product_id, items[0][1]))

        # Collect vault items
        unlabeled_quants = []
        for product, location in prod_loc_pairs:
            # Check if this product is a vault item
            if not product.is_vault_item:
                continue

            key = (product.id, location.id)
            
            # If the product type is 'consu' (Consumable), compute historical qty directly from moves
            if product.detailed_type == 'consu' or product.type == 'consu':
                moves_before = vault_moves_before_by_product.get(product.id, [])
                in_qty = sum(m.product_qty for m in moves_before if m.location_dest_id.id == location.id)
                out_qty = sum(m.product_qty for m in moves_before if m.location_id.id == location.id)
                historical_qty = in_qty - out_qty
            else:
                current_qty = current_quant_qty.get(key, 0.0)
                historical_qty = current_qty - incoming_after.get(key, 0.0) + outgoing_after.get(key, 0.0)

            # Get matching labels for this product and location
            matching = vault_labels_by_prod_loc.get(key, [])
            
            # Count only labels that were physically in-stock at start_datetime
            in_stock_labeled_qty = sum(1 for m in matching if m[3])

            # Calculate remaining unlabeled qty
            unlabeled_qty = historical_qty - in_stock_labeled_qty

            # Add all matching labels (active or inactive)
            for label, loc, branch, is_in_stock in matching:
                in_date = label.create_date
                unlabeled_quants.append(HistoricalQuantMock(
                    product=product,
                    location=location,
                    qty=1.0,
                    in_date=in_date,
                    branch=branch,
                    label_no=label.name,
                    is_labeled=True,
                    pcs=1,
                    gross=label.purchase_gross_weight or 0.0,
                    diamond_g=label.purchase_diamond_weight_gm or 0.0,
                    diamond_ct=label.purchase_diamond_weight_ct or 0.0,
                    stone=label.purchase_stone_weight or 0.0,
                    other=label.other_weight_g or 0.0,
                    net=label.purchase_net_weight or 0.0
                ))

            # If there is remaining unlabeled stock
            if unlabeled_qty > 0.0001:
                in_date = None
                if product.detailed_type == 'consu' or product.type == 'consu':
                    moves_before_dest = vault_moves_dest_before_by_product_loc.get(key, [])
                    if moves_before_dest:
                        in_date = moves_before_dest[0].date
                else:
                    in_date = current_quant_in_date.get(key) or current_quant_create_date.get(key)

                if not in_date:
                    earliest_move = self.env['stock.move'].sudo().search([
                        ('product_id', '=', product.id),
                        ('location_dest_id', '=', location.id),
                        ('state', '=', 'done')
                    ], order='date asc', limit=1)
                    in_date = earliest_move.date if earliest_move else self.start_datetime

                unlabeled_quants.append(HistoricalQuantMock(
                    product=product,
                    location=location,
                    qty=unlabeled_qty,
                    in_date=in_date,
                    is_labeled=False
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
            "Pcs",
            "Gross Wt.",
            "Diamond Wt",
            "Diamond Wt ( Caret )",
            "Stone Weight",
            "Other Weight",
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

        for label in labels:
            ws1.row_dimensions[row_idx].height = 20

            # Receipt Date
            receipt_date_val = get_date_from_val(label.create_date) or today
            receipt_date_str = receipt_date_val.strftime('%d-%b-%y')

            # Aging Days
            days = (local_start_dt.date() - receipt_date_val).days + 1
            if days < 0:
                days = 0

            # Variety Name
            variety_name = label.product_id.name or ""

            # Item Name resolution
            item_name = ""
            if label.product_template_id:
                item_name = label.product_template_id.name
            elif label.product_tmpl_id:
                item_name = label.product_tmpl_id.name
            elif label.product_id and label.product_id.product_tmpl_id:
                item_name = label.product_id.product_tmpl_id.name

            # Values
            pcs = 1
            gross = label.purchase_gross_weight or 0.0
            diamond_g = label.purchase_diamond_weight_gm or 0.0
            diamond_ct = label.purchase_diamond_weight_ct or 0.0
            stone = label.purchase_stone_weight or 0.0
            other = label.other_weight_g or 0.0
            net = label.purchase_net_weight or 0.0

            tot_pcs += pcs
            tot_gross += gross
            tot_diamond_g += diamond_g
            tot_diamond_ct += diamond_ct
            tot_stone += stone
            tot_other += other
            tot_net += net

            # Write data row
            ws1.cell(row=row_idx, column=1, value=receipt_date_str).alignment = align_center
            ws1.cell(row=row_idx, column=2, value=label.name or "").alignment = align_center
            ws1.cell(row=row_idx, column=3, value=item_name or "").alignment = align_left
            ws1.cell(row=row_idx, column=4, value=variety_name or "").alignment = align_left
            ws1.cell(row=row_idx, column=5, value=label.purity_id.name or "").alignment = align_center
            ws1.cell(row=row_idx, column=6, value=label_branches[label.id].name or "").alignment = align_center
            ws1.cell(row=row_idx, column=7, value=label_locations[label.id].name or "").alignment = align_center

            c_pcs = ws1.cell(row=row_idx, column=8, value=pcs)
            c_pcs.alignment = align_right
            c_pcs.number_format = "#,##0"

            c_gross = ws1.cell(row=row_idx, column=9, value=gross)
            c_gross.alignment = align_right
            c_gross.number_format = "#,##0.000"

            c_di_g = ws1.cell(row=row_idx, column=10, value=diamond_g)
            c_di_g.alignment = align_right
            c_di_g.number_format = "#,##0.000"

            c_di_ct = ws1.cell(row=row_idx, column=11, value=diamond_ct)
            c_di_ct.alignment = align_right
            c_di_ct.number_format = "#,##0.00"

            c_stone = ws1.cell(row=row_idx, column=12, value=stone)
            c_stone.alignment = align_right
            c_stone.number_format = "#,##0.000"

            c_other = ws1.cell(row=row_idx, column=13, value=other)
            c_other.alignment = align_right
            c_other.number_format = "#,##0.000"

            c_net = ws1.cell(row=row_idx, column=14, value=net)
            c_net.alignment = align_right
            c_net.number_format = "#,##0.000"

            c_days = ws1.cell(row=row_idx, column=15, value=days)
            c_days.alignment = align_right
            c_days.number_format = "#,##0"

            for col in range(1, 16):
                cell = ws1.cell(row=row_idx, column=col)
                cell.font = font_data
                cell.border = border_all_cells

            row_idx += 1

        # Sheet 1 Totals
        ws1.row_dimensions[row_idx].height = 22
        ws1.cell(row=row_idx, column=4, value="Total").alignment = align_left
        ws1.cell(row=row_idx, column=8, value=tot_pcs).number_format = "#,##0"
        ws1.cell(row=row_idx, column=8).alignment = align_right

        ws1.cell(row=row_idx, column=9, value=tot_gross).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=9).alignment = align_right

        ws1.cell(row=row_idx, column=10, value=tot_diamond_g).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=10).alignment = align_right

        ws1.cell(row=row_idx, column=11, value=tot_diamond_ct).number_format = "#,##0.00"
        ws1.cell(row=row_idx, column=11).alignment = align_right

        ws1.cell(row=row_idx, column=12, value=tot_stone).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=12).alignment = align_right

        ws1.cell(row=row_idx, column=13, value=tot_other).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=13).alignment = align_right

        ws1.cell(row=row_idx, column=14, value=tot_net).number_format = "#,##0.000"
        ws1.cell(row=row_idx, column=14).alignment = align_right

        for col in range(1, 16):
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
            if quant.is_labeled:
                pcs = quant.pcs
                gross = quant.gross
                diamond_g = quant.diamond_g
                diamond_ct = quant.diamond_ct
                stone = quant.stone
                other = quant.other
                net = quant.net
            else:
                # Check UOM Category
                uom_cat = quant.product_id.uom_id.category_id.name
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
            
            variety_name2 = quant.product_id.name or ""
            ws2.cell(row=row_idx2, column=3, value=variety_name2).alignment = align_left
            
            ws2.cell(row=row_idx2, column=4, value=quant.product_id.purity_id.name or "").alignment = align_center
            ws2.cell(row=row_idx2, column=5, value=branch_name).alignment = align_center
            ws2.cell(row=row_idx2, column=6, value=quant.location_id.name or "").alignment = align_center

            c_pcs = ws2.cell(row=row_idx2, column=7, value=pcs)
            c_pcs.alignment = align_right
            c_pcs.number_format = "#,##0"

            c_gross = ws2.cell(row=row_idx2, column=8, value=gross)
            c_gross.alignment = align_right
            c_gross.number_format = "#,##0.000"

            c_di_g = ws2.cell(row=row_idx2, column=9, value=diamond_g)
            c_di_g.alignment = align_right
            c_di_g.number_format = "#,##0.000"

            c_di_ct = ws2.cell(row=row_idx2, column=10, value=diamond_ct)
            c_di_ct.alignment = align_right
            c_di_ct.number_format = "#,##0.00"

            c_stone = ws2.cell(row=row_idx2, column=11, value=stone)
            c_stone.alignment = align_right
            c_stone.number_format = "#,##0.000"

            c_other = ws2.cell(row=row_idx2, column=12, value=other)
            c_other.alignment = align_right
            c_other.number_format = "#,##0.000"

            c_net = ws2.cell(row=row_idx2, column=13, value=net)
            c_net.alignment = align_right
            c_net.number_format = "#,##0.000"

            c_days = ws2.cell(row=row_idx2, column=14, value=days)
            c_days.alignment = align_right
            c_days.number_format = "#,##0"

            for col in range(1, 15):
                cell = ws2.cell(row=row_idx2, column=col)
                cell.font = font_data
                cell.border = border_all_cells

            row_idx2 += 1

        # Sheet 2 Totals
        ws2.row_dimensions[row_idx2].height = 22
        ws2.cell(row=row_idx2, column=3, value="Total").alignment = align_left
        ws2.cell(row=row_idx2, column=7, value=tot_pcs2).number_format = "#,##0"
        ws2.cell(row=row_idx2, column=7).alignment = align_right

        ws2.cell(row=row_idx2, column=8, value=tot_gross2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=8).alignment = align_right

        ws2.cell(row=row_idx2, column=9, value=tot_diamond_g2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=9).alignment = align_right

        ws2.cell(row=row_idx2, column=10, value=tot_diamond_ct2).number_format = "#,##0.00"
        ws2.cell(row=row_idx2, column=10).alignment = align_right

        ws2.cell(row=row_idx2, column=11, value=tot_stone2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=11).alignment = align_right

        ws2.cell(row=row_idx2, column=12, value=tot_other2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=12).alignment = align_right

        ws2.cell(row=row_idx2, column=13, value=tot_net2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=13).alignment = align_right

        for col in range(1, 15):
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
        self.file_name = "Product_Label_Report.xlsx"
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
