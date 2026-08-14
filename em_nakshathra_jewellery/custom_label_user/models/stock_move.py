from odoo import models, fields, api


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.onchange('label_id')
    def _onchange_label_id_set_source(self):
        """On change of label, default picking source location if not set yet."""
        for rec in self:
            if rec.label_id and rec.picking_id:
                if not rec.picking_id.location_id and rec.label_id.source_location_id:
                    rec.picking_id.location_id = rec.label_id.source_location_id.id