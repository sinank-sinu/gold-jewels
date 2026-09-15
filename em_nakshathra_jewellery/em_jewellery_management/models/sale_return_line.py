from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class SaleReturnLine(models.Model):
    _name = 'sale.return.line'
    _inherit = ['analytic.mixin']
    _description = 'Sale Return Line'

    sale_id = fields.Many2one('sale.order', ondelete='cascade')
    currency_id = fields.Many2one(related='sale_id.currency_id', store=True, readonly=True)

    product_template_id = fields.Many2one(
        'product.template',
        string="Product",
        compute='_compute_product_template_id',
        readonly=False,
        store=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string="Variety",
        required=True,
    )
    label_id = fields.Many2one(
        'product.label',
        string="Label",
    )
    name = fields.Text(
        string="Description",
        compute='_compute_name',
        store=True,
        readonly=False,
    )
    purity_id = fields.Many2one(
        'gold.purity',
        string="Purity",
    )
    product_uom = fields.Many2one(
        'uom.uom',
        string="UOM",
        compute='_compute_product_uom',
        readonly=False,
        store=True,
    )
    event_id = fields.Many2one(
        'event.event',
        string="Event",
    )
    event_ticket_id = fields.Many2one(
        'event.event.ticket',
        string="Event Ticket",
    )
    route_id = fields.Many2one(
        'stock.route',
        string="Route",
    )
    customer_lead = fields.Float(
        string="Lead Time",
        default=0.0,
    )
    analytic_precision = fields.Integer(
        store=False,
        default=lambda self: self.env['decimal.precision'].precision_get("Percentage Analytic"),
    )
    qty_delivered = fields.Float(string="Delivered", digits=(16, 3))
    qty_invoiced = fields.Float(string="Invoiced", digits=(16, 3))

    gross_weight = fields.Float(string="Gross Weight (g)", digits=(16, 3))
    stone_weight = fields.Float(string="Stone Weight (g)", digits=(16, 3))
    sale_stone_weight = fields.Float(string="Stone Weight (g)", digits=(16, 3))
    sale_stone_weight_ct = fields.Float(string="Stone Weight (ct)", digits=(12, 3))
    sale_diamond_weight_gm = fields.Float(string="Diamond Weight (g)", digits=(12, 3))
    sale_diamond_weight_ct = fields.Float(string="Diamond Weight (ct)", digits=(12, 3))
    net_weight = fields.Float(string="Net Weight (g)", compute='_compute_net_weight', store=True, digits=(16, 3))
    rate = fields.Float(string="Gold Rate")
    metal_amount = fields.Float(string="Metal Amt", compute='_compute_metal_amount', store=True)
    fine_weight = fields.Float(string="Fine Weight (g)", compute='_compute_fine_weight', store=True, digits=(16, 3))

    mc_percent = fields.Float(string="Max mc")
    mc_amount = fields.Float(string="MC Amt", compute='_compute_mc_amount', store=True)
    mc_percent_actual = fields.Float(string="MC%", readonly=False)
    mc_amount_actual = fields.Float(string="MC", compute='_compute_mc_amount_actual', store=True)
    mc_discount = fields.Float(string="Discount")

    sale_stone_rate = fields.Float(string="Stone Amt")
    sale_diamond_rate = fields.Float(string="Diamond Amt")
    other_weight_g = fields.Float(string="Other Weight (g)", digits=(16, 3))
    other_weight_amount = fields.Float(string="Other Weight Amount")

    amount = fields.Monetary(string="Subtotal", compute='_compute_amount', store=True, currency_field='currency_id')
    price_subtotal_actual = fields.Monetary(string="MRP", store=True, currency_field='currency_id')
    price_total = fields.Monetary(string="Tax incl.", compute='_compute_price_total', store=True, currency_field='currency_id')
    price_unit = fields.Float(string="Unit Price", compute='_compute_price_unit', store=True)
    tax_id = fields.Many2many('account.tax', string="Taxes")

    @api.depends('product_id')
    def _compute_product_template_id(self):
        for rec in self:
            if rec.product_id:
                rec.product_template_id = rec.product_id.product_tmpl_id
            elif not rec.product_template_id:
                rec.product_template_id = False

    @api.depends('product_id')
    def _compute_product_uom(self):
        for rec in self:
            if rec.product_id:
                rec.product_uom = rec.product_id.uom_id
            elif not rec.product_uom:
                rec.product_uom = False

    @api.depends('product_id')
    def _compute_name(self):
        for rec in self:
            if rec.product_id:
                rec.name = rec.product_id.display_name or rec.product_id.name
            elif not rec.name:
                rec.name = False

    @api.depends('gross_weight', 'stone_weight', 'sale_stone_weight', 'sale_diamond_weight_gm')
    def _compute_net_weight(self):
        for r in self:
            st_wt = r.sale_stone_weight or r.stone_weight or 0.0
            dia_wt = r.sale_diamond_weight_gm or 0.0
            r.net_weight = (r.gross_weight or 0.0) - st_wt - dia_wt
            if not r.stone_weight and r.sale_stone_weight:
                r.stone_weight = r.sale_stone_weight
            elif not r.sale_stone_weight and r.stone_weight:
                r.sale_stone_weight = r.stone_weight

    @api.onchange('sale_stone_weight')
    def _onchange_sale_stone_weight(self):
        if self.sale_stone_weight:
            self.stone_weight = self.sale_stone_weight

    @api.onchange('stone_weight')
    def _onchange_stone_weight(self):
        if self.stone_weight:
            self.sale_stone_weight = self.stone_weight

    @api.depends('net_weight', 'purity_id', 'purity_id.percentage')
    def _compute_fine_weight(self):
        for rec in self:
            if rec.net_weight and rec.purity_id and rec.purity_id.percentage:
                rec.fine_weight = rec.net_weight * (rec.purity_id.percentage / 100.0)
            else:
                rec.fine_weight = 0.0

    @api.depends('net_weight', 'rate')
    def _compute_metal_amount(self):
        for rec in self:
            rec.metal_amount = (rec.net_weight or 0.0) * (rec.rate or 0.0)

    @api.depends('metal_amount', 'mc_percent')
    def _compute_mc_amount(self):
        for rec in self:
            rec.mc_amount = (rec.metal_amount or 0.0) * ((rec.mc_percent or 0.0) / 100.0)

    @api.depends('metal_amount', 'mc_percent_actual', 'mc_percent')
    def _compute_mc_amount_actual(self):
        for rec in self:
            pct = rec.mc_percent_actual if rec.mc_percent_actual else (rec.mc_percent or 0.0)
            rec.mc_amount_actual = (rec.metal_amount or 0.0) * (pct / 100.0)

    @api.depends('metal_amount', 'mc_amount_actual', 'mc_amount', 'mc_discount', 'sale_stone_rate', 'sale_diamond_rate', 'other_weight_amount')
    def _compute_amount(self):
        for rec in self:
            mc = rec.mc_amount_actual if rec.mc_amount_actual else (rec.mc_amount or 0.0)
            extra = (rec.sale_stone_rate or 0.0) + (rec.sale_diamond_rate or 0.0) + (rec.other_weight_amount or 0.0)
            rec.amount = (rec.metal_amount or 0.0) + mc - (rec.mc_discount or 0.0) + extra
            rec.price_subtotal_actual = (rec.metal_amount or 0.0) + (rec.mc_amount or 0.0) + extra

    @api.depends('amount', 'tax_id')
    def _compute_price_total(self):
        for rec in self:
            if rec.tax_id and rec.amount and rec.sale_id.partner_id:
                taxes = rec.tax_id.compute_all(
                    rec.amount,
                    currency=rec.currency_id,
                    quantity=1.0,
                    product=rec.product_id,
                    partner=rec.sale_id.partner_id
                )
                rec.price_total = taxes['total_included']
            else:
                rec.price_total = rec.amount or 0.0

    @api.depends('amount', 'gross_weight', 'net_weight', 'rate')
    def _compute_price_unit(self):
        for rec in self:
            if rec.gross_weight:
                rec.price_unit = rec.amount / rec.gross_weight
            elif rec.net_weight:
                rec.price_unit = rec.amount / rec.net_weight
            else:
                rec.price_unit = rec.rate or 0.0

    @api.onchange('product_template_id')
    def _onchange_product_template_id(self):
        if self.product_template_id:
            variants = self.product_template_id.product_variant_ids
            if len(variants) == 1:
                self.product_id = variants[0].id
            elif self.product_id and self.product_id.product_tmpl_id != self.product_template_id:
                self.product_id = False

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_template_id = self.product_id.product_tmpl_id
            self.product_uom = self.product_id.uom_id
            self.name = self.product_id.display_name or self.product_id.name
            if hasattr(self.product_id, 'purity_id') and self.product_id.purity_id:
                self.purity_id = self.product_id.purity_id.id
            if self.product_id.taxes_id and self.sale_id.company_id:
                self.tax_id = self.product_id.taxes_id.filtered(lambda t: t.company_id == self.sale_id.company_id)

    @api.onchange('label_id')
    def _onchange_label_id(self):
        if self.label_id:
            if self.label_id.product_id:
                self.product_id = self.label_id.product_id.id
                self.product_template_id = self.label_id.product_id.product_tmpl_id.id
                self.name = self.label_id.product_id.display_name or self.label_id.product_id.name
            if hasattr(self.label_id, 'purity_id') and self.label_id.purity_id:
                self.purity_id = self.label_id.purity_id.id
            elif hasattr(self.label_id, 'sale_purity_id') and self.label_id.sale_purity_id:
                self.purity_id = self.label_id.sale_purity_id.id
            if hasattr(self.label_id, 'sale_gross_weight') and self.label_id.sale_gross_weight:
                self.gross_weight = self.label_id.sale_gross_weight
            if hasattr(self.label_id, 'sale_stone_weight') and self.label_id.sale_stone_weight:
                self.stone_weight = self.label_id.sale_stone_weight
                self.sale_stone_weight = self.label_id.sale_stone_weight
            if hasattr(self.label_id, 'sale_stone_weight_ct') and self.label_id.sale_stone_weight_ct:
                self.sale_stone_weight_ct = self.label_id.sale_stone_weight_ct
            if hasattr(self.label_id, 'sale_diamond_weight_gm') and self.label_id.sale_diamond_weight_gm:
                self.sale_diamond_weight_gm = self.label_id.sale_diamond_weight_gm
            if hasattr(self.label_id, 'sale_diamond_weight_ct') and self.label_id.sale_diamond_weight_ct:
                self.sale_diamond_weight_ct = self.label_id.sale_diamond_weight_ct
            if hasattr(self.label_id, 'sale_stone_rate') and self.label_id.sale_stone_rate:
                self.sale_stone_rate = self.label_id.sale_stone_rate
            if hasattr(self.label_id, 'sale_diamond_rate') and self.label_id.sale_diamond_rate:
                self.sale_diamond_rate = self.label_id.sale_diamond_rate
            if hasattr(self.label_id, 'other_weight_g') and self.label_id.other_weight_g:
                self.other_weight_g = self.label_id.other_weight_g
            if hasattr(self.label_id, 'other_weight_amount') and self.label_id.other_weight_amount:
                self.other_weight_amount = self.label_id.other_weight_amount
            if hasattr(self.label_id, 'sale_making_charge_value') and self.label_id.sale_making_charge_value:
                self.mc_percent = self.label_id.sale_making_charge_value
                self.mc_percent_actual = self.label_id.sale_making_charge_value
            self._onchange_purity()

    @api.onchange('purity_id')
    def _onchange_purity(self):
        for r in self:
            if not r.purity_id:
                continue
            today = fields.Date.today()
            gold_rate_rec = self.env['gold.rate.master'].search([
                ('purity_id', '=', r.purity_id.id),
                ('date', '<=', today),
                ('active', '=', True),
                ('rate_type', '=', 'old_gold')
            ], order='date desc', limit=1)
            if gold_rate_rec:
                r.rate = gold_rate_rec.board_rate
