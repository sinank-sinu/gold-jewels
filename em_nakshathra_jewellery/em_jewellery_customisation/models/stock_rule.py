from odoo import models

class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _get_stock_move_values(
        self, product_id, product_qty, product_uom,
        location_dest_id, name, origin, company_id, values
    ):
        move_values = super()._get_stock_move_values(
            product_id, product_qty, product_uom,
            location_dest_id, name, origin, company_id, values
        )

        #Override source location from label
        if values.get('label_location_id'):
            move_values['location_id'] = values['label_location_id']

        return move_values