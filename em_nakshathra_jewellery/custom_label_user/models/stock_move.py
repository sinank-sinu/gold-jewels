from odoo import models, fields, api


class StockMove(models.Model):
    _inherit = 'stock.move'

    # @api.onchange('label_id')
    # def _onchange_label_id_set_source(self):
    #     """On change of label, default picking source location if not set yet."""
    #     for rec in self:
    #         if rec.label_id and rec.picking_id:
    #             # loc = rec.label_id.branch_location_id or rec.label_id.source_location_id
    #             if not rec.picking_id.location_id and loc:
    #                 rec.picking_id.location_id = loc.id