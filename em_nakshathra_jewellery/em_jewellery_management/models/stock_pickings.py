from odoo import models, fields, api, _
from odoo.tools.float_utils import float_compare
from markupsafe import Markup
from odoo.exceptions import UserError, ValidationError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_old_gold = fields.Boolean(
        string="Old Gold Transfer",
        help="Indicates this picking is related to Old Gold movement"
    )
    sale_old_id = fields.Many2one('sale.order', ondelete='cascade')
    old_gold_issue_id = fields.Many2one(
        'old.gold.refinery.issue',
        string="Old Gold Issue"
    )
    lab_purity_id = fields.Many2one('lab.purity', string="Lab Purity")
    is_multiple_transfer = fields.Boolean(
        string="Multiple Transfer",
        help="Check this if you want to transfer to multiple locations in a single picking."
    )

    @api.onchange('is_multiple_transfer', 'location_id', 'location_dest_id')
    def _onchange_is_multiple_transfer(self):
        if not self.is_multiple_transfer:
            if self.location_id:
                for move in self.move_ids_without_package:
                    move.location_id = self.location_id.id
            if self.location_dest_id:
                for move in self.move_ids_without_package:
                    move.location_dest_id = self.location_dest_id.id

    def write(self, vals):
        res = super().write(vals)
        if 'location_id' in vals or 'location_dest_id' in vals:
            for picking in self:
                if not picking.is_multiple_transfer:
                    draft_ready_moves = picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
                    if 'location_id' in vals and picking.location_id:
                        draft_ready_moves.write({'location_id': picking.location_id.id})
                        draft_ready_moves.move_line_ids.filtered(lambda ml: ml.state not in ('done', 'cancel')).write({'location_id': picking.location_id.id})
                    if 'location_dest_id' in vals and picking.location_dest_id:
                        draft_ready_moves.write({'location_dest_id': picking.location_dest_id.id})
                        draft_ready_moves.move_line_ids.filtered(lambda ml: ml.state not in ('done', 'cancel')).write({'location_dest_id': picking.location_dest_id.id})
        return res

    def button_validate(self):
        for picking in self:
            # Sync move and move_line locations if not multiple_transfer
            if not picking.is_multiple_transfer:
                draft_ready_moves = picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
                if picking.location_id:
                    out_of_sync_src = draft_ready_moves.filtered(lambda m: m.location_id != picking.location_id)
                    if out_of_sync_src:
                        out_of_sync_src.write({'location_id': picking.location_id.id})
                        out_of_sync_src.move_line_ids.filtered(lambda ml: ml.state not in ('done', 'cancel')).write({'location_id': picking.location_id.id})
                if picking.location_dest_id:
                    out_of_sync_dest = draft_ready_moves.filtered(lambda m: m.location_dest_id != picking.location_dest_id)
                    if out_of_sync_dest:
                        out_of_sync_dest.write({'location_dest_id': picking.location_dest_id.id})
                        out_of_sync_dest.move_line_ids.filtered(lambda ml: ml.state not in ('done', 'cancel')).write({'location_dest_id': picking.location_dest_id.id})

            for move in picking.move_ids:
                if move.state in ('done', 'cancel'):
                    continue
                if not move.label_id:
                    continue
                # Auto-allocate available stock if physically in source location
                picking._auto_allocate_available_stock()
                # 1. Strict Validation Guard: Verify label physically belongs to source location
                # When a label is not yet stocked in (is_stocked_in == False), its physical stock is at source_location_id.
                # Once stocked in (is_stocked_in == True), its current physical location is branch_location_id.
                label_sudo = move.label_id.sudo()
                expected_loc = label_sudo.branch_location_id if label_sudo.is_stocked_in else label_sudo.source_location_id
                if move.location_id.usage == 'internal' and expected_loc and expected_loc != move.location_id:
                    current_loc = expected_loc.display_name
                    raise UserError(_(
                        "Cannot validate: Label %s is currently located at %s, not %s."
                    ) % (
                        label_sudo.display_name or label_sudo.name,
                        current_loc,
                        move.location_id.display_name
                    ))

                # 2. Anti-Concurrency Guard: Verify label is not reserved in another active transfer
                conflicting_move = self.env['stock.move'].sudo().search([
                    ('label_id', '=', move.label_id.id),
                    ('state', 'not in', ('done', 'cancel')),
                    ('id', '!=', move.id),
                    ('picking_id', '!=', picking.id),
                ], limit=1)
                if conflicting_move:
                    other_picking = conflicting_move.picking_id
                    transfer_ref = other_picking.name if other_picking else (conflicting_move.reference or _("another transfer"))
                    raise UserError(_(
                        "Label %s is already reserved in active transfer %s. Please cancel or validate that transfer first."
                    ) % (
                        label_sudo.display_name or label_sudo.name,
                        transfer_ref
                    ))

        return super().button_validate()

    def _auto_allocate_available_stock(self):
        """
        If physical/unreserved stock exists in move.location_id,
        automatically allocate the missing quantity into the move line,
        ensuring the full required quantity/weight is fulfilled.
        """
        for picking in self:
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                rounding = move.product_uom.rounding if move.product_uom else 0.001
                need = move.product_uom_qty - move.quantity
                if float_compare(need, 0, precision_rounding=rounding) > 0:
                    avail = self.env['stock.quant']._get_available_quantity(move.product_id, move.location_id)
                    if float_compare(avail, 0, precision_rounding=rounding) > 0:
                        qty_to_assign = min(need, avail)
                        move._update_reserved_quantity(qty_to_assign, move.location_id, strict=False)
                        move.picked = True
                        for ml in move.move_line_ids:
                            ml.picked = True

    def action_assign(self):
        res = super().action_assign()
        self._auto_allocate_available_stock()
        return res

    @api.depends('state', 'move_ids.product_uom_qty', 'move_ids.quantity')
    def _compute_show_check_availability(self):
        super()._compute_show_check_availability()
        for picking in self:
            if picking.state in ('confirmed', 'waiting', 'assigned'):
                if any(float_compare(m.product_uom_qty, m.quantity,
                                     precision_rounding=m.product_uom.rounding or 0.001) > 0 for m in picking.move_ids):
                    picking.show_check_availability = True

    def _create_backorder(self):
        # if not self.env.user.has_group('em_jewellery_management.group_allow_backorder_creation') and not self.env.is_superuser():
        #     raise UserError(_(
        #         "You are not authorized to create backorders. "
        #         "Only authorized supervisors/managers can create backorders. "
        #         "Please choose 'No Backorder' or contact your manager."
        #     ))
        return super()._create_backorder()


