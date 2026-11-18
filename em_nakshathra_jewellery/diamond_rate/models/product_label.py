# -*- coding: utf-8 -*-
from odoo import models, api

class ProductLabel(models.Model):
    _inherit = 'product.label'

    @api.onchange('sale_diamond_weight_ct')
    def _onchange_sale_diamond_weight_ct(self):
        super()._onchange_sale_diamond_weight_ct()
        if self.sale_diamond_weight_ct:
            domain = [('active', '=', True)]
            rate_rec = False
            if self.purity_id:
                rate_rec = self.env['diamond.rate.master'].search(domain + [('purity_id', '=', self.purity_id.id)], order='date desc, id desc', limit=1)
            if not rate_rec:
                rate_rec = self.env['diamond.rate.master'].search(domain, order='date desc, id desc', limit=1)
            diamond_rate = rate_rec.rate_per_carat if rate_rec else 0.0
            self.sale_diamond_rate = round(self.sale_diamond_weight_ct * diamond_rate, 2)
        else:
            self.sale_diamond_rate = 0.0
