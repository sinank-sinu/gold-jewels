from odoo import models, fields, api, _
import math
import base64
from io import BytesIO

from odoo.exceptions import ValidationError, UserError
from odoo.tools import barcode as barcode_tool


class ProductLabel(models.Model):
    _name = 'product.label'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Product Label'
    _rec_names_search = ['name', 'barcode']
    # _rec_name = 'label_name'

    name = fields.Char(string="Label Reference", required=True, copy=False, default="New", tracking=True)
    active = fields.Boolean(
        string='Active',
        default=False,
        tracking=True
    )
    image = fields.Binary(string="Label Image", attachment=True)

    label_number = fields.Char(
        string="Label Number",
    )
    label_name = fields.Char()
    branch_location_id = fields.Many2one(
        'stock.location',
        string='Destination Location',
        domain="[('usage', '=', 'internal'), ('branch_id', '=', branch_id)]",
        tracking=True
    )
    source_location_id = fields.Many2one(
        'stock.location',
        string='Source Location',
        domain="[('usage', '=', 'internal')]",
        tracking=True
    )
    picking_id = fields.Many2one('stock.picking', string="Stock Picking", readonly=True)
    purchase_id = fields.Many2one(
        'purchase.order',
        string="Purchase Order",
        domain="[('state','=','purchase'),('order_line.product_id','=',product_id)]"
    )
    product_id = fields.Many2one(
        'product.product',
        ondelete='cascade',
        tracking=True
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string="Product",
    )
    branch_id = fields.Many2one('res.branch', string='Branch', store=True,
                                readonly=False, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    sale_purity_id = fields.Many2one('gold.purity', string="Sale Purity")
    sale_price_per_gram = fields.Float(string="Sale Rate / gram")
    job_work_id = fields.Many2one(
        'jewellery.job.work',
        string='Job Work',
        ondelete='cascade',
    )
    requisition_id = fields.Many2one("material.purchase.requisition")


    diamond_certificate = fields.Binary(
        string="Diamond Certificate",
        attachment=True
    )
    diamond_certificate_filename = fields.Char(
        string="Certificate File Name"
    )
    sale_gross_weight = fields.Float(string="Sale Gross Weight (g)", digits=(16, 3), tracking=True)
    sale_stone_weight = fields.Float(string="Sale Stone Weight (g)", digits=(16, 3))
    sale_stone_weight_ct = fields.Float(string="Sale Stone Weight (ct)", digits=(12, 4))
    sale_diamond_weight = fields.Float(string="Sale Diamond Weight (g)", digits=(16, 3))

    @api.constrains('sale_gross_weight')
    def _check_sale_gross_weight(self):
        for rec in self:
            if rec.sale_gross_weight <= 0.0:
                raise ValidationError(_("Sale Gross Weight must be greater than 0."))


    sale_net_weight = fields.Float(
        string="Sale Net Weight (g)",
        compute="_compute_sale_net_weight",
        store=True, digits=(16, 3)
    )

    sale_metal_rate = fields.Float(string="Sale Metal Amount")
    sale_stone_rate = fields.Float(string="Sale Stone Amount")
    sale_diamond_rate = fields.Float(string="Sale Diamond Amount")

    sale_making_charge_type = fields.Selection([
        ('percent', 'Percentage'),
        ('amount', 'Amount'),
        ('rate_per_gram', 'Rate per Gram'),
    ], string="Sale Making Charge Type", default='percent')

    sale_making_charge_value = fields.Float(string="Sale Making Charge Max")
    sale_making_charge_min = fields.Float(string="Sale Making Charge Min")

    sale_making_charge_amount = fields.Float(
        string="Sale Making Charge Amount",
        compute="_compute_sale_making_charge",
        store=True
    )
    sale_making_charge_fixed_amount_max = fields.Float(string="Sale Fixed Making Charge Amount Max")
    sale_making_charge_fixed_amount_min = fields.Float(string="Sale Fixed Making Charge Amount Min")

    # =========================
    # PURCHASE JEWELLERY DETAILS
    # =========================
    purity_id = fields.Many2one('gold.purity', string="Purity", tracking=True)
    purchase_price_per_gram = fields.Float(string="Purchase fine Rate / gram", digits=(16, 3))

    purchase_gross_weight = fields.Float(string="Purchase Gross Amount (g)", digits=(16, 3), tracking=True)
    purchase_stone_weight = fields.Float(string="Purchase Stone Weight (g)", digits=(16, 3))
    purchase_stone_weight_ct = fields.Float(string="Purchase Stone Weight (ct)", digits=(12, 4))
    purchase_diamond_weight = fields.Float(string="Purchase Diamond Weight (g)", digits=(16, 3))

    purchase_net_weight = fields.Float(
        string="Purchase Net Weight (g)",
        compute="_compute_purchase_net_weight",
        store=True, digits=(16, 3)
    )

    purchase_metal_rate = fields.Float(
        string="Purchase Metal Amount",
        compute="_compute_purchase_metal_rate",
        store=True,
        readonly=False
    )
    purchase_stone_rate = fields.Float(string="Purchase Stone Amount")
    purchase_diamond_rate = fields.Float(string="Purchase Diamond Amount")

    purchase_making_charge_type = fields.Selection([
        ('percent', 'Percentage'),
        ('amount', 'Amount'),
        ('rate_per_gram', 'Rate per Gram'),
    ], string="Purchase Making Charge Type", default='percent')

    purchase_making_charge_value = fields.Float(string="Purchase Making Charge")

    purchase_making_charge_amount = fields.Float(
        string="Purchase Making Charge Amount",
        compute="_compute_purchase_making_charge",
        store=True
    )
    mc_fine = fields.Float(string="MC Fine", compute="_compute_purchase_mc_fine", digits=(16, 3))
    barcode = fields.Char(
        'Barcode', copy=False, index='btree_not_null',
        help="International Article Number used for product identification.")
    tag_weight = fields.Float(string="Tag Weight (g)")
    sale_fine_weight = fields.Float(string="Fine Weight  (g)", compute="_compute_sale_fine_weight", digits=(16, 3))
    purchase_fine_weight = fields.Float(string="Fine Weight  (g)", compute="_compute_purchase_fine_weight", digits=(16, 3))

    sale_diamond_weight_gm = fields.Float(
        string="Diamond Weight (g)",
        digits=(12, 4)
    )

    sale_diamond_weight_ct = fields.Float(
        string="Diamond Weight (ct)",
        digits=(12, 4)
    )
    purchase_diamond_weight_gm = fields.Float(
        string="Diamond Weight (g)",
        digits=(12, 4)
    )

    purchase_diamond_weight_ct = fields.Float(
        string="Diamond Weight (ct)",
        digits=(12, 4)
    )
    sync_lock = fields.Boolean(default=False)
    is_stocked_in = fields.Boolean(string="Stock Updated", default=False, copy=False, tracking=True)

    unlabelled_weight = fields.Float(
        string="Unlabelled Weight",
        compute="_compute_unlabelled_weight",
        store=False,
    )
    unlabelled_weight_jw = fields.Float(
        string="Unlabelled Weight",
        compute="_compute_unlabelled_weight",
        store=False,
    )



    age = fields.Integer(
        string="Age (Days)",
        compute="_compute_age",
    )

    age_import = fields.Integer(string="Age (Import)", default=0, store=True)

    certification_charge = fields.Float(string="Certification Charge")
    transportation_charge = fields.Float(string="Transportation Charge")
    cargo_charge = fields.Float(string="Cargo Charge")
    others = fields.Float(string="Others")
    stock_move_count = fields.Integer(compute="_compute_stock_move_count")

    other_weight_g = fields.Float(string="Other Weight (g)", digits=(16, 3))
    other_weight_amount = fields.Float(string="Other Weight Amount")

    location_journey = fields.Char(
        string="Journey",
        compute="_compute_location_journey"
    )

    visual_html = fields.Html(
        string="Visual Timeline",
        compute="_compute_visual_html"
    )

    def _compute_visual_html(self):
        for rec in self:
            moves = self.env['stock.move.line'].search(
                [('label_id', '=', rec.id), ('state', '=', 'done')],
                order='date asc, id asc'
            )

            if not moves:
                rec.visual_html = "<div style='text-align:center; padding: 20px; color: #777;'>No tracking history available yet.</div>"
                continue

            def clean_loc_name(loc):
                name = loc.display_name
                if name.startswith('Physical Locations/'):
                    name = name.replace('Physical Locations/', '', 1)
                elif name.startswith('Partner Locations/'):
                    name = name.replace('Partner Locations/', '', 1)
                elif name.startswith('Virtual Locations/'):
                    name = name.replace('Virtual Locations/', '', 1)
                return name

            def get_icon(name):
                name_lower = name.lower()
                if 'ho' in name_lower or 'head office' in name_lower:
                    return 'fa-building'
                elif 'transit' in name_lower or 'trn' in name_lower:
                    return 'fa-truck'
                elif 'branch' in name_lower or 'brc' in name_lower:
                    return 'fa-shopping-cart'
                elif 'vendor' in name_lower or 'partner' in name_lower:
                    return 'fa-industry'
                elif 'customer' in name_lower or 'final' in name_lower:
                    return 'fa-user'
                return 'fa-map-marker'

            stations = []
            first_name = clean_loc_name(moves[0].location_id)
            stations.append({
                'name': first_name,
                'date': moves[0].date.strftime('%d %b %Y, %I:%M %p') if moves[0].date else '',
                'icon': get_icon(first_name),
                'picking_html': ''
            })

            for move in moves:
                dest_loc = clean_loc_name(move.location_dest_id)
                picking = move.picking_id
                picking_html = ""
                if picking:
                    picking_url = f"/web#id={picking.id}&model=stock.picking&view_type=form"
                    picking_html = f"<a href='{picking_url}' target='_blank' style='display: inline-block; margin-top: 5px; font-size: 10px; font-weight: bold; color: #017e84; text-decoration: none; border: 1px solid #017e84; border-radius: 4px; padding: 3px 6px; background-color: #e8f4f8;'>{picking.name}</a>"

                if stations[-1]['name'] != dest_loc:
                    stations.append({
                        'name': dest_loc,
                        'date': move.date.strftime('%d %b %Y, %I:%M %p') if move.date else '',
                        'icon': get_icon(dest_loc),
                        'picking_html': picking_html
                    })
                else:
                    if picking_html and picking_html not in stations[-1].get('picking_html', ''):
                        if stations[-1]['picking_html']:
                            stations[-1]['picking_html'] += "<div style='margin-top: 3px;'></div>" + picking_html
                        else:
                            stations[-1]['picking_html'] = picking_html

            # Check if sold
            is_sold = not rec.active or (moves and moves[-1].location_dest_id.usage == 'customer')
            
            invoice_html = ''
            if is_sold:
                invoice_line = self.env['account.move.line'].sudo().search([
                    ('label_id', '=', rec.id),
                    ('move_id.move_type', '=', 'out_invoice'),
                    ('move_id.state', '!=', 'cancel')
                ], limit=1, order='id desc')
                
                if invoice_line:
                    invoice = invoice_line.move_id
                    inv_date = invoice.invoice_date.strftime('%d %b %Y') if invoice.invoice_date else ''
                    inv_time = invoice.create_date.strftime('%I:%M %p') if invoice.create_date else ''
                    inv_url = f"/web#id={invoice.id}&model=account.move&view_type=form"
                    invoice_html = f"<a href='{inv_url}' target='_blank' style='display: inline-block; margin-top: 5px; font-size: 10px; font-weight: bold; color: #d9534f; text-decoration: none; border: 1px solid #d9534f; border-radius: 4px; padding: 3px 6px; background-color: #fdf0f0;'>{invoice.name}</a><br/><span style='font-size:10px; color:#777;'>{inv_date} {inv_time}</span>"
                else:
                    sale_line = self.env['sale.order.line'].sudo().search([
                        ('label_id', '=', rec.id),
                        ('order_id.state', 'in', ['sale', 'done'])
                    ], limit=1, order='id desc')
                    if sale_line:
                        sale = sale_line.order_id
                        inv_date = sale.date_order.strftime('%d %b %Y') if sale.date_order else ''
                        inv_time = sale.date_order.strftime('%I:%M %p') if sale.date_order else ''
                        sale_url = f"/web#id={sale.id}&model=sale.order&view_type=form"
                        invoice_html = f"<a href='{sale_url}' target='_blank' style='display: inline-block; margin-top: 5px; font-size: 10px; font-weight: bold; color: #d9534f; text-decoration: none; border: 1px solid #d9534f; border-radius: 4px; padding: 3px 6px; background-color: #fdf0f0;'>{sale.name}</a><br/><span style='font-size:10px; color:#777;'>{inv_date} {inv_time}</span>"

                stations.append({
                    'name': 'SOLD',
                    'date': '',
                    'icon': 'fa-shopping-bag',
                    'picking_html': invoice_html,
                    'is_sold_node': True
                })

            html = """
            <div style="background: linear-gradient(to right bottom, #ffffff, #f4f6f9); padding: 25px 15px; border: 1px solid #e1e5eb; border-radius: 12px; margin-bottom: 25px; overflow-x: auto; box-shadow: 0 4px 20px rgba(0,0,0,0.03); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                <div style="display: flex; justify-content: flex-start; align-items: flex-start; position: relative; width: max-content; margin: 0 auto;">
                    <div style="position: absolute; top: 17px; left: 75px; width: calc(100% - 150px); height: 4px; background-color: #5cb85c; z-index: 1; border-radius: 2px;"></div>
            """

            for index, station in enumerate(stations):
                color = "#d9534f" if station.get('is_sold_node') else "#5cb85c"
                check_icon = "fa-star" if station.get('is_sold_node') else "fa-check"
                shadow_color = "rgba(217, 83, 79, 0.2)" if station.get('is_sold_node') else "rgba(92, 184, 92, 0.2)"
                
                html += f"""
                    <div style="position: relative; z-index: 2; display: flex; flex-direction: column; align-items: center; width: 150px; padding: 0 5px; box-sizing: border-box; transition: transform 0.2s;" onmouseover="this.style.transform='translateY(-3px)'" onmouseout="this.style.transform='none'">
                        <div style="width: 34px; height: 34px; background-color: {color}; color: white; border-radius: 50%; display: flex; justify-content: center; align-items: center; font-size: 15px; margin-bottom: 12px; box-shadow: 0 0 0 4px white, 0 4px 10px {shadow_color};"><i class='fa {check_icon}'></i></div>
                        <div style="width: 48px; height: 48px; background-color: white; border: 1px solid #e1e5eb; border-radius: 12px; display: flex; justify-content: center; align-items: center; font-size: 20px; color: #495057; margin-bottom: 12px; box-shadow: 0 6px 16px rgba(0,0,0,0.06);"><i class='fa {station['icon']}'></i></div>
                        <div style="text-align: center; font-weight: 600; color: {color}; font-size: 13px; word-wrap: break-word; margin-bottom: 6px; padding: 0 4px; line-height: 1.2;">{station['name']}</div>
                        <div style="text-align: center; color: #6c757d; font-size: 11px; font-weight: 500; margin-bottom: 8px;">{station['date']}</div>
                        <div style="text-align: center; width: 100%;">{station['picking_html']}</div>
                    </div>
                """

            html += "</div></div>"
            rec.visual_html = html

    def _compute_location_journey(self):
        for rec in self:
            moves = self.env['stock.move.line'].search(
                [('label_id', '=', rec.id), ('state', '=', 'done')],
                order='date asc, id asc'
            )
            if not moves:
                rec.location_journey = "New"
                continue
                
            stations = []
            
            def clean_loc_name(loc):
                name = loc.display_name
                if name.startswith('Physical Locations/'):
                    name = name.replace('Physical Locations/', '', 1)
                elif name.startswith('Partner Locations/'):
                    name = name.replace('Partner Locations/', '', 1)
                elif name.startswith('Virtual Locations/'):
                    name = name.replace('Virtual Locations/', '', 1)
                return name
                
            first_loc = clean_loc_name(moves[0].location_id)
            stations.append(first_loc)
            
            for move in moves:
                dest_loc = clean_loc_name(move.location_dest_id)
                if not stations or stations[-1] != dest_loc:
                    stations.append(dest_loc)
                    
            rec.location_journey = " ➔ ".join(stations)

    def action_view_tracker(self):
        """Method to open the visual tracker wizard."""
        self.ensure_one()
        moves = self.env['stock.move'].search([('label_id', '=', self.id)])
        wizard = self.env['label.tracker.wizard'].create({
            'label_id': self.id,
            'move_ids': [(6, 0, moves.ids)]
        })
        return {
            'name': 'Journey Tracker',
            'type': 'ir.actions.act_window',
            'res_model': 'label.tracker.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }



    @api.depends('purchase_id', 'job_work_id', 'sale_gross_weight')
    def _compute_unlabelled_weight(self):
        for rec in self:
            rec.unlabelled_weight = 0.0
            rec.unlabelled_weight_jw = 0.0

            if rec.purchase_id:
                po = rec.purchase_id
                # Deduct all other labels on this PO, then deduct current label's live weight
                other_labels = po.label_ids - rec
                total_other = sum(other_labels.mapped('sale_gross_weight'))
                rec.unlabelled_weight = po.total_weight - total_other - (rec.sale_gross_weight or 0.0)

            if rec.job_work_id:
                jw = rec.job_work_id
                # Deduct all other labels on this Job Work, then deduct current label's live weight
                other_labels = jw.jw_label_ids - rec
                total_other = sum(other_labels.mapped('sale_gross_weight'))
                rec.unlabelled_weight_jw = jw.total_weight - total_other - (rec.sale_gross_weight or 0.0)


    def _compute_stock_move_count(self):
        for rec in self:
            rec.stock_move_count = self.env['stock.move'].search_count([('label_id', '=', rec.id)])

    # un comment the code if import the product label
    @api.depends('age_import', 'create_date')
    def _compute_age(self):
        today = fields.Date.today()
        for rec in self:
            days_since_creation = (today - rec.create_date.date()).days if rec.create_date else 0
            if rec.age_import != 0:
                rec.age = rec.age_import + days_since_creation
            else:
                rec.age = days_since_creation + 1

    # comment this code for import age days
    # @api.depends('create_date')
    # def _compute_age(self):
    #     today = fields.Date.today()
    #     for rec in self:
    #         if rec.create_date:
    #             created_date = rec.create_date.date()
    #             rec.age = (today - created_date).days+1
    #         else:
    #             rec.age = 0

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.image = self.product_id.image_1920

    def action_set_active(self):
        self.ensure_one()
        self.active = True

    def action_stock_in(self):
        """Method to stock in the product based on label details using internal transfer."""
        self.ensure_one()
        if not self.branch_location_id:
            raise ValidationError("Please select a Branch Location before stocking in.")
        if not self.product_id:
            raise ValidationError("Product is missing on this label.")
        if not self.source_location_id:
            raise ValidationError("Please select a Source Location before stocking in.")

        # Find official internal picking type for the source location's warehouse or branch
        picking_type = False
        warehouse = self.source_location_id.warehouse_id or self.env['stock.warehouse'].search([('lot_stock_id', 'parent_of', self.source_location_id.id)], limit=1)
        if not warehouse and self.source_location_id.location_id:
            warehouse = self.env['stock.warehouse'].search([('lot_stock_id', 'parent_of', self.source_location_id.location_id.id)], limit=1)
        if not warehouse and self.branch_id and hasattr(self.branch_id, 'warehouse_id') and self.branch_id.warehouse_id:
            warehouse = self.branch_id.warehouse_id
        if warehouse and warehouse.int_type_id:
            picking_type = warehouse.int_type_id
        elif warehouse:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('warehouse_id', '=', warehouse.id)
            ], limit=1)

        if not picking_type:
            company_id = self.company_id.id or self.branch_id.company_id.id or self.env.company.id
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('company_id', '=', company_id)
            ], limit=1)

        if not picking_type:
            # Fallback to standard ref if search fails
            try:
                picking_type = self.env.ref('stock.picking_type_internal')
            except ValueError:
                raise ValidationError("Internal transfer picking type not found.")

        picking_company_id = self.company_id.id or (picking_type.company_id.id if picking_type else self.env.company.id)

        picking = self.env['stock.picking'].with_context(skip_label_location_overwrite=True).create({
            'picking_type_id': picking_type.id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.branch_location_id.id,
            'origin': self.name,
            'branch_id': self.branch_id.id,
            'company_id': picking_company_id,
        })

        self.env['stock.move'].with_context(skip_label_location_overwrite=True).create({
            'name': f"Stock In: {self.name}",
            'product_id': self.product_id.id,
            'product_uom_qty': self.purchase_gross_weight or 1.0,
            'product_uom': self.product_id.uom_id.id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.branch_location_id.id,
            'picking_id': picking.id,
            'label_id': self.id,
            'purity_id': self.purity_id.id if self.purity_id else False,
            'branch_id': self.branch_id.id,
            'company_id': picking_company_id,
        })

        # Process and validate the picking
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            if round(move.quantity, 3) < round(move.product_uom_qty, 3):
                raise ValidationError(f"Not enough stock available in '{self.source_location_id.display_name}'. Requested: {move.product_uom_qty}, Available: {move.quantity}")
        #
        # for move_line in picking.move_line_ids:
        #     # Reverting to Odoo 17 standard 'quantity' field
        #     move_line.quantity = move_line.move_id.product_uom_qty
        
        picking.button_validate()

        self.picking_id = picking.id
        self.is_stocked_in = True

        return {
            'effect': {
                'fadeout': 'slow',
                'message': f"Internal transfer completed for {self.purchase_gross_weight or 1.0} {self.product_id.uom_id.name}",
                'type': 'rainbow_man',
            }
        }

    def action_view_picking(self):
        """Method to view the linked stock picking."""
        self.ensure_one()
        if not self.picking_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.picking_id.id,
            'target': 'current',
        }

    @api.onchange('job_work_id')
    def _onchange_job_work_source_location(self):
        if self.job_work_id and self.job_work_id.job_worker_id:
            worker_location = self.job_work_id.job_worker_id.property_stock_supplier
            if worker_location and worker_location.usage == 'internal':
                self.source_location_id = worker_location.id


    @api.onchange('sale_diamond_weight_ct')
    def _onchange_sale_diamond_weight_ct(self):
        if self.sale_diamond_weight_ct:
            self.sale_diamond_weight_gm = self.sale_diamond_weight_ct * 0.2
        else:
            self.sale_diamond_weight_gm = 0.0

    @api.onchange('sale_diamond_weight_gm')
    def _onchange_sale_diamond_weight_gm(self):
        if self.sale_diamond_weight_gm:
            self.sale_diamond_weight_ct = self.sale_diamond_weight_gm / 0.2
        else:
            self.sale_diamond_weight_ct = 0.0

    @api.onchange('purchase_diamond_weight_ct')
    def _onchange_purchase_diamond_weight_ct(self):
        if self.purchase_diamond_weight_ct:
            self.purchase_diamond_weight_gm = self.purchase_diamond_weight_ct * 0.2
        else:
            self.purchase_diamond_weight_gm = 0.0

    @api.onchange('purchase_diamond_weight_gm')
    def _onchange_purchase_diamond_weight_gm(self):
        if self.purchase_diamond_weight_gm:
            self.purchase_diamond_weight_ct = self.purchase_diamond_weight_gm / 0.2
        else:
            self.purchase_diamond_weight_ct = 0.0

    @api.onchange('sale_stone_weight_ct')
    def _onchange_sale_stone_weight_ct(self):
        if self.sale_stone_weight_ct:
            self.sale_stone_weight = self.sale_stone_weight_ct * 0.2
        else:
            self.sale_stone_weight = 0.0

    @api.onchange('sale_stone_weight')
    def _onchange_sale_stone_weight(self):
        if self.sale_stone_weight:
            self.sale_stone_weight_ct = self.sale_stone_weight / 0.2
        else:
            self.sale_stone_weight_ct = 0.0

    @api.onchange('purchase_stone_weight_ct')
    def _onchange_purchase_stone_weight_ct(self):
        if self.purchase_stone_weight_ct:
            self.purchase_stone_weight = self.purchase_stone_weight_ct * 0.2
        else:
            self.purchase_stone_weight = 0.0

    @api.onchange('purchase_stone_weight')
    def _onchange_purchase_stone_weight(self):
        if self.purchase_stone_weight:
            self.purchase_stone_weight_ct = self.purchase_stone_weight / 0.2
        else:
            self.purchase_stone_weight_ct = 0.0

    # =========================
    # COMPUTES
    # =========================
    @api.depends(
        'sale_gross_weight',
        'sale_stone_weight',
        'sale_diamond_weight_gm'
    )
    def _compute_sale_net_weight(self):
        for rec in self:
            rec.sale_net_weight = (
                    rec.sale_gross_weight
                    - rec.sale_stone_weight
                    - rec.sale_diamond_weight_gm
            )
            # rec.sale_net_weight = rec.sale_net_weight*rec.purity_id.percentage

    @api.depends('sale_net_weight','purity_id')
    def _compute_sale_fine_weight(self):
        for rec in self:
            rec.sale_fine_weight = rec.sale_net_weight * (rec.purity_id.percentage)/100

    @api.depends('purchase_net_weight', 'purchase_making_charge_type','purchase_making_charge_amount')
    def _compute_purchase_mc_fine(self):
        for rec in self:
            if rec.purchase_making_charge_type == 'percent':
                rec.mc_fine = rec.purchase_net_weight * (rec.purchase_making_charge_value) / 100
            elif rec.purchase_making_charge_type == 'amount':
                rec.mc_fine = 0.0
                rec.purchase_making_charge_amount = rec.purchase_making_charge_value
            else:
                rec.mc_fine = 0.0
    @api.depends(
        'purchase_gross_weight',
        'purchase_stone_weight',
        'purchase_diamond_weight_gm',
    )
    def _compute_purchase_net_weight(self):
        for rec in self:
            rec.purchase_net_weight = (
                    rec.purchase_gross_weight
                    - rec.purchase_stone_weight
                    - rec.purchase_diamond_weight_gm
            )

    @api.depends('purchase_net_weight','purity_id')
    def _compute_purchase_fine_weight(self):
        for rec in self:
            rec.purchase_fine_weight = rec.purchase_net_weight * (rec.purity_id.percentage)/100



    @api.depends(
        'sale_making_charge_type',
        'sale_making_charge_value',
        'sale_net_weight',
        'sale_metal_rate'
    )
    def _compute_sale_making_charge(self):
        for rec in self:
            if rec.sale_making_charge_type == 'percent':
                rec.sale_making_charge_amount = rec.sale_net_weight * (rec.sale_making_charge_value) / 100
            elif rec.sale_making_charge_type == 'rate_per_gram':
                rec.sale_making_charge_amount = rec.sale_net_weight * rec.sale_making_charge_value


    @api.depends(
        'purchase_making_charge_type',
        'purchase_making_charge_value',
        'purchase_net_weight',
        'purchase_metal_rate'
    )
    def _compute_purchase_making_charge(self):
        for rec in self:
            if rec.purchase_making_charge_type == 'percent':
                rec.purchase_making_charge_amount = rec.mc_fine* rec.purchase_price_per_gram
            elif rec.purchase_making_charge_type == 'amount':
                rec.purchase_making_charge_amount = rec.purchase_making_charge_value
            elif rec.purchase_making_charge_type == 'rate_per_gram':
                 rec.purchase_making_charge_amount = rec.purchase_net_weight*rec.purchase_making_charge_value

    @api.onchange('product_id')
    def _onchange_product_id_set_template(self):
        for rec in self:
            if rec.product_id:
                rec.product_tmpl_id = rec.product_id.product_tmpl_id
            else:
                rec.product_tmpl_id = False

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id_set_template(self):
        for rec in self:
            if rec.product_tmpl_id:
                rec.product_id = rec.product_tmpl_id
            else:
                rec.product_id = False

    @api.model_create_multi
    def create(self, vals_list):
        """Function to add EAN13 Standard barcode at the time
        create new product"""
        for vals in vals_list:
            if vals.get('name', "New") == "New":
                vals['name'] = self.env['ir.sequence'].next_by_code('product.label') or "New"
        res_list = super(ProductLabel, self).create(vals_list)
        for res in res_list:
            ean = generate_ean(str(res.id))
            res.barcode = '21' + ean[2:]
    
            if res.purchase_id:
                res.purchase_id.sudo()._compute_total_labelled()
                res.purchase_id.sudo()._compute_unlabelled_totals()
            if res.job_work_id:
                res.purchase_id.sudo()._compute_total_labelled()
                res.purchase_id.sudo()._compute_unlabelled_totals()
    
        return res_list

    @api.depends('purchase_price_per_gram', 'purchase_fine_weight')
    def _compute_purchase_metal_rate(self):
        for rec in self:
            if rec.purchase_price_per_gram:
                rec.purchase_metal_rate = rec.purchase_price_per_gram * rec.purchase_fine_weight

    # -------------------------------------------------
    # Sync Sale & Purchase fields (two-way)
    # -------------------------------------------------



    @api.onchange(
        'sale_gross_weight',
        'sale_stone_weight',
        'sale_stone_weight_ct',
        'sale_diamond_weight_gm',
        'sale_stone_rate',
        'sale_diamond_rate'
    )
    def _onchange_sale_sync_purchase(self):
        for rec in self:
            if rec.sync_lock:
                return

            rec.sync_lock = True

            rec.purchase_gross_weight = rec.sale_gross_weight
            rec.purchase_stone_weight = rec.sale_stone_weight
            rec.purchase_stone_weight_ct = rec.sale_stone_weight_ct
            rec.purchase_diamond_weight_gm = rec.sale_diamond_weight_gm

            # rec.purchase_stone_rate = rec.sale_stone_rate
            # rec.purchase_diamond_rate = rec.sale_diamond_rate

            rec.sync_lock = False

    @api.onchange(
        'purchase_gross_weight',
        'purchase_stone_weight',
        'purchase_stone_weight_ct',
        'purchase_diamond_weight_gm',
        'purchase_stone_rate',
        'purchase_diamond_rate'
    )
    def _onchange_purchase_sync_sale(self):
        for rec in self:
            if rec.sync_lock:
                return

            rec.sync_lock = True

            rec.sale_gross_weight = rec.purchase_gross_weight
            rec.sale_stone_weight = rec.purchase_stone_weight
            rec.sale_stone_weight_ct = rec.purchase_stone_weight_ct
            rec.sale_diamond_weight_gm = rec.purchase_diamond_weight_gm

            # rec.sale_stone_rate = rec.purchase_stone_rate
            # rec.sale_diamond_rate = rec.purchase_diamond_rate

            rec.sync_lock = False

    def write(self, vals):
        res = super().write(vals)

        if 'sale_gross_weight' in vals or 'purchase_id' in vals or 'job_work_id' in vals:
            purchases = self.mapped('purchase_id')
            if purchases:
                purchases._compute_total_labelled()
                purchases._compute_unlabelled_totals()
            job_work = self.mapped('job_work_id')
            if job_work:
                job_work._compute_total_labelled()
                job_work._compute_unlabelled_totals()

        return res

    @api.onchange('purchase_id')
    def _onchange_purchase_product(self):
        if self.purchase_id and self.product_id:
            line = self.purchase_id.order_line.filtered(
                lambda l: l.product_id.id == self.product_id.id
            )
            if line:
                line = line[0]  # take first matching line
                self.purchase_making_charge_type = line.purchase_making_charge_type
                if line.purchase_making_charge_type == 'percent':
                    self.purchase_making_charge_value = line.mc_percent
                elif line.purchase_making_charge_type == 'amount':
                    self.purchase_making_charge_value = line.purchase_making_charge_value
                elif line.purchase_making_charge_type == 'rate_per_gram':
                    self.purchase_making_charge_value = line.rate_value
                self.purchase_metal_rate = line.metal_amount
            else:
                self.purchase_making_charge_value = 0
                self.purchase_metal_rate = 0


def ean_checksum(eancode):
    """Returns the checksum of an ean string of length 13, returns -1 if
    the string has the wrong length"""
    if len(eancode) != 13:
        return -1
    odd_sum = 0
    even_sum = 0
    for rec in range(len(eancode[::-1][1:])):
        if rec % 2 == 0:
            odd_sum += int(eancode[::-1][1:][rec])
        else:
            even_sum += int(eancode[::-1][1:][rec])
    total = (odd_sum * 3) + even_sum
    return int(10 - math.ceil(total % 10.0)) % 10


def check_ean(eancode):
    """Returns True if ean code is a valid ean13 string, or null"""
    if not eancode:
        return True
    if len(eancode) != 13:
        return False
    try:
        int(eancode)
    except:
        return False
    return ean_checksum(eancode)


def generate_ean(ean):
    """Creates and returns a valid ean13 from an invalid one"""
    if not ean:
        return "0000000000000"
    product_identifier = '00000000000' + ean
    ean = product_identifier[-11:]
    check_number = check_ean(ean + '00')
    return f'{ean}0{check_number}'