class StockMove(models.Model):
    _inherit = 'stock.move'

    purity_id = fields.Many2one('gold.purity')
    grams = fields.Float(string="Grams", digits=(16, 3))
    label_id = fields.Many2one(
            'product.label',
            string="Label",
        )
    def _update_reserved_quantity(self, need, location_id, quant_ids=None, lot_id=None, package_id=None, owner_id=None, strict=True):
        if self.picking_type_id.code == 'internal':
            strict = True
        return super()._update_reserved_quantity(need, location_id, quant_ids=quant_ids, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=strict)

    receive_voucher_line_id = fields.Many2one('jewellery.receive.voucher.line', string="Receive Voucher Line")

    branch_id = fields.Many2one(
        'res.branch', 
        string='Branch', 
        compute='_compute_branch_id', 
        store=True, 
        readonly=False,
        precompute=True
    )

    @api.depends('picking_id.branch_id', 'production_id.branch_id', 'raw_material_production_id.branch_id')
    def _compute_branch_id(self):
        for move in self:
            branch = False
            if move.picking_id:
                branch = move.picking_id.branch_id
            elif move.production_id:
                branch = move.production_id.branch_id
            elif move.raw_material_production_id:
                branch = move.raw_material_production_id.branch_id
            
            if branch:
                move.branch_id = branch.id
            else:
                # Fallback to user branch if not already set
                if not move.branch_id:
                    move.branch_id = self.env.user.branch_id.id

    @api.onchange('label_id', 'product_uom_qty', 'tax_id')
    def _onchange_label_id(self):
        if self.label_id:
            if not self.product_id and self.label_id.product_id:
                self.product_id = self.label_id.product_id.id
            self.purity_id = self.label_id.purity_id.id
            self.product_uom_qty = self.label_id.purchase_gross_weight

    @api.constrains('label_id', 'state')
    def _check_label_single_active_transfer(self):
        active_moves = self.filtered(lambda m: m.label_id and m.state not in ('done', 'cancel'))
        label_ids = active_moves.mapped('label_id.id')
        if len(label_ids) != len(set(label_ids)):
            for move in active_moves:
                duplicates = active_moves.filtered(lambda m: m.label_id == move.label_id and m.id != move.id)
                if duplicates:
                    raise ValidationError(_(
                        "Label %s cannot be added multiple times to the same transfer."
                    ) % (move.label_id.display_name or move.label_id.name))

        # for move in active_moves:
        #     domain = [
        #         ('label_id', '=', move.label_id.id),
        #         ('state', 'not in', ('done', 'cancel')),
        #         ('id', '!=', move.id),
        #     ]
        #     conflicting_move = self.search(domain, limit=1)
        #     if conflicting_move:
        #         other_picking = conflicting_move.picking_id
        #         transfer_ref = other_picking.name if other_picking else (conflicting_move.reference or _("another transfer"))
        #         raise ValidationError(_(
        #             "Label %s is already reserved in active transfer %s. Please cancel or validate that transfer first."
        #         ) % (
        #             move.label_id.display_name or move.label_id.name,
        #             transfer_ref
        #         ))

    def _get_price_unit(self):
        price = super()._get_price_unit()

        if self.purchase_line_id:
            pol = self.purchase_line_id

            subtotal = (
                    pol.metal_amount +
                    pol.mc_amount +
                    pol.stone_rate +
                    pol.diamond_rate
            )

            if pol.product_qty:
                price = subtotal / pol.product_qty
        
        if self.receive_voucher_line_id:
            rvl = self.receive_voucher_line_id
            if rvl.gross_weight:
                price = rvl.total_receive_fine_amount / rvl.gross_weight

        return price

    def _action_done(self, cancel_backorder=False):
        res = super()._action_done(cancel_backorder=cancel_backorder)
        moves_done = res if isinstance(res, models.Model) and res._name == 'stock.move' else self.filtered(lambda m: m.state == 'done')
        for move in moves_done:
            if move.state != 'done':
                continue
            rounding = move.product_uom.rounding if move.product_uom else 0.001
            if float_compare(move.quantity, 0.0, precision_rounding=rounding) <= 0:
                continue
            if not move.label_id:
                continue

            vals = {}
            if move.location_dest_id.usage in ('internal', 'transit'):
                vals['branch_location_id'] = move.location_dest_id.id
                vals['source_location_id'] = move.location_id.id
                branch = move.location_dest_id.branch_id or move.branch_id or (move.picking_id.branch_id if move.picking_id else False)
                if branch:
                    vals['branch_id'] = branch.id
            elif move.location_dest_id.usage == 'customer':
                vals['active'] = False
            if vals:
                move.label_id.with_context(from_stock_transfer=True).sudo().write(vals)

            # Post tracking log in Chatter
            try:
                transfer_ref = move.picking_id.name if move.picking_id else (move.reference or move.name)
                branch_name = branch.name if branch else (move.label_id.branch_id.name or _("N/A"))
                msg = Markup(_(
                    "<b>Stock Transfer Completed</b> (%s)<br/>"
                    "• From: %s<br/>"
                    "• To: %s<br/>"
                    "• Branch: %s"
                )) % (
                    transfer_ref,
                    move.location_id.display_name,
                    move.location_dest_id.display_name,
                    branch_name
                )
                move.label_id.sudo().message_post(body=msg)
            except Exception:
                pass
        return res

    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        fields = super()._prepare_merge_moves_distinct_fields()
        if 'label_id' not in fields:
            fields.append('label_id')
        return fields

    def _merge_moves(self, merge_into=False):
        """Do not merge moves for internal transfers or moves with different labels,
        preventing lines of the same variant from being summed together into a single move."""
        if merge_into and (
            merge_into.picking_type_id.code == 'internal' or
            (merge_into.picking_id and (merge_into.picking_id.picking_type_code == 'internal' or merge_into.picking_id.picking_type_id.code == 'internal'))
        ):
            return self

        moves_to_merge = self.filtered(
            lambda m: (m.picking_type_id.code or (m.picking_id and (m.picking_id.picking_type_code or m.picking_id.picking_type_id.code))) != 'internal'
        )
        moves_not_to_merge = self - moves_to_merge
        if not moves_to_merge:
            return self
        return super(StockMove, moves_to_merge)._merge_moves(merge_into=merge_into) | moves_not_to_merge


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    branch_id = fields.Many2one(
        'res.branch', 
        string='Branch', 
        store=True,
        readonly=False,
    )
    label_id = fields.Many2one(
        'product.label',
        string="Label",
        related='move_id.label_id',
        store=True,
    )
    is_quantity_done_editable = fields.Boolean(
        string="Is quantity done editable",
        compute='_compute_is_quantity_done_editable'
    )

    def _compute_is_quantity_done_editable(self):
        is_manager = self.env.user.has_group('base.group_system') or \
                     self.env.user.has_group('base.group_erp_manager')
        for line in self:
            line.is_quantity_done_editable = is_manager


class StockValuationLayer(models.Model):
    _inherit = 'stock.valuation.layer'

    branch_id = fields.Many2one(
        'res.branch', 
        string='Branch', 
        store=True,
        readonly=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('branch_id') and vals.get('stock_move_id'):
                move = self.env['stock.move'].browse(vals['stock_move_id'])
                if move.branch_id:
                    vals['branch_id'] = move.branch_id.id
            if not vals.get('branch_id'):
                vals['branch_id'] = self.env.user.branch_id.id
        return super().create(vals_list)


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_id, name, origin, company_id, values):
        move_values = super()._get_stock_move_values(product_id, product_qty, product_uom, location_id, name, origin, company_id, values)
        if values.get('label_id'):
            move_values['label_id'] = values['label_id']
        if values.get('purity_id'):
            move_values['purity_id'] = values['purity_id']
        return move_values

