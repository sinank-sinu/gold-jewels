from odoo import models, fields, api

class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.onchange('label_id', 'product_uom_qty', 'tax_id')
    def _onchange_label_id(self):
        super()._onchange_label_id()
        if self.label_id:
            weight = self.label_id.tag_weight or self.label_id.purchase_gross_weight or self.label_id.sale_gross_weight
            self.product_uom_qty = weight
            self.grams = weight
