from odoo import models, fields

class EcommerceUPI(models.Model):
    _name = 'ecommerce.upi'
    _description = 'Ecommerce Customer Saved UPI Profile'
    _order = 'id desc'

    customer_id = fields.Many2one('ecommerce.customer', string='Customer', required=True, ondelete='cascade', index=True)
    upi_id = fields.Char(string='UPI ID', required=True)
    status = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], string='Status', default='active', required=True)
