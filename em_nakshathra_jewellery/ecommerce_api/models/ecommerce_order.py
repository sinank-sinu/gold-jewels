from odoo import models, fields, api

class EcommerceOrder(models.Model):
    """E-commerce order for website customers."""
    _name = 'ecommerce.order'
    _description = 'Ecommerce Order'
    _rec_name = 'order_number'
    _order = 'created_at desc'

    order_number = fields.Char(string='Order Number', required=True, copy=False, readonly=True, default='New')
    customer_id = fields.Many2one('ecommerce.customer', string='Customer', required=True, ondelete='cascade', index=True)
    branch_id = fields.Many2one('res.branch', string='Branch', index=True)
    line_ids = fields.One2many('ecommerce.order.line', 'order_id', string='Order Items')
    
    subtotal_amount = fields.Float(string='Subtotal', compute='_compute_amounts', store=True)
    tax_amount = fields.Float(string='Tax Amount', compute='_compute_amounts', store=True)
    total_amount = fields.Float(string='Total Amount', compute='_compute_amounts', store=True)
    
    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('bank', 'Bank Transfer'),
        ('upi', 'UPI'),
        ('card', 'Card')
    ], string='Payment Method', required=True)
    
    payment_status = fields.Selection([
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed')
    ], string='Payment Status', default='pending')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True)
    
    shipping_address = fields.Text(string='Shipping Address')
    shipping_city = fields.Char(string='Shipping City')
    shipping_phone = fields.Char(string='Shipping Phone')
    
    created_at = fields.Datetime(string='Order Date', default=fields.Datetime.now, readonly=True)
    confirmed_at = fields.Datetime(string='Confirmed Date', readonly=True)
    delivered_at = fields.Datetime(string='Delivered Date', readonly=True)
    
    notes = fields.Text(string='Order Notes')

    @api.depends('line_ids.subtotal')
    def _compute_amounts(self):
        for order in self:
            order.subtotal_amount = sum(order.line_ids.mapped('subtotal'))
            order.tax_amount = 0.0
            order.total_amount = order.subtotal_amount + order.tax_amount

    @api.model
    def create(self, vals):
        if vals.get('order_number', 'New') == 'New':
            seq = self.env['ir.sequence'].next_by_code('ecommerce.order')
            vals['order_number'] = seq if seq else 'ORD/' + fields.Datetime.now().strftime('%Y%m%d%H%M%S')
        return super(EcommerceOrder, self).create(vals)

    def action_confirm(self):
        self.write({
            'state': 'confirmed',
            'confirmed_at': fields.Datetime.now()
        })

    def action_cancel(self):
        self.write({
            'state': 'cancelled'
        })

    def action_ship(self):
        self.write({
            'state': 'shipped'
        })

    def action_deliver(self):
        self.write({
            'state': 'delivered',
            'delivered_at': fields.Datetime.now()
        })


class EcommerceOrderLine(models.Model):
    """Individual line item in an e-commerce order."""
    _name = 'ecommerce.order.line'
    _description = 'Ecommerce Order Line'

    order_id = fields.Many2one('ecommerce.order', string='Order', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.template', string='Product', required=True)
    product_name = fields.Char(string='Product Name', related='product_id.name', readonly=True)
    quantity = fields.Float(string='Quantity', required=True, default=1.0)
    price = fields.Float(string='Unit Price', required=True)
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True)

    @api.depends('quantity', 'price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price
