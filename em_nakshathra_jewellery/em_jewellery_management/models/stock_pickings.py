from odoo import models, fields, api, _
from odoo.tools.float_utils import float_compare

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

    @api.onchange('is_multiple_transfer', 'location_dest_id')
    def _onchange_is_multiple_transfer(self):
        if not self.is_multiple_transfer and self.location_dest_id:
            for move in self.move_ids_without_package:
                move.location_dest_id = self.location_dest_id.id


class StockMove(models.Model):
    _inherit = 'stock.move'

    purity_id = fields.Many2one('gold.purity')
    grams = fields.Float(string="Grams", digits=(16, 3))
    label_id = fields.Many2one(
            'product.label',
            string="Label",
        )
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
            if move.location_dest_id.usage == 'internal':
                vals['branch_location_id'] = move.location_dest_id.id
                if move.location_dest_id.usage == 'internal':
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
                msg = _(
                    "<b>Stock Transfer Completed</b> (%s)<br/>"
                    "• From: %s<br/>"
                    "• To: %s<br/>"
                    "• Branch: %s"
                ) % (
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

