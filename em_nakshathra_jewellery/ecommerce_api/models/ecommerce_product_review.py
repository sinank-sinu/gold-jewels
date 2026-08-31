from odoo import models, fields

class EcommerceProductReview(models.Model):
    _name = 'ecommerce.product.review'
    _description = 'Ecommerce Product Review'
    _order = 'review_date desc, id desc'

    customer_id = fields.Many2one('ecommerce.customer', string='Customer', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.template', string='Product', required=True, ondelete='cascade', index=True)
    rating = fields.Integer(string='Rating (1-5)', required=True)
    review_text = fields.Text(string='Review Text', required=True)
    review_date = fields.Date(string='Review Date', default=fields.Date.context_today, required=True)
