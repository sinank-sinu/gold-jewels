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
        readonly=False
    )

    label_id = fields.Many2one('product.label', string="Label")
    purity_id = fields.Many2one('gold.purity', string="Purity")
    fine_weight = fields.Float(string="Fine Weight  (g)",compute="_compute_fine_weight",digits=(16, 3))
    metal_amount = fields.Float(string="Metal Amount",compute="_compute_metal_amount")
    mc_fine = fields.Float(string="MC Fine Wt", compute="_compute_purchase_mc_fine",digits=(16, 3))
    gold_rate =fields.Float(string="Rate(g)")
    mc_percent = fields.Float(string="MC%")
    net_weight = fields.Float(string="Net Weight (g)",compute="_compute_product_qty",digits=(16, 3))
    stone_weight = fields.Float(string="Stone Weight (g)",digits=(16, 3))
    diamond_weight_gm = fields.Float(
        string="Diamond Weight (g)",
        digits=(12, 4)
    )
    mc_amount = fields.Float(
        string="MC Amount",
        compute="_compute_purchase_mc_amount",
        store=True
    )
    stone_rate = fields.Float(string="Stone Amount")
    diamond_rate = fields.Float(string="Diamond Amount")
    gross_weight = fields.Float(string="Gross Weight (g)",digits=(16, 3))
    price_unit = fields.Float(
        string='Unit Price', required=True, digits='Product Price',
        compute="_compute_price_unit", readonly=False, store=True)
    price_subtotal = fields.Monetary(compute='_compute_subtotal', string='Subtotal', store=True)



    purchase_price_per_gram = fields.Float(string="Purchase fine Rate / gram",digits=(16, 3))
    purchase_making_charge_amount = fields.Float(
        string="MC Amount",
    )
    purchase_making_charge_value = fields.Float(string="Amount(mc)")

    purchase_making_charge_type = fields.Selection([
        ('percent', 'Percentage'),
        ('amount', 'Amount'),
        ('rate_per_gram', 'Rate Per Gram')

    ], string="MC Type", default='percent')
    total_fine = fields.Float(string="Total Fine", compute="_compute_total_fine",digits=(16, 3))

    rate_value = fields.Float(string="Rate Value")




    @api.depends(
        'product_qty',
        'stone_weight',
        'diamond_weight_gm',
    )
    def _compute_product_qty(self):
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

    @api.depends('gold_rate', 'fine_weight', 'net_weight', 'order_id.is_sale_return_shop')
    def _compute_metal_amount(self):
        for rec in self:
            gold_rate = rec.gold_rate or 0.0
            if rec.order_id and rec.order_id.is_sale_return_shop:
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
        'mc_fine','gold_rate','purchase_making_charge_type','rate_value'
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

    @api.depends('metal_amount', 'mc_amount', 'diamond_rate', 'stone_rate')
    def _compute_subtotal(self):
        for rec in self:
            rec.price_subtotal = rec.metal_amount + rec.mc_amount + rec.stone_rate + rec.diamond_rate


    @api.depends('price_subtotal', 'product_uom_qty')
    def _compute_price_unit(self):
        for rec in self:
            rec.price_unit = (rec.price_subtotal /rec.product_qty) if rec.product_uom_qty else 0.0


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

    @api.onchange('label_id')
    def _onchange_purchase_label_id(self):
        if self.label_id:
            if self.label_id.product_id:
                self.product_id = self.label_id.product_id.id
                self.product_template_id = self.label_id.product_id.product_tmpl_id.id
            purity = self.label_id.purity_id or self.label_id.sale_purity_id
            if purity:
                self.purity_id = purity.id
            if hasattr(self.label_id, 'sale_gross_weight') and self.label_id.sale_gross_weight:
                self.product_qty = self.label_id.sale_gross_weight
                self.gross_weight = self.label_id.sale_gross_weight
            if hasattr(self.label_id, 'sale_stone_weight') and self.label_id.sale_stone_weight:
                self.stone_weight = self.label_id.sale_stone_weight
            if hasattr(self.label_id, 'sale_diamond_weight_gm') and self.label_id.sale_diamond_weight_gm:
                self.diamond_weight_gm = self.label_id.sale_diamond_weight_gm
            if hasattr(self.label_id, 'sale_stone_rate') and self.label_id.sale_stone_rate:
                self.stone_rate = self.label_id.sale_stone_rate
            if hasattr(self.label_id, 'sale_diamond_rate') and self.label_id.sale_diamond_rate:
                self.diamond_rate = self.label_id.sale_diamond_rate
            if hasattr(self.label_id, 'sale_making_charge_value') and self.label_id.sale_making_charge_value:
                self.mc_percent = self.label_id.sale_making_charge_value
            # Gold Rate
            today = fields.Date.today()
            if purity:
                gold_rate_rec = self.env['gold.rate.master'].search([
                    ('purity_id', '=', purity.id),
                    ('date', '<=', today),
                    ('active', '=', True),
                    ('rate_type', '=', 'old_gold')
                ], order='date desc', limit=1)
                if not gold_rate_rec:
                    gold_rate_rec = self.env['gold.rate.master'].search([
                        ('purity_id', '=', purity.id),
                        ('date', '<=', today),
                        ('active', '=', True),
                        ('rate_type', '=', 'sale')
                    ], order='date desc', limit=1)
                if gold_rate_rec:
                    rate = gold_rate_rec.board_rate or gold_rate_rec.rate_per_gram
                    self.gold_rate = rate
                    self.price_unit = rate

