from odoo import models, fields


class PurchaseOrderExt(models.Model):
    _inherit = 'purchase.order'

    source_location_id = fields.Many2one(
        'stock.location',
        string='Source Location',
        help='Source location - will be used as destination in receipt when auto-receiving'
    )

    destination_location_id = fields.Many2one(
        'stock.location',
        string='Destination Location',
        domain="[('usage', '=', 'internal')]",
        help='Destination location where goods will be received'
    )

    def _prepare_picking(self):
        vals = super()._prepare_picking()
        # Use source_location as the picking destination (where goods will be received)
        if self.source_location_id:
            vals['location_dest_id'] = self.source_location_id.id
        elif self.destination_location_id:
            # Fallback to destination_location if source_location not set
            vals['location_dest_id'] = self.destination_location_id.id
        return vals