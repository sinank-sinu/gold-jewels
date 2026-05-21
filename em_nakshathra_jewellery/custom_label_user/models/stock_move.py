from odoo import models, fields, api


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.onchange('label_id')
    def _onchange_label_id_set_source(self):
        """On change of label, set the source location of the picking to the current location of the label."""
        for rec in self:
            if rec.label_id and rec.picking_id:

                # Current location of label
                current_location = rec.label_id.source_location_id

                if current_location:
                    rec.picking_id.location_id = current_location.id