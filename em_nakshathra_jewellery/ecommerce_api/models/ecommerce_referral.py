from odoo import models, fields

class EcommerceReferral(models.Model):
    _name = 'ecommerce.referral'
    _description = 'Ecommerce Customer Referral Invite'
    _order = 'id desc'

    referrer_id = fields.Many2one('ecommerce.customer', string='Referrer', required=True, ondelete='cascade', index=True)
    friend_email = fields.Char(string='Friend Email')
    friend_phone = fields.Char(string='Friend Phone')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('joined', 'Joined'),
        ('shipped', 'Order Shipped')
    ], string='Status', default='pending', required=True)
    coupon_value = fields.Float(string='Coupon Value (₹)', default=500.0)
