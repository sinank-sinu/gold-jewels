from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class SaleReturnLine(models.Model):
    _name = 'sale.return.line'
    _description = 'Sale Return Line'

    sale_id = fields.Many2one('sale.order', ondelete='cascade')
    product_id = fields.Many2one('product.product', string="Product", required=True)
    purity_id = fields.Many2one('gold.purity', string="Purity")
    gross_weight = fields.Float(string="Gross Weight (g)", digits=(16, 3))
    stone_weight = fields.Float(string="Stone Weight (g)", digits=(16, 3))
    net_weight = fields.Float(string="Net Weight (g)", compute='_compute_net_weight', store=True, digits=(16, 3))
    rate = fields.Float(string="Rate")
    amount = fields.Float(string="Amount", compute='_compute_amount', store=True)

    @api.depends('gross_weight', 'stone_weight')
    def _compute_net_weight(self):
        for r in self:
            r.net_weight = r.gross_weight - r.stone_weight

    @api.depends('net_weight', 'rate')
    def _compute_amount(self):
        for rec in self:
            rec.amount = rec.net_weight * rec.rate

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.purity_id = self.product_id.purity_id.id

    @api.onchange('purity_id')
    def _onchange_purity(self):
        for r in self:
            today = fields.Date.today()
            gold_rate_rec = self.env['gold.rate.master'].search([
                ('purity_id', '=', r.purity_id.id),
                ('date', '<=', today),
                ('active', '=', True),
                ('rate_type', '=', 'old_gold')
            ], order='date desc', limit=1)
            if gold_rate_rec:
                r.rate = gold_rate_rec.board_rate
