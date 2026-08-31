from odoo import models, fields, api

class EcommerceNotification(models.Model):
    """Stores push notifications, deals, and alerts for the mobile app."""
    _name = 'ecommerce.notification'
    _description = 'Ecommerce Mobile Notification'
    _order = 'created_at desc'

    title = fields.Char(string='Title', required=True)
    message = fields.Text(string='Message', required=True)
    image = fields.Binary(string='Banner Image')
    
    notification_category = fields.Selection([
        ('new_arrival', 'New Arrival'),
        ('offer_alert', 'Offer / Flash Sale'),
        ('newsletter', 'Monthly Trend / Newsletter'),
        ('order_update', 'Order Update'),
        ('general', 'General Alert')
    ], string='Category', required=True, default='general')
    
    customer_id = fields.Many2one('ecommerce.customer', string='Specific Customer', 
                                  help="If selected, this notification will only be sent to this specific customer. If left blank, it acts as a global broadcast.")
    
    active = fields.Boolean(default=True)
    created_at = fields.Datetime(string='Date Published', default=fields.Datetime.now)
