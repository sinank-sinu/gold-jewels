from odoo import models, fields, _, api
from odoo.exceptions import ValidationError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    sale_id = fields.Many2one(
        'sale.order',
        string='Related Sale Order'
    )
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', help="Pricelist for current order.")

    is_old_gold = fields.Boolean(
        string='Old Gold Purchase',
        default=False
    )
    is_sale_return_po = fields.Boolean(
        string='Sale Return',
        default=False
    )
    is_sale_return_shop = fields.Boolean(
        string='Sale Return Shop',
        default=False
    )
    unfix = fields.Boolean(
        string='Unfix',
        default=False
    )
    total_weight = fields.Float(
        string="Total Weight",
        compute="_compute_totals",
        store=True
    )

    total_labelled = fields.Float(
        string="Total Labelled",
        compute="_compute_total_labelled",
        store=True,
        compute_sudo=True,
    )

    total_unlabelled = fields.Float(
        string="Total Unlabelled",
        compute="_compute_unlabelled_totals",
        store=True,
        compute_sudo=True,
    )
    label_ids = fields.One2many(
        'product.label',
        'purchase_id',
        string="Labels"
    )

    @api.onchange('is_old_gold')
    def _onchange_is_old_gold(self):
        if self.is_old_gold:
            self.unfix = False
            self.is_sale_return_shop = False

    @api.onchange('unfix')
    def _onchange_unfix(self):
        if self.unfix:
            self.is_old_gold = False
            self.is_sale_return_shop = False

    @api.onchange('is_sale_return_po')
    def _onchange_is_sale_return_po(self):
        if self.is_sale_return_po:
            self.is_old_gold = False
            self.unfix = False
            self.is_sale_return_shop = False

    @api.onchange('is_sale_return_shop')
    def _onchange_is_sale_return_shop(self):
        if self.is_sale_return_shop:
            self.is_old_gold = False
            self.unfix = False


    def action_create_sale_order(self):
        self.ensure_one()

        SaleOrder = self.env['sale.order']

        # 🔹 Check if already created
        existing_so = SaleOrder.search([
            ('purchase_order_id', '=', self.id)
        ], limit=1)

        if existing_so:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Sale Order',
                'res_model': 'sale.order',
                'res_id': existing_so.id,
                'view_mode': 'form',
                'target': 'current',
            }

        # 🔹 Prepare order line
        product = self.env.ref('em_jewellery_management.product_bullion_gold')

        total_weight = sum(
            self.order_line.mapped('qty_received')
        )
        total_fine = sum(
            self.order_line.mapped('total_fine')
        )
        

        order_lines = [(0, 0, {
            'product_id': product.id,
            # 'product_uom_qty': total_fine,
            'fine_weight': total_fine,
            'name': product.display_name,
            'price_unit': product.list_price or 0.0,
        })]

        # 🔹 Create Sale Order
        sale_order = SaleOrder.create({
            'purchase_order_id': self.id,
            'origin': self.name,
            'partner_id': self.partner_id.id,
            'order_line': order_lines,
            'unfix': self.unfix,
        })
        self.sale_id = sale_order.id

        # 🔹 Open created order
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sale Order',
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.depends(
        'order_line.qty_received',
    )
    def _compute_totals(self):
        for order in self:
            order.total_weight = sum(
                order.order_line.mapped('qty_received')
            )

    @api.depends('label_ids.sale_gross_weight')
    def _compute_total_labelled(self):
        for order in self:
            order.total_labelled = sum(
                order.label_ids.mapped('sale_gross_weight')
            )

    @api.depends(
        'total_labelled',
        'total_weight'
    )
    def _compute_unlabelled_totals(self):
        for order in self:

            order.total_unlabelled = order.total_weight - order.total_labelled

    def button_confirm(self):
        res = super(PurchaseOrder, self).button_confirm()
        if self.is_old_gold:
            for order in self:
                location = self.env.user.branch_id.old_gold_location_id


            # ------------------------------------------------
            # 1️⃣ CREATE OLD GOLD PURCHASE (LOGICAL RECORD)
            # ------------------------------------------------
                self.env['old.gold.purchase'].with_context(skip_old_gold_amount_compute=True).create({
                    'partner_id': order.partner_id.id,
                    'date': fields.Date.today(),
                    'branch_location_id': location.id,
                    'purchase_order_id': order.id,
                    'branch_id': self.env.user.branch_id.id,
                    'old_gold_line_ids': [
                        (0, 0, {
                            'purity_id': l.purity_id.id,
                            'gross_weight': l.product_qty,
                            'stone_weight': l.stone_weight,
                            'amount': l.price_subtotal,
                            'rate':l.price_unit,
                        }) for l in order.order_line
                    ],
                })
    def _prepare_picking(self):
        vals = super()._prepare_picking()
        vals['branch_id'] = self.branch_id.id
        return vals

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals['unfix'] = self.unfix
        return vals

    def action_create_bill_and_pay(self):
        for order in self:

            # 1️⃣ Create Vendor Bill
            action = order.action_create_invoice()

            # Get created bill
            bill = order.invoice_ids.filtered(lambda m: m.state == 'draft')


            if not bill:
                continue
            bill.invoice_date = fields.Date.context_today(self)
            bill.date = fields.Date.context_today(self)
            # 2️⃣ Post Bill
            bill.action_post()

        return True
