from odoo import models

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def write(self, values):
        if self.filtered(lambda l: l.order_id.is_editing_main_po):
            self = self.with_context(mail_notrack=True, disable_po_chatter_track=True)
            
        # Intercept quantity reductions when editing the main order to safely reverse pickings 
        # BEFORE Odoo's native purchase_stock validation triggers a UserError.
        if 'product_qty' in values:
            for line in self:
                if line.order_id.is_editing_main_po:
                    # If quantity has changed and is less than received, we must reverse pickings
                    if values['product_qty'] != line.product_qty and values['product_qty'] < line.qty_received:
                        in_pickings = line.order_id.picking_ids.filtered(
                            lambda p: p.state != 'cancel' and p.picking_type_id.code == 'incoming'
                        )
                        for picking in in_pickings:
                            line.order_id._safe_reverse_or_cancel_picking(picking)

        return super(PurchaseOrderLine, self).write(values)
