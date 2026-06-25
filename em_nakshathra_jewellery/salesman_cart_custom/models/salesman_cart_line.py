from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta

class SalesmanCartLine(models.Model):
    _name = 'salesman.cart.line'
    _description = 'Salesman Digital Cart Line'

    cart_id = fields.Many2one('salesman.cart', ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    label_id = fields.Many2one('product.label', string='Label')
    lot_id = fields.Many2one('stock.lot', string='Serial/Lot Number')
    qty = fields.Float(string='Qty', default=1.0)
    weight = fields.Float(string='Gross Weight (g)', related='product_id.weight', store=True)
    price_unit = fields.Float(string='Unit Price', related='product_id.lst_price')
    price_subtotal = fields.Monetary(string='Subtotal', compute='_compute_subtotal')
    currency_id = fields.Many2one('res.currency', related='cart_id.currency_id')
    picking_id = fields.Many2one('stock.picking', string='Linked Internal Transfer', readonly=True)
    active_label_name = fields.Char(string='Active Label Reference', related='product_id.active_label_name')

    @api.depends('qty', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.price_subtotal = line.qty * line.price_unit