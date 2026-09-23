from odoo import models, fields,api,_

class SchemeRedemption(models.Model):
    _name = 'scheme.redemption'
    _description = 'Scheme Redemption Tracking'

    scheme_id = fields.Many2one('jewellery.scheme.enrollment', required=True)
    sale_order_id = fields.Many2one('sale.order', required=False)
    move_id = fields.Many2one('account.move', string="Invoice", ondelete='cascade')
    amount = fields.Float(required=True)
    date = fields.Date(default=fields.Date.today)

    def init(self):
        super().init()
        self.env.cr.execute("""
            ALTER TABLE scheme_redemption 
            ADD COLUMN IF NOT EXISTS move_id INTEGER;
        """)