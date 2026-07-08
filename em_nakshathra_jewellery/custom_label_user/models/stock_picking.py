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
        # Save the current values of location_id and location_dest_id before running super
        current_locations = {}
        for picking in self:
            current_locations[picking.id] = (picking.location_id, picking.location_dest_id)

        super()._compute_location_id()

        for picking in self:
            prev_loc, prev_dest_loc = current_locations.get(picking.id, (False, False))

            # Only internal transfers
            if picking.picking_type_code != 'internal':
                if prev_loc:
                    picking.location_id = prev_loc
                if prev_dest_loc:
                    picking.location_dest_id = prev_dest_loc
                continue

            move = picking.move_ids_without_package.filtered(
                lambda m: m.label_id and m.label_id.source_location_id
            )[:1]

            if move:
                picking.location_id = move.label_id.source_location_id.id
                if prev_dest_loc:
                    picking.location_dest_id = prev_dest_loc
            else:
                # No label found, restore the previous values if they exist
                if prev_loc:
                    picking.location_id = prev_loc
                if prev_dest_loc:
                    picking.location_dest_id = prev_dest_loc