from odoo import models, fields,api


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    product_template_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='po_line_ptav_rel',
        string="Product Attribute Values",
        ondelete='restrict'
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='po_line_no_variant_ptav_rel',
        string="Extra Product Attribute Values",
        ondelete='restrict'
    )
    product_custom_attribute_value_ids = fields.Many2many(
        comodel_name='product.attribute.custom.value',
        relation='po_line_custom_ptav_rel',
        string="Custom Product Attribute Values"
    )
    is_configurable_product = fields.Boolean(
        string="Is the product configurable?",
        related='product_template_id.has_configurable_attributes'
    )
    product_type = fields.Selection(
        related='product_id.detailed_type'
    )
    pricelist_id = fields.Many2one(
        related='order_id.pricelist_id',
        string='Pricelist',
        readonly=True
    )
    product_uom_qty = fields.Float(
        related='product_qty',
        string="Product Quantity",
        readonly=False,
        digits=(16, 3),
    )

    sale_return_line_id = fields.Many2one('sale.return.line', string="Sale Return Line", ondelete='set null')
    purity_id = fields.Many2one('gold.purity', string="Purity")
    fine_weight = fields.Float(string="Fine Weight  (g)",compute="_compute_fine_weight",digits=(16, 3))
    metal_amount = fields.Float(string="Metal Amount",compute="_compute_metal_amount", digits=(16, 3))
    mc_fine = fields.Float(string="MC Fine Wt", compute="_compute_purchase_mc_fine",digits=(16, 3))
    gold_rate =fields.Float(string="Rate(g)", digits=(16, 3))
    mc_percent = fields.Float(string="MC%", digits=(16, 3))
    net_weight = fields.Float(string="Net Weight (g)",compute="_compute_net_weight",digits=(16, 3))
    stone_weight = fields.Float(string="Stone Weight (g)",digits=(16, 3))
    diamond_weight_gm = fields.Float(
        string="Diamond Weight (g)",
        digits=(16, 3)
    )
    mc_amount = fields.Float(
        string="MC Amount",
        compute="_compute_purchase_mc_amount",
        digits=(16, 3),
        store=True
    )
    stone_rate = fields.Float(string="Stone Amount", digits=(16, 3))
    diamond_rate = fields.Float(string="Diamond Amount", digits=(16, 3))
    gross_weight = fields.Float(string="Gross Weight (g)",digits=(16, 3))
    price_unit = fields.Float(
        string='Unit Price', required=True, digits=(16, 3),
        compute="_compute_price_unit", readonly=False, store=True)
    price_subtotal = fields.Monetary(compute='_compute_subtotal', string='Subtotal', store=True)

    @api.depends('product_qty', 'price_unit', 'taxes_id', 'discount', 'sale_return_line_id', 'sale_return_line_id.amount')
    def _compute_amount(self):
        super()._compute_amount()
        for line in self:
            if line.sale_return_line_id:
                line.price_subtotal = line.sale_return_line_id.amount
                line.price_total = line.price_subtotal + line.price_tax



    purchase_price_per_gram = fields.Float(string="Purchase fine Rate / gram",digits=(16, 3))
    purchase_making_charge_amount = fields.Float(
        string="MC Amount",
        digits=(16, 3)
    )
    purchase_making_charge_value = fields.Float(string="Amount(mc)", digits=(16, 3))

    purchase_making_charge_type = fields.Selection([
        ('percent', 'Percentage'),
        ('amount', 'Amount'),
        ('rate_per_gram', 'Rate Per Gram')

    ], string="MC Type", default='percent')
    total_fine = fields.Float(string="Total Fine", compute="_compute_total_fine",digits=(16, 3))

    rate_value = fields.Float(string="Rate Value", digits=(16, 3))




    @api.depends(
        'product_qty',
        'stone_weight',
        'diamond_weight_gm',
    )
    def _compute_net_weight(self):
        for rec in self:
            rec.net_weight = (
                    rec.product_qty
                    - rec.stone_weight
                    - rec.diamond_weight_gm
            )

    @api.depends('net_weight', 'purity_id')
    def _compute_fine_weight(self):
        for rec in self:
            rec.fine_weight = rec.net_weight * (rec.purity_id.percentage)/100

    @api.depends('gold_rate', 'fine_weight', 'net_weight', 'order_id.is_sale_return_shop', 'order_id.is_sale_return_po')
    def _compute_metal_amount(self):
        for rec in self:
            gold_rate = rec.gold_rate or 0.0
            if rec.order_id and (rec.order_id.is_sale_return_shop or rec.order_id.is_sale_return_po):
                rec.metal_amount = gold_rate * (rec.net_weight or 0.0)
            else:
                rec.metal_amount = gold_rate * (rec.fine_weight or 0.0)

    @api.depends('net_weight','mc_percent','purchase_making_charge_type')
    def _compute_purchase_mc_fine(self):
        for rec in self:
            if rec.purchase_making_charge_type == 'percent':
                rec.mc_fine = rec.net_weight * (rec.mc_percent/ 100)
            else:
                rec.mc_fine = 0.0

    @api.depends(
        'mc_fine', 'gold_rate', 'purchase_making_charge_type', 'rate_value', 'purchase_making_charge_value'
    )
    def _compute_purchase_mc_amount(self):
        for rec in self:
            if rec.purchase_making_charge_type == 'percent':
                rec.mc_amount = rec.mc_fine * rec.gold_rate
            elif rec.purchase_making_charge_type == 'amount':
                rec.mc_amount = rec.purchase_making_charge_value
            # from jafar side
            elif rec.purchase_making_charge_type == 'rate_per_gram':
                rec.mc_amount = rec.net_weight * rec.rate_value
            else:
                rec.mc_amount = rec.net_weight * rec.gold_rate

    @api.depends('metal_amount', 'mc_amount', 'diamond_rate', 'stone_rate', 'sale_return_line_id', 'sale_return_line_id.amount')
    def _compute_subtotal(self):
        for rec in self:
            if rec.sale_return_line_id:
                rec.price_subtotal = rec.sale_return_line_id.amount
            else:
                rec.price_subtotal = rec.metal_amount + rec.mc_amount + rec.stone_rate + rec.diamond_rate

    @api.depends('price_subtotal', 'product_qty', 'product_uom_qty')
    def _compute_price_unit(self):
        for rec in self:
            rec.price_unit = (rec.price_subtotal / rec.product_qty) if rec.product_qty else 0.0


    def _prepare_stock_moves(self, picking):
        moves = super()._prepare_stock_moves(picking)

        for values in moves:
            values['purity_id'] = self.purity_id.id if self.purity_id else False

        return moves

    @api.depends('mc_fine', 'fine_weight')
    def _compute_total_fine(self):
        for rec in self:
            rec.total_fine = rec.mc_fine + rec.fine_weight

    @api.onchange('product_id')
    def _onchange_purchase_product_id(self):
        if self.product_id:
            self.purity_id = self.product_id.purity_id.id
            if self.order_id.is_old_gold:
                self.purchase_making_charge_type = 'rate_per_gram'



