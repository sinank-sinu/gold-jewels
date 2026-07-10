from odoo import models, fields, api


class EcommerceCart(models.Model):
    """Shopping cart for an e-commerce customer."""
    _name = 'ecommerce.cart'
    _description = 'Ecommerce Cart'
    _rec_name = 'customer_id'

    customer_id = fields.Many2one('ecommerce.customer', string='Customer', required=True, ondelete='cascade', index=True)
    line_ids = fields.One2many('ecommerce.cart.line', 'cart_id', string='Cart Items')
    total_amount = fields.Float(string='Total Amount', compute='_compute_total', store=True)
    created_at = fields.Datetime(default=fields.Datetime.now)

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for cart in self:
            cart.total_amount = sum(cart.line_ids.mapped('subtotal'))


class EcommerceCartLine(models.Model):
    """Individual line item in a shopping cart."""
    _name = 'ecommerce.cart.line'
    _description = 'Ecommerce Cart Line'

    cart_id = fields.Many2one('ecommerce.cart', string='Cart', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.template', string='Product', required=True)
    location_id = fields.Many2one('stock.location', string='Location')
    quantity = fields.Float(string='Quantity', default=1.0)
    price = fields.Float(string='Unit Price', compute='_compute_price', store=True)
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True)

    @api.depends('product_id')
    def _compute_price(self):
        for line in self:
            line.price = line.product_id.list_price if line.product_id else 0.0

    @api.depends('quantity', 'price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price
