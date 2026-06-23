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
                    new_qty = values['product_qty']
                    if new_qty != line.product_qty:
                        moves = line.move_ids.filtered(lambda m: m.state == 'done')
                        for move in moves:
                            old_qty = move.quantity
                            if old_qty == 0:
                                continue
                            
                            qty_diff = new_qty - old_qty
                            
                            # 1. Update move lines silently
                            for ml in move.move_line_ids:
                                self.env.cr.execute(
                                    "UPDATE stock_move_line SET quantity = %s WHERE id = %s",
                                    (new_qty, ml.id)
                                )
                            
                            # 2. Update move silently
                            self.env.cr.execute(
                                "UPDATE stock_move SET product_uom_qty = %s, quantity = %s WHERE id = %s",
                                (new_qty, new_qty, move.id)
                            )
                            
                            # 3. Update valuation silently
                            svls = move.stock_valuation_layer_ids
                            for svl in svls:
                                if svl.quantity != 0:
                                    ratio = new_qty / old_qty
                                    new_svl_qty = -new_qty if svl.quantity < 0 else new_qty
                                    new_svl_value = svl.value * ratio
                                    
                                    self.env.cr.execute(
                                        "UPDATE stock_valuation_layer SET quantity = %s, value = %s WHERE id = %s",
                                        (new_svl_qty, new_svl_value, svl.id)
                                    )
                                    
                                    if svl.account_move_id:
                                        self.env.cr.execute(
                                            "UPDATE account_move_line SET debit = debit * %s, credit = credit * %s, balance = balance * %s WHERE move_id = %s",
                                            (ratio, ratio, ratio, svl.account_move_id.id)
                                        )
                                        self.env.cr.execute(
                                            "UPDATE account_move SET amount_total = amount_total * %s, amount_total_signed = amount_total_signed * %s, amount_total_in_currency_signed = amount_total_in_currency_signed * %s WHERE id = %s",
                                            (ratio, ratio, ratio, svl.account_move_id.id)
                                        )
                            
                            # 4. Adjust Quants
                            self.env['stock.quant'].sudo()._update_available_quantity(
                                move.product_id,
                                move.location_id,
                                -qty_diff,
                            )
                            self.env['stock.quant'].sudo()._update_available_quantity(
                                move.product_id,
                                move.location_dest_id,
                                qty_diff,
                            )
                            
                        # Force flush and invalidation so Odoo's native checks see the new qty_received from DB
                        self.env.flush_all()
                        self.env.invalidate_all()

        return super(PurchaseOrderLine, self).write(values)

    def _create_or_update_picking(self):
        # Bypass the native purchase_stock UserError check if editing the order
        if self.filtered(lambda l: l.order_id.is_editing_main_po):
            # Do nothing since the SQL update handles everything silently
            return True
        return super(PurchaseOrderLine, self)._create_or_update_picking()
