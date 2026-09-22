from odoo import models, fields, api

class EcommerceCard(models.Model):
    _name = 'ecommerce.card'
    _description = 'Ecommerce Customer Saved Card'
    _order = 'id desc'

    customer_id = fields.Many2one('ecommerce.customer', string='Customer', required=True, ondelete='cascade', index=True)
    card_type = fields.Selection([
        ('visa', 'Visa'),
        ('mastercard', 'Mastercard'),
        ('rupay', 'Rupay'),
    ], string='Card Type', required=True)
    card_holder_name = fields.Char(string='Card Holder Name', required=True)
    card_number = fields.Char(string='Card Number', required=True)
    card_number_masked = fields.Char(string='Masked Card Number', compute='_compute_card_number_masked', store=True)
    expiry = fields.Char(string='Expiry (MM/YY)', required=True)

    @api.depends('card_number')
    def _compute_card_number_masked(self):
        for rec in self:
            if rec.card_number:
                digits = ''.join(c for c in rec.card_number if c.isdigit())
                last_four = digits[-4:] if len(digits) >= 4 else digits
                rec.card_number_masked = f"•••• •••• •••• {last_four}"
            else:
                rec.card_number_masked = "•••• •••• •••• ••••"
