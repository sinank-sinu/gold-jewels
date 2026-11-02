from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    available_transfer_label_ids = fields.Many2many(
        'product.label',
        compute='_compute_available_transfer_labels',
    )
    
    cutpiece_location_dest_id = fields.Many2one(
        'stock.location', 
        string="Cutpiece Location", 
        domain="[('usage', '=', 'internal')]", 
        copy=False,
    )

    is_transfer_remaining = fields.Boolean(
        string="Transfer Remaining Stock",
        default=False,
        copy=False,
    )

    cutpiece_line_ids = fields.One2many(
        'sale.order.cutpiece.line',
        'order_id',
        string="Cutpiece Lines",
        copy=False,
    )

    is_transferred = fields.Boolean(
        string="Is Transferred",
        default=False,
        copy=False,
    )

    has_active_transfers = fields.Boolean(
        string="Has Active Transfers",
        compute='_compute_cutpiece_picking_ids',
    )

    cutpiece_picking_ids = fields.Many2many(
        'stock.picking',
        string="Cutpiece Transfers",
        compute='_compute_cutpiece_picking_ids',
        copy=False,
    )
    cutpiece_picking_count = fields.Integer(
        string="Cutpiece Transfers Count",
        compute='_compute_cutpiece_picking_ids',
    )

    @api.depends('cutpiece_line_ids.picking_id', 'cutpiece_line_ids.return_picking_id', 'cutpiece_line_ids.is_transferred')
    def _compute_cutpiece_picking_ids(self):
        for order in self:
            line_pickings = order.cutpiece_line_ids.mapped('picking_id') | order.cutpiece_line_ids.mapped('return_picking_id')
            origin_pickings = self.env['stock.picking'].search([
                ('origin', 'in', [
                    f"{order.name} - Cutpiece Transfer", 
                    f"{order.name} - Remaining Transfer",
                    f"{order.name} - Cutpiece Reversal"
                ]),
                ('picking_type_id.code', '=', 'internal'),
            ]) if order.name else self.env['stock.picking']
            all_pickings = line_pickings | origin_pickings
            order.cutpiece_picking_ids = all_pickings
            order.cutpiece_picking_count = len(all_pickings)
            order.has_active_transfers = any(l.is_transferred and not l.is_reverted for l in order.cutpiece_line_ids)

    def action_view_cutpiece_transfers(self):
        self.ensure_one()
        pickings = self.cutpiece_picking_ids
        if not pickings:
            return {'type': 'ir.actions.act_window_close'}
        action = self._get_action_view_picking(pickings)
        action['name'] = _("Cut Piece Transfers")
        return action

    # Legacy fields preserved for backward compatibility
    transfer_label_id = fields.Many2one(
        'product.label',
        string="Label to Transfer",
        copy=False,
    )
    transfer_weight = fields.Float(
        string="Remaining Weight (g)",
        compute="_compute_transfer_weight",
        digits=(16, 3),
    )
    dest_location_weight = fields.Float(
        string="Quantity in Location", 
        compute="_compute_dest_location_weight", 
        digits=(16, 3),
    )

    def _compute_available_transfer_labels(self):
        for order in self:
            order.available_transfer_label_ids = order.order_line.mapped('label_id')

    def _compute_transfer_weight(self):
        for order in self:
            order.transfer_weight = sum(order.cutpiece_line_ids.mapped('transfer_weight'))

    def _compute_dest_location_weight(self):
        for order in self:
            order.dest_location_weight = sum(order.cutpiece_line_ids.mapped('dest_location_weight'))

    @api.onchange('branch_id')
    def _onchange_branch_id_for_cutpiece(self):
        if getattr(self, 'branch_id', False) and getattr(self.branch_id, 'cutpiece_location_id', False):
            self.cutpiece_location_dest_id = self.branch_id.cutpiece_location_id.id

    @api.onchange('cutpiece_location_dest_id')
    def _onchange_cutpiece_location_dest_id(self):
        if self.cutpiece_location_dest_id:
            for line in self.cutpiece_line_ids:
                if not line.is_transferred:
                    line.cutpiece_location_dest_id = self.cutpiece_location_dest_id.id

    @api.onchange('order_line', 'is_transfer_remaining')
    def _onchange_order_line_cutpiece_sync(self):
        """Automatically keep cutpiece_line_ids in sync with order lines in real-time"""
        if not self.is_transfer_remaining:
            return

        default_dest = self.cutpiece_location_dest_id.id or (
            self.branch_id.cutpiece_location_id.id if getattr(self, 'branch_id', False) else False
        )
        if not self.cutpiece_location_dest_id and default_dest:
            self.cutpiece_location_dest_id = default_dest

        # Aggregate sold weight per label across order lines
        label_sold = {}
        warning_msgs = []
        for line in self.order_line:
            label = line.label_id
            if not label:
                continue
            gross = label.sale_gross_weight or label.tag_weight or label.purchase_gross_weight or 0.0
            sold = line.product_uom_qty or 0.0
            if round(sold - gross, 3) > 0.0001:
                warning_msgs.append(_(
                    "Label '%(label)s': Sold weight (%(sold)s g) exceeds original gross weight (%(gross)s g)."
                ) % {'label': label.name, 'sold': sold, 'gross': gross})

            if label.id not in label_sold:
                label_sold[label.id] = {'label': label, 'gross': gross, 'sold': 0.0}
            label_sold[label.id]['sold'] += sold

        # Build active cutpiece mapping
        active_cuts = {}
        for lid, data in label_sold.items():
            rem = round(data['gross'] - data['sold'], 3)
            if rem > 0.0001:
                active_cuts[lid] = {
                    'label': data['label'],
                    'gross': data['gross'],
                    'sold': round(data['sold'], 3),
                    'remaining': rem,
                }

        # Keep existing transferred lines and update untransferred lines cleanly
        transferred_cmds = []
        for line in self.cutpiece_line_ids:
            if line.is_transferred:
                transferred_cmds.append((4, line.id.origin if hasattr(line.id, 'origin') and line.id.origin else line.id))

        new_commands = []
        for lid, cut_data in active_cuts.items():
            # Check if this label already has a transferred line
            already_transferred = any(
                (l.label_id.id == lid and l.is_transferred) for l in self.cutpiece_line_ids
            )
            if not already_transferred:
                new_commands.append((0, 0, {
                    'label_id': cut_data['label'].id,
                    'original_weight': cut_data['gross'],
                    'sold_weight': cut_data['sold'],
                    'transfer_weight': cut_data['remaining'],
                    'cutpiece_location_dest_id': default_dest,
                    'state': 'draft',
                }))
        self.cutpiece_line_ids = [(5, 0, 0)] + transferred_cmds + new_commands

        if warning_msgs:
            return {
                'warning': {
                    'title': _("Sold Weight Exceeds Gross Weight"),
                    'message': "\n".join(warning_msgs),
                }
            }

    def _sync_cutpiece_lines_with_order_lines(self):
        """Backend sync for cutpiece lines before confirmation and on write"""
        for order in self:
            if not order.is_transfer_remaining:
                untransferred = order.cutpiece_line_ids.filtered(lambda l: not l.is_transferred)
                if untransferred:
                    untransferred.unlink()
                continue

            default_dest = order.cutpiece_location_dest_id.id or (
                order.branch_id.cutpiece_location_id.id if getattr(order, 'branch_id', False) else False
            )
            if not order.cutpiece_location_dest_id and default_dest:
                order.cutpiece_location_dest_id = default_dest

            label_sold = {}
            for line in order.order_line:
                label = line.label_id
                if not label:
                    continue
                gross = label.sale_gross_weight or label.tag_weight or label.purchase_gross_weight or 0.0
                if label.id not in label_sold:
                    label_sold[label.id] = {'label': label, 'gross': gross, 'sold': 0.0}
                label_sold[label.id]['sold'] += (line.product_uom_qty or 0.0)

            active_cuts = {}
            for lid, data in label_sold.items():
                rem = round(data['gross'] - data['sold'], 3)
                if rem > 0.0001:
                    active_cuts[lid] = {
                        'label': data['label'],
                        'gross': data['gross'],
                        'sold': round(data['sold'], 3),
                        'remaining': rem,
                    }

            # Update existing untransferred lines or remove stale ones
            existing_by_label = {}
            for line in order.cutpiece_line_ids:
                if line.is_transferred:
                    continue
                lid = line.label_id.id
                if lid in active_cuts and lid not in existing_by_label:
                    cut_data = active_cuts[lid]
                    line.write({
                        'original_weight': cut_data['gross'],
                        'sold_weight': cut_data['sold'],
                        'transfer_weight': cut_data['remaining'],
                        'cutpiece_location_dest_id': line.cutpiece_location_dest_id.id or default_dest,
                        'state': 'draft',
                    })
                    existing_by_label[lid] = line
                else:
                    line.unlink()

            # Create missing cut piece lines
            for lid, cut_data in active_cuts.items():
                if lid not in existing_by_label:
                    # Check if already transferred
                    if not any(l.label_id.id == lid and l.is_transferred for l in order.cutpiece_line_ids):
                        self.env['sale.order.cutpiece.line'].create({
                            'order_id': order.id,
                            'label_id': cut_data['label'].id,
                            'original_weight': cut_data['gross'],
                            'sold_weight': cut_data['sold'],
                            'transfer_weight': cut_data['remaining'],
                            'cutpiece_location_dest_id': default_dest,
                            'state': 'draft',
                        })

    def action_populate_cutpiece_lines(self):
        """Manual Refresh Button action for the Transfer Remaining tab"""
        for order in self:
            order._sync_cutpiece_lines_with_order_lines()
            count = len(order.cutpiece_line_ids.filtered(lambda l: not l.is_transferred and l.transfer_weight > 0))
            if count:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Cut Pieces Refreshed"),
                        'message': _("Found %s cut piece(s) ready to transfer.") % count,
                        'sticky': False,
                        'type': 'info',
                    }
                }
            elif order.cutpiece_line_ids.filtered(lambda l: l.is_transferred):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Cut Pieces Up-to-date"),
                        'message': _("All cut piece transfers are completed."),
                        'sticky': False,
                        'type': 'success',
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("No Cut Pieces"),
                        'message': _("No cut pieces found. Order line quantities match label gross weights."),
                        'sticky': False,
                        'type': 'warning',
                    }
                }
        return True

    def _create_and_validate_cutpiece_transfers(self):
        """Creates and validates the internal transfer picking for all untransferred cut pieces"""
        self.ensure_one()
        lines_to_transfer = self.cutpiece_line_ids.filtered(lambda l: not l.is_transferred and l.transfer_weight > 0)
        if not lines_to_transfer:
            return

        warehouse = self.warehouse_id
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1) or self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

        if not picking_type:
            raise UserError(_("No internal transfer operation type found for warehouse/company."))

        default_dest = self.cutpiece_location_dest_id or lines_to_transfer[0].cutpiece_location_dest_id
        if not default_dest:
            raise UserError(_("Please specify a Cutpiece Location before confirming the order."))

        # Validate stock availability
        for line in lines_to_transfer:
            dest_location = line.cutpiece_location_dest_id or default_dest
            if not dest_location:
                raise UserError(_("Please specify a Cutpiece Location for label '%s'.") % line.label_id.name)
            source_location = line.label_id.branch_location_id or warehouse.lot_stock_id
            quants = self.env['stock.quant'].search([
                ('location_id', '=', source_location.id),
                ('product_id', '=', line.label_id.product_id.id),
            ])
            available_qty = sum(quants.mapped('quantity'))
            if available_qty < line.transfer_weight:
                raise UserError(_(
                    "Insufficient stock on hand for '%s' (Label %s) in '%s'. Available: %s g, Required: %s g."
                ) % (line.product_id.name, line.label_id.name, source_location.display_name, available_qty, line.transfer_weight))

        first_source = lines_to_transfer[0].label_id.branch_location_id or warehouse.lot_stock_id
        unique_sources = {l.label_id.branch_location_id.id for l in lines_to_transfer if l.label_id.branch_location_id}
        unique_dests = {l.cutpiece_location_dest_id.id for l in lines_to_transfer if l.cutpiece_location_dest_id}
        is_multiple = len(unique_sources) > 1 or len(unique_dests) > 1

        # Create combined internal transfer picking
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': first_source.id,
            'location_dest_id': default_dest.id,
            'origin': f"{self.name} - Cutpiece Transfer",
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'is_multiple_transfer': is_multiple,
            'branch_id': self.branch_id.id if getattr(self, 'branch_id', False) else False,
        })

        for line in lines_to_transfer:
            source_location = line.label_id.branch_location_id or warehouse.lot_stock_id
            dest_location = line.cutpiece_location_dest_id or default_dest
            self.env['stock.move'].create({
                'name': f"Transfer Scrap: {line.label_id.name}",
                'product_id': line.label_id.product_id.id,
                'product_uom_qty': line.transfer_weight,
                'product_uom': line.label_id.product_id.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': dest_location.id,
                'picking_id': picking.id,
                'label_id': False,
                'branch_id': self.branch_id.id if getattr(self, 'branch_id', False) else False,
                'company_id': self.company_id.id,
            })

        picking.action_confirm()
        picking.action_assign()

        for move in picking.move_ids:
            move.picked = True
            if move.move_line_ids:
                for ml in move.move_line_ids:
                    ml.quantity = ml.quantity_product_uom or move.product_uom_qty
                    ml.picked = True
            else:
                self.env['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'quantity': move.product_uom_qty,
                    'picked': True,
                })

        res = picking.button_validate()
        if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
            wiz = self.env['stock.backorder.confirmation'].with_context(res.get('context', {})).create({})
            wiz.process()

        if picking.state != 'done':
            raise UserError(_(
                "Cutpiece transfer %s could not be completed automatically (Status: %s)."
            ) % (picking.name, picking.state))

        # Update cutpiece lines and label gross weights
        for line in lines_to_transfer:
            line.write({
                'is_transferred': True,
                'is_reverted': False,
                'state': 'done',
                'picking_id': picking.id,
            })
            if line.label_id and line.sold_weight > 0:
                label_vals = {}
                if 'sale_gross_weight' in line.label_id._fields:
                    label_vals['sale_gross_weight'] = line.sold_weight
                if 'purchase_gross_weight' in line.label_id._fields:
                    label_vals['purchase_gross_weight'] = line.sold_weight
                if label_vals:
                    old_w = line.original_weight or line.label_id.sale_gross_weight
                    line.label_id.sudo().with_context(cutpiece_weight_update=True).write(label_vals)
                    dest_name = (line.cutpiece_location_dest_id or default_dest).display_name
                    line.label_id.sudo().message_post(body=_(
                        "Cut piece stock transferred on confirmation of %(order)s (%(transfer_weight)s g transferred to %(dest)s). "
                        "Label gross weight updated from %(old_weight)s g to %(new_weight)s g.",
                        order=self.name,
                        transfer_weight=line.transfer_weight,
                        dest=dest_name,
                        old_weight=old_w,
                        new_weight=line.sold_weight,
                    ))

        self.is_transferred = True

    def _revert_cutpiece_line(self, line):
        """Reverses a single completed cut piece transfer, returns scrap to stock, and restores label weight"""
        self.ensure_one()
        if not line.is_transferred or line.is_reverted:
            return

        warehouse = self.warehouse_id
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1) or self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

        if not picking_type:
            raise UserError(_("No internal transfer operation type found for warehouse/company."))

        source_location = line.cutpiece_location_dest_id or self.cutpiece_location_dest_id
        dest_location = line.label_id.branch_location_id or warehouse.lot_stock_id

        if not source_location:
            raise UserError(_("Cutpiece location not found for reversion."))

        # Check stock in cutpiece location before returning
        quants = self.env['stock.quant'].search([
            ('location_id', '=', source_location.id),
            ('product_id', '=', line.label_id.product_id.id),
        ])
        available_scrap = sum(quants.mapped('quantity'))
        if available_scrap < line.transfer_weight:
            raise UserError(_(
                "Cannot revert cut piece: Not enough scrap on hand in '%(loc)s'. Available: %(avail)s g, Required: %(req)s g."
            ) % {
                'loc': source_location.display_name,
                'avail': available_scrap,
                'req': line.transfer_weight,
            })

        # Create reversal internal transfer picking
        return_picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': source_location.id,
            'location_dest_id': dest_location.id,
            'origin': f"{self.name} - Cutpiece Reversal",
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'branch_id': self.branch_id.id if getattr(self, 'branch_id', False) else False,
        })

        move = self.env['stock.move'].create({
            'name': f"Revert Scrap: {line.label_id.name}",
            'product_id': line.label_id.product_id.id,
            'product_uom_qty': line.transfer_weight,
            'product_uom': line.label_id.product_id.uom_id.id,
            'location_id': source_location.id,
            'location_dest_id': dest_location.id,
            'picking_id': return_picking.id,
            'label_id': False,
            'branch_id': self.branch_id.id if getattr(self, 'branch_id', False) else False,
            'company_id': self.company_id.id,
        })

        return_picking.action_confirm()
        return_picking.action_assign()

        move.picked = True
        if move.move_line_ids:
            for ml in move.move_line_ids:
                ml.quantity = ml.quantity_product_uom or move.product_uom_qty
                ml.picked = True
        else:
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': return_picking.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
                'quantity': move.product_uom_qty,
                'picked': True,
            })

        res = return_picking.button_validate()
        if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
            wiz = self.env['stock.backorder.confirmation'].with_context(res.get('context', {})).create({})
            wiz.process()

        # Restore original label gross weight
        if line.label_id and line.original_weight > 0:
            label_vals = {}
            if 'sale_gross_weight' in line.label_id._fields:
                label_vals['sale_gross_weight'] = line.original_weight
            if 'purchase_gross_weight' in line.label_id._fields:
                label_vals['purchase_gross_weight'] = line.original_weight
            if label_vals:
                line.label_id.sudo().with_context(cutpiece_weight_update=True).write(label_vals)
                line.label_id.sudo().message_post(body=_(
                    "Cut piece transfer REVERTED on %(order)s (%(weight)s g returned to %(dest)s). "
                    "Label gross weight restored from %(old_weight)s g to %(new_weight)s g.",
                    order=self.name,
                    weight=line.transfer_weight,
                    dest=dest_location.display_name,
                    old_weight=line.sold_weight,
                    new_weight=line.original_weight,
                ))

        # Restore Sale Order line(s) for this label back to original weight
        so_lines = self.order_line.filtered(lambda l: l.label_id == line.label_id)
        for sol in so_lines:
            sol_vals = {
                'product_uom_qty': line.original_weight,
            }
            if 'sale_gross_weight' in sol._fields:
                sol_vals['sale_gross_weight'] = line.original_weight
            sol.sudo().write(sol_vals)

            # Recompute weights and pricing fields
            if hasattr(sol, '_compute_net_weight'):
                sol._compute_net_weight()
            if hasattr(sol, '_compute_metal_amounts'):
                sol._compute_metal_amounts()
            if hasattr(sol, '_compute_mc_amount'):
                sol._compute_mc_amount()
            if hasattr(sol, '_compute_subtotal'):
                sol._compute_subtotal()
            if hasattr(sol, '_compute_price_unit'):
                sol._compute_price_unit()

            # Update customer delivery picking move quantity if delivery is active
            for move in sol.move_ids.filtered(lambda m: m.state not in ('done', 'cancel') and m.picking_code == 'outgoing'):
                move.product_uom_qty = line.original_weight
                for ml in move.move_line_ids.filtered(lambda l: l.state not in ('done', 'cancel')):
                    ml.quantity = line.original_weight

        self.message_post(body=_(
            "Cut piece transfer for label '%(label)s' was reverted: %(weight)s g returned to stock, "
            "label weight restored to %(orig)s g, and Sale Order line restored to %(orig)s g.",
            label=line.label_id.name if line.label_id else '',
            weight=line.transfer_weight,
            orig=line.original_weight,
        ))

        line.write({
            'is_transferred': False,
            'is_reverted': True,
            'state': 'reverted',
            'return_picking_id': return_picking.id,
        })

    def action_revert_cutpiece_transfers(self):
        """Action button to revert all active cut piece transfers on the order"""
        for order in self:
            transferred_lines = order.cutpiece_line_ids.filtered(lambda l: l.is_transferred and not l.is_reverted)
            if not transferred_lines:
                raise UserError(_("No active cut piece transfers found to revert."))
            for line in transferred_lines:
                order._revert_cutpiece_line(line)
            order.is_transferred = False
            order.message_post(body=_(
                "Cut piece transfers reverted: Scrap returned to branch stock and original label gross weights restored."
            ))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Transfers Reverted"),
                    'message': _("All cut piece transfers have been reversed and label weights restored to original."),
                    'sticky': False,
                    'type': 'success',
                }
            }
        return True

    def action_transfer_remaining_stock(self):
        """Manual transfer trigger if user explicitly invokes it"""
        for order in self:
            order._create_and_validate_cutpiece_transfers()
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'cutpiece_line_ids' in vals:
                vals.pop('cutpiece_line_ids', None)
        orders = super(SaleOrder, self).create(vals_list)
        for order in orders:
            if order.is_transfer_remaining:
                order._sync_cutpiece_lines_with_order_lines()
        return orders

    def write(self, vals):
        if 'order_line' in vals or 'is_transfer_remaining' in vals:
            vals.pop('cutpiece_line_ids', None)
        elif 'cutpiece_line_ids' in vals:
            clean_cmds = []
            for cmd in vals['cutpiece_line_ids']:
                if isinstance(cmd, (list, tuple)) and cmd[0] == 0:
                    if cmd[2] and not cmd[2].get('label_id'):
                        continue
                clean_cmds.append(cmd)
            vals['cutpiece_line_ids'] = clean_cmds

        res = super(SaleOrder, self).write(vals)
        if 'order_line' in vals or 'is_transfer_remaining' in vals:
            for order in self:
                if order.state in ('draft', 'sent') and order.is_transfer_remaining:
                    order._sync_cutpiece_lines_with_order_lines()
        return res

    def action_confirm(self):
        for order in self:
            # Guard: Prevent partial weight sale without enabling Transfer Remaining
            if not order.is_transfer_remaining:
                untransferred_scraps = []
                for line in order.order_line:
                    label = line.label_id
                    if not label:
                        continue
                    gross = label.sale_gross_weight or label.tag_weight or label.purchase_gross_weight or 0.0
                    sold = line.product_uom_qty or 0.0
                    rem = round(gross - sold, 3)
                    if rem > 0.0001:
                        untransferred_scraps.append(
                            _("• Label '%(label)s': Original weight is %(gross)s g, but sold weight is %(sold)s g (%(rem)s g remaining).") % {
                                'label': label.name, 'gross': gross, 'sold': sold, 'rem': rem,
                            }
                        )
                if untransferred_scraps:
                    raise UserError(_(
                        "You are selling a partial weight from the following label(s), but 'Transfer Remaining Weight' is not enabled:\n\n"
                        "%(details)s\n\n"
                        "Please enable 'Transfer Remaining Weight' so the remaining scrap is properly transferred to the cut piece location, or adjust the sold weight back to the full label weight."
                    ) % {'details': "\n".join(untransferred_scraps)})

            if order.is_transfer_remaining:
                order._sync_cutpiece_lines_with_order_lines()

                # Validation 1: Check for oversale beyond tag gross weight
                oversale_errors = []
                for line in order.order_line:
                    label = line.label_id
                    if not label:
                        continue
                    gross = label.sale_gross_weight or label.tag_weight or label.purchase_gross_weight or 0.0
                    sold = line.product_uom_qty or 0.0
                    if round(sold - gross, 3) > 0.0001:
                        oversale_errors.append(_(
                            "• %s: Sold weight (%s g) exceeds original gross weight (%s g)."
                        ) % (label.name, sold, gross))

                if oversale_errors:
                    raise ValidationError(_(
                        "Cannot confirm sale order because sold weight exceeds label gross weight:\n\n%s"
                    ) % "\n".join(oversale_errors))

                # Validation 2: Ensure cut pieces exist if toggle is ON
                if not order.cutpiece_line_ids:
                    raise UserError(_(
                        "You have enabled 'Transfer Remaining Stock', but no cut pieces were detected. "
                        "Please verify order line weights, or turn off 'Transfer Remaining Stock' before confirming."
                    ))

                # Automatically create and validate the scrap transfer picking!
                order._create_and_validate_cutpiece_transfers()

        return super(SaleOrder, self).action_confirm()

    def action_cancel(self):
        """Automatic Rollback on order cancellation"""
        for order in self:
            if order.is_transfer_remaining:
                transferred_lines = order.cutpiece_line_ids.filtered(lambda l: l.is_transferred and not l.is_reverted)
                if transferred_lines:
                    for line in transferred_lines:
                        order._revert_cutpiece_line(line)
                    order.is_transferred = False
                    order.message_post(body=_(
                        "Order Cancelled: All completed cut piece transfers were automatically reversed and label weights restored to original."
                    ))
        return super(SaleOrder, self).action_cancel()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.constrains('product_uom_qty', 'label_id')
    def _check_cutpiece_sold_qty(self):
        for line in self:
            if line.order_id.is_transfer_remaining and line.label_id:
                gross = (
                    line.label_id.sale_gross_weight
                    or line.label_id.tag_weight
                    or line.label_id.purchase_gross_weight
                    or 0.0
                )
                if gross > 0 and round(line.product_uom_qty - gross, 3) > 0.0001:
                    raise ValidationError(_(
                        "For label '%(label)s', sold weight (%(sold)s g) cannot exceed the original gross weight (%(gross)s g)."
                    ) % {
                        'label': line.label_id.name,
                        'sold': line.product_uom_qty,
                        'gross': gross,
                    })

    def unlink(self):
        orders = self.mapped('order_id').filtered(lambda o: o.is_transfer_remaining and o.state in ('draft', 'sent'))
        res = super(SaleOrderLine, self).unlink()
        for order in orders:
            order._sync_cutpiece_lines_with_order_lines()
        return res


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        res = super(StockPicking, self)._action_done()
        for picking in self:
            cutpiece_lines = self.env['sale.order.cutpiece.line'].search([('picking_id', '=', picking.id)])
            for line in cutpiece_lines:
                if line.label_id and line.sold_weight > 0 and not line.is_reverted:
                    label_vals = {}
                    if 'sale_gross_weight' in line.label_id._fields and line.label_id.sale_gross_weight != line.sold_weight:
                        label_vals['sale_gross_weight'] = line.sold_weight
                    if 'purchase_gross_weight' in line.label_id._fields and line.label_id.purchase_gross_weight != line.sold_weight:
                        label_vals['purchase_gross_weight'] = line.sold_weight
                    if label_vals:
                        line.label_id.sudo().with_context(cutpiece_weight_update=True).write(label_vals)
        return res
