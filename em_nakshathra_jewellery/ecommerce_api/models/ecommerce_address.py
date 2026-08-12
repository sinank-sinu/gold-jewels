from odoo import models, fields

class EcommerceAddress(models.Model):
    _name = 'ecommerce.address'
    _description = 'Ecommerce Customer Saved Address'
    _order = 'id desc'

    name = fields.Selection([
        ('home', 'Home'),
        ('work', 'Work'),
        ('other', 'Other')
    ], string='Address Type', default='home', required=True)
    
    recipient_name = fields.Char(string='Recipient Name', required=True)
    phone = fields.Char(string='Phone Number', required=True)
    address_details = fields.Text(string='Full Address Details', required=True)
    customer_id = fields.Many2one('ecommerce.customer', string='Customer', required=True, ondelete='cascade', index=True)
