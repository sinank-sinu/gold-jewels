from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from io import BytesIO
import base64
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

class ProductLabelReportWizard(models.TransientModel):
    _name = "product.label.report.wizard"
    _description = "Product Label Report Wizard"

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

    start_datetime = fields.Datetime(string="From Date & Time", required=True, default=_default_start_datetime)
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
        locations = self.env['stock.location'].search(loc_domain)
        loc_ids = locations.ids

        # 2. Query stock quants with quantity > 0 in those locations
        quants = self.env['stock.quant'].search([
            ('location_id', 'in', loc_ids),
            ('quantity', '>', 0)
        ])
        product_ids = quants.mapped('product_id').ids

        # 3. Query active product labels in stock (locations & branches) matching start_datetime filter
        labels_domain = [
            ('active', '=', True),
            ('product_id', 'in', product_ids),
            ('branch_location_id', 'in', loc_ids),
            ('create_date', '>=', self.start_datetime)
        ]
        if self.branch_ids:
            labels_domain.append(('branch_id', 'in', self.branch_ids.ids))
        labels = self.env['product.label'].search(labels_domain)

        # 4. Filter out unlabeled quants (where product is not in the active labels list)
        labeled_product_ids = labels.mapped('product_id').ids
        unlabeled_quants = quants.filtered(lambda q: q.product_id.id not in labeled_product_ids)

        # Apply date filter on unlabeled quants using in_date or create_date
        unlabeled_quants = unlabeled_quants.filtered(lambda q:
            (q.in_date and q.in_date >= self.start_datetime) or
            (q.create_date and q.create_date >= self.start_datetime) or
            (not q.in_date and not q.create_date)
        )

        # Create Excel Workbook
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

        headers = [
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

        # Branch name header text
        branch_name_text = ", ".join(self.branch_ids.mapped('name')) if self.branch_ids else "All Branches"
        local_start_dt = fields.Datetime.context_timestamp(self, self.start_datetime)
        start_date_str = local_start_dt.strftime('%d-%b-%y %I:%M:%S %p')
        today_str = today.strftime('%d-%b-%y')

        def setup_sheet_headers(ws, title_text):
            # Row 1
            ws.cell(row=1, column=2, value=title_text).font = font_total
            ws.cell(row=1, column=4, value=branch_name_text).font = font_total

            # Row 2
            ws.cell(row=2, column=2, value="Period From").font = font_total
            ws.cell(row=2, column=3, value=start_date_str).font = font_data
            ws.cell(row=2, column=4, value="To").font = font_total
            ws.cell(row=2, column=5, value=today_str).font = font_data

            # Row 3 - Table headers
            ws.row_dimensions[3].height = 25
            for col_idx, header in enumerate(headers, start=1):
                cell = ws.cell(row=3, column=col_idx, value=header)
                cell.font = font_header
                cell.alignment = align_center
                cell.border = border_header_row

        # ==========================================
        # SHEET 1: Label Closing Stock Report
        # ==========================================
        ws1 = wb.active
        ws1.title = "Label Closing Stock Report"
        setup_sheet_headers(ws1, "Closing Stock Label Wise")

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
            days = (today - receipt_date_val).days + 1
            if days < 0:
                days = 0

            # Variety Name
            variety_name = ""
            ptavs = label.product_template_attribute_value_ids or label.product_id.product_template_attribute_value_ids
            for ptav in ptavs:
                attr_name = ptav.attribute_id.name.strip().lower()
                if attr_name in ('variety', 'verity'):
                    variety_name = ptav.product_attribute_value_id.name
                    break

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
            ws1.cell(row=row_idx, column=6, value=label.branch_id.name or "").alignment = align_center
            ws1.cell(row=row_idx, column=7, value=label.branch_location_id.name or "").alignment = align_center

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
        # SHEET 2: Unlabeled Closing Stock
        # ==========================================
        ws2 = wb.create_sheet(title="Unlabeled Closing Stock")
        setup_sheet_headers(ws2, "Closing Stock Unlabeled Wise")

        row_idx2 = 4
        tot_pcs2 = 0
        tot_gross2 = 0.0
        tot_net2 = 0.0

        for quant in unlabeled_quants:
            ws2.row_dimensions[row_idx2].height = 20

            # Receipt Date
            receipt_date_val = get_date_from_val(quant.in_date) or get_date_from_val(quant.create_date) or today
            receipt_date_str = receipt_date_val.strftime('%d-%b-%y')

            # Aging Days
            days = (today - receipt_date_val).days + 1
            if days < 0:
                days = 0

            # Branch Name
            branch_name = quant.location_id.branch_id.name or quant.location_id.warehouse_id.name or ""

            # Check UOM Category
            uom_cat = quant.product_id.uom_id.category_id.name
            if uom_cat in ('Unit', 'Working Time'):
                pcs = int(quant.quantity)
                gross = quant.quantity * (quant.product_id.weight or 0.0)
            else:
                pcs = 0
                gross = quant.quantity

            net = gross  # For unlabeled weight fallback

            tot_pcs2 += pcs
            tot_gross2 += gross
            tot_net2 += net

            # Write data row
            ws2.cell(row=row_idx2, column=1, value=receipt_date_str).alignment = align_center
            ws2.cell(row=row_idx2, column=2, value="").alignment = align_center  # Label No is blank
            ws2.cell(row=row_idx2, column=3, value=quant.product_id.name or "").alignment = align_left
            ws2.cell(row=row_idx2, column=4, value="").alignment = align_left  # Variety Name is blank
            ws2.cell(row=row_idx2, column=5, value=quant.product_id.purity_id.name or "").alignment = align_center
            ws2.cell(row=row_idx2, column=6, value=branch_name).alignment = align_center
            ws2.cell(row=row_idx2, column=7, value=quant.location_id.name or "").alignment = align_center

            c_pcs = ws2.cell(row=row_idx2, column=8, value=pcs)
            c_pcs.alignment = align_right
            c_pcs.number_format = "#,##0"

            c_gross = ws2.cell(row=row_idx2, column=9, value=gross)
            c_gross.alignment = align_right
            c_gross.number_format = "#,##0.000"

            # Diamond, Stone, and Other Weights are empty on Sheet 2
            ws2.cell(row=row_idx2, column=10, value="")
            ws2.cell(row=row_idx2, column=11, value="")
            ws2.cell(row=row_idx2, column=12, value="")
            ws2.cell(row=row_idx2, column=13, value="")

            c_net = ws2.cell(row=row_idx2, column=14, value=net)
            c_net.alignment = align_right
            c_net.number_format = "#,##0.000"

            c_days = ws2.cell(row=row_idx2, column=15, value=days)
            c_days.alignment = align_right
            c_days.number_format = "#,##0"

            for col in range(1, 16):
                cell = ws2.cell(row=row_idx2, column=col)
                cell.font = font_data
                cell.border = border_all_cells

            row_idx2 += 1

        # Sheet 2 Totals
        ws2.row_dimensions[row_idx2].height = 22
        ws2.cell(row=row_idx2, column=4, value="Total").alignment = align_left
        ws2.cell(row=row_idx2, column=8, value=tot_pcs2).number_format = "#,##0"
        ws2.cell(row=row_idx2, column=8).alignment = align_right

        ws2.cell(row=row_idx2, column=9, value=tot_gross2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=9).alignment = align_right

        ws2.cell(row=row_idx2, column=10, value="")
        ws2.cell(row=row_idx2, column=11, value="")
        ws2.cell(row=row_idx2, column=12, value="")
        ws2.cell(row=row_idx2, column=13, value="")

        ws2.cell(row=row_idx2, column=14, value=tot_net2).number_format = "#,##0.000"
        ws2.cell(row=row_idx2, column=14).alignment = align_right

        for col in range(1, 16):
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
