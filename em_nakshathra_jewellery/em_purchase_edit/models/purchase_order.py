from odoo import models, fields, api

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    is_editing_main_po = fields.Boolean(
        string="Editing Main PO", 
        default=False, 
        copy=False,
        help="Flag to unlock the main PO lines for editing after confirmation."
    )

    def action_edit_main_po(self):
        """Unlock the Main Purchase Order table for editing."""
        self.ensure_one()
        self.is_editing_main_po = True

    def write(self, vals):
        if self.filtered('is_editing_main_po') or vals.get('is_editing_main_po'):
            self = self.with_context(mail_notrack=True, tracking_disable=True, disable_po_chatter_track=True)
            res = super(PurchaseOrder, self).write(vals)
            self.env.flush_all()
            return res
        return super(PurchaseOrder, self).write(vals)

    def message_post_with_source(self, source, render_values=None, subtype_xmlid=None, **kwargs):
        if self.env.context.get('disable_po_chatter_track'):
            return self.env['mail.message']
        return super(PurchaseOrder, self).message_post_with_source(source, render_values=render_values, subtype_xmlid=subtype_xmlid, **kwargs)

    def message_post(self, **kwargs):
        if self.env.context.get('disable_po_chatter_track'):
            return self.env['mail.message']
        return super(PurchaseOrder, self).message_post(**kwargs)

    def _track_prepare(self, fields_iter):
        track_self = self.filtered(lambda r: not r.is_editing_main_po)
        if not track_self:
            return
        return super(PurchaseOrder, track_self)._track_prepare(fields_iter)

    def action_save_main_po(self):
        """Persist edits: trigger new procurement, update invoice."""
        self.ensure_one()
        self._update_main_po_stock_and_bill()
        self.is_editing_main_po = False
        self.with_context(mail_notrack=True, tracking_disable=True).env.flush_all()

    def _update_main_po_stock_and_bill(self):
        """Trigger new receipt and update vendor bills."""
        self = self.with_context(mail_notrack=True, tracking_disable=True, disable_po_chatter_track=True)
        # 1. Trigger procurement to generate new receipts for the updated quantities
        if self.order_line:
            # Recreate or update picking (purchase_stock natively handles this during write if qty increased)
            # We call _create_picking() to be safe if pickings were reversed.
            self._create_picking()

            # Automatically validate any pending incoming pickings
            pending_pickings = self.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel') and p.picking_type_id.code == 'incoming'
            )
            for picking in pending_pickings:
                picking.action_confirm()
                picking.action_assign()
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                picking.button_validate()

        # 2. Update vendor bills in-place
        invoices = self.invoice_ids.filtered(
            lambda inv: inv.state != 'cancel' and inv.move_type == 'in_invoice'
        ).with_context(mail_notrack=True, tracking_disable=True)
        for invoice in invoices:
            if invoice.state == 'posted':
                invoice.button_draft()
            
            # Sync the invoice lines from the corresponding PO lines
            for inv_line in invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                po_line = inv_line.purchase_line_id
                if po_line:
                    inv_line.with_context(check_move_validity=False).write({
                        'quantity': po_line.product_qty,
                        'price_unit': po_line.price_unit,
                    })
            
            # Recompute tax totals since we bypassed validity checks
            invoice.with_context(check_move_validity=False)._compute_tax_totals()
            invoice.action_post()

    def _safe_reverse_or_cancel_picking(self, picking):
        """Safely reverses 'done' pickings via return wizard or cancels pending ones."""
        if picking.state == 'cancel':
            return
        
        if picking.state == 'done':
            ReturnWizard = self.env['stock.return.picking']
            wizard_vals = ReturnWizard.with_context(active_id=picking.id, active_model='stock.picking').default_get(
                ['product_return_moves', 'move_dest_exists', 'original_location_id', 'parent_location_id', 'location_id']
            )
            wizard = ReturnWizard.create(wizard_vals)
            
            # Identify the return picking ID from the wizard's action
            res = wizard.create_returns()
            return_picking_id = res.get('res_id')
            if return_picking_id:
                return_picking = self.env['stock.picking'].browse(return_picking_id)
                # Auto-validate the return picking
                return_picking.action_confirm()
                return_picking.action_assign()
                
                # Set quantities
                for move in return_picking.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                    
                return_picking.button_validate()
        else:
            picking.action_cancel()
