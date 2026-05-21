from odoo import models, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.depends(
        'picking_type_id',
        'partner_id',
        'move_ids_without_package.label_id'
    )
    def _compute_location_id(self):
        """Compute the source location of the picking based on the label's source location."""
        super()._compute_location_id()

        for picking in self:

            # Only internal transfers
            if picking.picking_type_code != 'internal':
                continue

            move = picking.move_ids_without_package.filtered(
                lambda m: m.label_id and m.label_id.source_location_id
            )[:1]

            if move:
                picking.location_id = move.label_id.source_location_id.id