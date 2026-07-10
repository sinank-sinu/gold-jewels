from odoo import models, fields


class EcommerceWishlist(models.Model):
    """Wishlist item for an e-commerce customer."""
    _name = 'ecommerce.wishlist'
    _description = 'Ecommerce Wishlist'
    _rec_name = 'product_id'
    _sql_constraints = [
        ('unique_customer_product', 'UNIQUE(customer_id, product_id)', 'This product is already in the wishlist.')
    ]

    customer_id = fields.Many2one('ecommerce.customer', string='Customer', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.template', string='Product', required=True)
    added_on = fields.Datetime(default=fields.Datetime.now)
