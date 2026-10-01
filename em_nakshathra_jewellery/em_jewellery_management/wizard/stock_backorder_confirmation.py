from odoo import models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class StockBackorderConfirmation(models.TransientModel):
    _inherit = 'stock.backorder.confirmation'

    def process_cancel_backorder(self):
        for picking in self.pick_ids:
            for move in picking.move_ids:
                if move.label_id:
                    rounding = move.product_uom.rounding if move.product_uom else 0.001
                    if float_compare(move.quantity, move.product_uom_qty, precision_rounding=rounding) < 0:
                        raise UserError(_(
                            "Cannot cancel backorder for jewellery item '%s' (Label: %s).\n\n"
                            "• Required Gross Weight: %.3f %s\n"
                            "• Processed Weight: %.3f %s\n\n"
                            "Partial delivery is not permitted for labelled jewellery items. "
                            "Clicking 'No Backorder' would permanently erase %.3f %s from inventory while the physical piece is given to the customer.\n\n"
                            "Please ensure the full item weight is available at the counter/location before completing the sale."
                        ) % (
                            move.product_id.display_name,
                            move.label_id.display_name or move.label_id.name,
                            move.product_uom_qty,
                            move.product_uom.name or 'g',
                            move.quantity,
                            move.product_uom.name or 'g',
                            move.product_uom_qty - move.quantity,
                            move.product_uom.name or 'g',
                        ))
        return super().process_cancel_backorder()
