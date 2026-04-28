from odoo import models, fields,api,_

class SchemeRedemption(models.Model):
    _name = 'scheme.redemption'
    _description = 'Scheme Redemption Tracking'

    scheme_id = fields.Many2one('jewellery.scheme.enrollment', required=True)
    sale_order_id = fields.Many2one('sale.order', required=True)
    amount = fields.Float(required=True)
    date = fields.Date(default=fields.Date.today)