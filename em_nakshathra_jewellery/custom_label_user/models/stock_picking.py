from odoo import models, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.depends(
        'picking_type_id',
        'partner_id',
        'move_ids_without_package.label_id'
    )
    def _compute_location_id(self):
        """Compute the source location of the picking based on the label's current branch location.

        Rules:
        - Skipped entirely when context 'skip_label_location_overwrite' is True.
        - Skipped for non-internal pickings.
        - Skipped for non-draft pickings (confirmed / done / cancelled) — locations are frozen.
        - Skipped for return pickings (return_id is set).
        - Skipped for pickings originating from 'Return of'.
        - 'Salesman Cart' pickings participate in label-based location compute (not skipped).
        - For eligible draft internal pickings (and Salesman Cart pickings) that have a
          labelled move: uses label.branch_location_id (current physical location) as source,
          falling back to label.source_location_id only if branch_location_id is missing.
        """

        # Bypass compute completely when explicitly requested (e.g. data import/migration)
        if self.env.context.get('skip_label_location_overwrite'):
            return

        # Save the current values before running super so we can restore them selectively
        current_locations = {}
        for picking in self:
            current_locations[picking.id] = (picking.location_id, picking.location_dest_id)

        super()._compute_location_id()

        for picking in self:
            prev_loc, prev_dest_loc = current_locations.get(picking.id, (False, False))

            # Only touch internal transfers
            if picking.picking_type_code != 'internal':
                if prev_loc:
                    picking.location_id = prev_loc
                if prev_dest_loc:
                    picking.location_dest_id = prev_dest_loc
                continue

            # Skip for non-draft / return / 'Return of'-originated pickings
            # NOTE: 'Salesman Cart' pickings are intentionally NOT skipped here —
            # they also benefit from label-based location compute.
            origin = picking.origin or ''
            is_salesman_cart = 'Salesman Cart' in origin
            is_managed_externally = (
                picking.state != 'draft'
                or bool(picking.return_id)
                or origin.startswith('Return of')
            )

            if is_managed_externally and not is_salesman_cart:
                # Restore whatever was stored before super() ran
                if prev_loc:
                    picking.location_id = prev_loc
                if prev_dest_loc:
                    picking.location_dest_id = prev_dest_loc
                continue

            # For a genuine fresh-draft internal picking: derive source from label location
            move = picking.move_ids_without_package.filtered(
                lambda m: m.label_id and (m.label_id.branch_location_id or m.label_id.source_location_id)
            )[:1]

            if move:
                # branch_location_id = where the piece physically is now (preferred)
                # source_location_id = where it was received from (fallback)
                loc = move.label_id.branch_location_id or move.label_id.source_location_id
                picking.location_id = loc.id
                if prev_dest_loc:
                    picking.location_dest_id = prev_dest_loc
            else:
                # No label — restore previous values to avoid losing explicit assignments
                if prev_loc:
                    picking.location_id = prev_loc
                if prev_dest_loc:
                    picking.location_dest_id = prev_dest_loc