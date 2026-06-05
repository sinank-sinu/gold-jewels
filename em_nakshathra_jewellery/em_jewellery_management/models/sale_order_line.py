from email.policy import default

from numpy.f2py.rules import defmod_rules

from odoo import models, fields, api

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    label_id = fields.Many2one(
        'product.label',
        string="Label",
    )
    purity_id = fields.Many2one('gold.purity', string="Purity")
    net_weight = fields.Float(string="Net Weight  (g)",compute="_compute_net_weight",digits=(16, 3))
    sale_stone_weight = fields.Float(string="Stone Weight (g)",digits=(16, 3))
    sale_diamond_weight_gm = fields.Float(
        string="Diamond Weight (g)",
        digits=(12, 3)
    )
    sale_diamond_weight_ct = fields.Float(
        string="Diamond Weight (ct)",
        digits=(12, 3)
    )
    gold_rate =fields.Float(string="Gold Rate(g)")

    mc_percent = fields.Float(string="Max mc")
    mc_amount = fields.Float(string="MC Amt",compute="_compute_mc_amount",)
    metal_amount = fields.Float(string="Metal Amt", compute="_compute_metal_amounts",store=True)

    fine_weight = fields.Float(string="Fine Weight  (g)",digits=(16, 3))
    tag_weight = fields.Float(string="Tag Weight (g)")

    sale_stone_rate = fields.Float(string="Stone Amt")
    sale_diamond_rate = fields.Float(string="Diamond Amt")
    product_uom_qty = fields.Float(
        compute='_compute_product_uom_qty',
        digits='Product Unit of Measure',
        readonly=False, store=True,
    )
    sale_gross_weight = fields.Float(string="Gross Weight (g)", digits=(16, 3))
    price_unit = fields.Float(
        string='Unit Price', required=True, digits='Product Price',
        compute="_compute_price_unit", readonly=False, store=True)
    price_subtotal = fields.Monetary(string='Subtotal', compute='_compute_subtotal', readonly=False, store=True)
    price_subtotal_actual = fields.Monetary(compute='_compute_subtotal', string='MRP', store=True)
    mc_percent_actual = fields.Float(string="MC%",readonly=False)
    mc_amount_actual = fields.Float(string="MC", compute="_compute_mc_amount_actual" )
    mc_discount = fields.Float(string="Discount", compute="_compute_mc_discount")
    sale_making_charge_min = fields.Float(string="Sale Making Charge Min")

    # @api.depends('mc_amount_actual', 'metal_amount')
    # def _compute_effective_mc_percent(self):
    #     for rec in self:
    #         if rec.mc_amount_actual:
    #             rec.mc_percent_actual = (rec.mc_amount_actual / rec.metal_amount) * 100
    #         else:
    #             rec.mc_percent_actual = 0.0

    @api.depends('mc_amount', 'mc_discount','mc_percent_actual')
    def _compute_mc_amount_actual(self):
        for rec in self:
               # rec.mc_amount_actual = rec.mc_amount - rec.mc_discount
            if rec.mc_percent_actual:
                rec.mc_amount_actual = rec.metal_amount * (rec.mc_percent_actual / 100.0)
            else:
                rec.mc_amount_actual=0.0


    @api.depends('price_subtotal', 'price_subtotal_actual')
    def _compute_mc_discount(self):
        for rec in self:
            if rec.price_subtotal:
               rec.mc_discount = rec.price_subtotal_actual - rec.price_subtotal
            else:
               rec.mc_discount = 0.0

    @api.depends('metal_amount', 'mc_percent')
    def _compute_mc_amount(self):
        for rec in self:
            rec.mc_amount = rec.metal_amount * (rec.mc_percent / 100.0)

    @api.onchange('label_id','product_uom_qty')
    def _onchange_label_id(self):
        if self.label_id :
            self.purity_id = self.label_id.purity_id.id
            self.mc_percent = self.label_id.sale_making_charge_value
            self.sale_making_charge_min = self.label_id.sale_making_charge_min
            self.product_uom_qty = self.label_id.sale_gross_weight
            self.sale_stone_weight = self.label_id.sale_stone_weight
            self.sale_diamond_weight_gm = self.label_id.sale_diamond_weight_gm
            self.sale_diamond_weight_ct = self.label_id.sale_diamond_weight_ct

            self.sale_stone_rate = self.label_id.sale_stone_rate
            self.sale_diamond_rate = self.label_id.sale_diamond_rate

            gold_rate = 0.0
            today = fields.Date.today()
            gold_rate_rec = self.env['gold.rate.master'].search([
                ('purity_id', '=', self.purity_id.id),
                ('date', '<=', today),
                ('active', '=', True),
                ('rate_type', '=', 'sale')

            ], order='date desc', limit=1)
            gold_rate = gold_rate_rec.rate_per_gram
            self.gold_rate = gold_rate
            self.metal_amount = self.gold_rate * self.product_uom_qty

        if not self.label_id :
            today = fields.Date.today()
            gold_rate_rec = self.env['gold.rate.master'].search([
                ('purity_id', '=', self.purity_id.id),
                ('date', '<=', today),
                ('active', '=', True),
                ('rate_type', '=', 'sale')

            ], order='date desc', limit=1)
            gold_rate = gold_rate_rec.rate_per_gram
            self.gold_rate = gold_rate


    @api.depends('gold_rate', 'product_uom_qty')
    def _compute_metal_amount(self):
        for rec in self:
            rec.metal_amount = rec.gold_rate * rec.product_uom_qty

    @api.depends(
        'product_uom_qty',
        'sale_stone_weight',
        'sale_diamond_weight_gm',
    )
    def _compute_net_weight(self):
        for rec in self:
            rec.net_weight = (
                    rec.product_uom_qty
                    - rec.sale_stone_weight
                    - rec.sale_diamond_weight_gm
            )

    @api.depends('gold_rate', 'net_weight')
    def _compute_metal_amounts(self):
        for rec in self:
            rec.metal_amount = rec.gold_rate * rec.net_weight


    @api.depends('metal_amount', 'mc_amount', 'sale_diamond_rate', 'sale_stone_rate','mc_amount_actual')
    def _compute_subtotal(self):
        for rec in self:
            rec.price_subtotal_actual = rec.metal_amount + rec.mc_amount + rec.sale_stone_rate + rec.sale_diamond_rate
            rec.price_subtotal = rec.metal_amount + rec.mc_amount_actual + rec.sale_stone_rate + rec.sale_diamond_rate

    @api.depends('price_subtotal', 'product_uom_qty')
    def _compute_price_unit(self):
        for rec in self:
            rec.price_unit = (rec.price_subtotal / rec.product_uom_qty) if rec.product_uom_qty else 0.0

    @api.depends('gold_rate', 'fine_weight')
    def _compute_metal_amount(self):
        for rec in self:
            rec.metal_amount = rec.gold_rate * rec.fine_weight

    @api.depends('fine_weight', 'purity_id', 'order_id.purchase_order_id')
    def _compute_product_uom_qty(self):
        for rec in self:
            if (
                rec.order_id.purchase_order_id
                and rec.purity_id
                and rec.purity_id.percentage
                and rec.fine_weight
            ):
                # Only recompute from fine_weight when fine_weight is explicitly set
                # (e.g. Unfix scenario). Skip for regular lines where the user has
                # manually entered a gross weight — those should not be wiped out
                # simply because a purchase_order_id was linked via apply_old_gold.
                rec.product_uom_qty = rec.fine_weight / (rec.purity_id.percentage / 100.0)
            elif not rec.product_uom_qty:
                rec.product_uom_qty = 0.0

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        res['label_id'] = self.label_id.id if self.label_id else False
        res['purity_id'] = self.purity_id.id if self.purity_id else False

        return res

    def _prepare_procurement_values(self,group_id=False):
        values = super()._prepare_procurement_values(group_id)
        values['label_id'] = self.label_id.id if self.label_id else False
        values['purity_id'] = self.purity_id.id if self.purity_id else False

        return values






