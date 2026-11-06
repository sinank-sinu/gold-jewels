from odoo import models, fields, api


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _compute_display_name(self):
        super()._compute_display_name()
        for move in self:
            if self.env.context.get('show_transfer_item_details'):
                weight = getattr(move, 'grams', 0.0) or (move.quantity if (move.picking_id and move.picking_id.state == 'done' and move.quantity) else (move.product_uom_qty or move.quantity or 0.0))
                label_part = f" [{move.label_id.name}]" if (hasattr(move, 'label_id') and move.label_id and move.label_id.name) else ""
                prod_name = move.product_id.display_name or (move.product_tmpl_id.name if hasattr(move, 'product_tmpl_id') else move.name)
                move.display_name = f"{prod_name} - {weight:.3f}g{label_part}"

