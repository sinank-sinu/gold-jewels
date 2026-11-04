from odoo import models, fields, api

class SaleOrderCutpieceLine(models.Model):
    _name = 'sale.order.cutpiece.line'
    _description = 'Sale Order Cutpiece Line'
    _order = 'id desc'

    order_id = fields.Many2one(
        'sale.order',
        string="Sale Order",
        ondelete='cascade',
        required=True,
        index=True,
    )
    label_id = fields.Many2one(
        'product.label',
        string="Label to Transfer",
        required=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string="Product",
        related='label_id.product_id',
        store=True,
        readonly=True,
    )
    original_weight = fields.Float(
        string="Label Gross Weight (g)",
        digits=(16, 3),
        store=True,
        readonly=True,
    )
    sold_weight = fields.Float(
        string="Sold Weight (g)",
        digits=(16, 3),
        store=True,
        readonly=True,
    )
    transfer_weight = fields.Float(
        string="Remaining Weight (g)",
        digits=(16, 3),
        store=True,
        readonly=True,
    )
    cutpiece_location_dest_id = fields.Many2one(
        'stock.location',
        string="Cutpiece Location",
        domain="[('usage', '=', 'internal')]",
    )
    dest_location_weight = fields.Float(
        string="Qty in Dest Location (g)",
        compute="_compute_dest_location_weight",
        digits=(16, 3),
    )
    is_transferred = fields.Boolean(
        string="Is Transferred",
        default=False,
        copy=False,
    )
    is_reverted = fields.Boolean(
        string="Is Reverted",
        default=False,
        copy=False,
    )
    picking_id = fields.Many2one(
        'stock.picking',
        string="Transfer Picking",
        readonly=True,
        copy=False,
    )
    return_picking_id = fields.Many2one(
        'stock.picking',
        string="Reversal Picking",
        readonly=True,
        copy=False,
    )
    state = fields.Selection([
        ('draft', 'Pending Confirmation'),
        ('done', 'Transferred'),
        ('reverted', 'Reverted'),
    ], string="Status", default='draft', copy=False)

    @api.depends('label_id', 'cutpiece_location_dest_id')
    def _compute_dest_location_weight(self):
        for line in self:
            if line.label_id and line.cutpiece_location_dest_id:
                domain = [
                    ('location_id', '=', line.cutpiece_location_dest_id.id),
                    ('product_id', '=', line.label_id.product_id.id),
                ]
                if 'label_id' in self.env['stock.quant']._fields:
                    domain.append(('label_id', '=', line.label_id.id))
                quants = self.env['stock.quant'].search(domain)
                line.dest_location_weight = sum(quants.mapped('quantity'))
            else:
                line.dest_location_weight = 0.0

    def action_revert_single_cutpiece(self):
        """Action button to revert a single cut piece line"""
        self.ensure_one()
        return self.order_id._revert_single_cutpiece_action(self)
