from email.policy import default

from numpy.f2py.rules import defmod_rules

from odoo import models, fields, api

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_scheme_line = fields.Boolean(default=False)
    
    @api.depends('mc_amount_actual', 'metal_amount')
    def _compute_effective_mc_percent(self):
        for rec in self:
            if rec.is_scheme_line:
                rec.mc_percent_actual = 0.0
                continue
            if rec.metal_amount:
                rec.mc_percent_actual = (rec.mc_amount_actual / rec.metal_amount) * 100
            else:
                rec.mc_percent_actual = 0.0

    @api.depends('metal_amount', 'mc_amount', 'sale_diamond_rate', 'sale_stone_rate', 'is_scheme_line')
    def _compute_subtotal(self):
        for rec in self:
            if rec.is_scheme_line:
                continue  
            rec.price_subtotal_actual = rec.metal_amount + rec.mc_amount + rec.sale_stone_rate + rec.sale_diamond_rate
            rec.price_subtotal = rec.price_subtotal_actual
    
    @api.depends('price_subtotal', 'product_uom_qty', 'is_scheme_line')
    def _compute_price_unit(self):
        for rec in self:
            if rec.is_scheme_line:
                continue  
            rec.price_unit = (rec.price_subtotal / rec.product_uom_qty) if rec.product_uom_qty else 0.0