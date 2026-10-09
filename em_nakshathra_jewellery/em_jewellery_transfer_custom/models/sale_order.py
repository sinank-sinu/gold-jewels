from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    available_transfer_label_ids = fields.Many2many('product.label', compute='_compute_available_transfer_labels')
    
    # We override the existing field to add the default value.
    cutpiece_location_dest_id = fields.Many2one(
        'stock.location', 
        string="Cutpiece Location", 
        domain="[('usage', '=', 'internal')]", 
        copy=False,
    )

    @api.onchange('branch_id')
    def _onchange_branch_id_for_cutpiece(self):
        if getattr(self, 'branch_id', False) and getattr(self.branch_id, 'cutpiece_location_id', False):
            self.cutpiece_location_dest_id = self.branch_id.cutpiece_location_id.id

    dest_location_weight = fields.Float(
        string="Quantity in Location", 
        compute="_compute_dest_location_weight", 
        digits=(16, 3)
    )

    is_transfer_remaining = fields.Boolean(string="Transfer Remaining Stock", default=False, copy=False)
    transfer_label_id = fields.Many2one('product.label', string="Label to Transfer", copy=False)

    transfer_weight = fields.Float(string="Remaining Weight (g)", compute="_compute_transfer_weight", digits=(16, 3))
    is_transferred = fields.Boolean(string="Is Transferred", default=False, copy=False)

    @api.depends('transfer_label_id', 'order_line.product_uom_qty', 'order_line.label_id')
    def _compute_transfer_weight(self):
        for order in self:
            if not order.transfer_label_id:
                order.transfer_weight = 0.0
                continue
            
            # Find total weight sold for this label in this order
            sold_weight = sum(order.order_line.filtered(lambda l: l.label_id == order.transfer_label_id).mapped('product_uom_qty'))
            order.transfer_weight = order.transfer_label_id.sale_gross_weight - sold_weight

    def action_transfer_remaining_stock(self):
        for order in self:
            from odoo.exceptions import UserError
            from odoo import _
            if not order.transfer_label_id or not order.cutpiece_location_dest_id:
                raise UserError(_("Please select a label and a destination location to transfer."))
            if order.transfer_weight <= 0:
                raise UserError(_("There is no remaining weight to transfer for the selected label."))
            if order.is_transferred:
                raise UserError(_("The remaining stock has already been transferred."))

            warehouse = order.warehouse_id
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('warehouse_id', '=', warehouse.id)
            ], limit=1)
            if not picking_type:
                picking_type = self.env['stock.picking.type'].search([
                    ('code', '=', 'internal'),
                    ('company_id', '=', order.company_id.id)
                ], limit=1)

            source_location = order.transfer_label_id.branch_location_id or warehouse.lot_stock_id

            quants = self.env['stock.quant'].search([
                ('location_id', '=', source_location.id),
                ('product_id', '=', order.transfer_label_id.product_id.id)
            ])
            available_qty = sum(quants.mapped('quantity'))
            if available_qty < order.transfer_weight:
                raise UserError(_("There is not enough stock on hand for the product '%s' in the location '%s'. Available: %s g, Required to transfer: %s g.") % (
                    order.transfer_label_id.product_id.name, source_location.display_name, available_qty, order.transfer_weight))

            picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'location_id': source_location.id,
                'location_dest_id': order.cutpiece_location_dest_id.id,
                'origin': f"{order.name} - Remaining Transfer",
                'company_id': order.company_id.id,
                'branch_id': order.branch_id.id,
            })

            move = self.env['stock.move'].create({
                'name': f"Transfer Remaining: {order.transfer_label_id.name}",
                'product_id': order.transfer_label_id.product_id.id,
                'product_uom_qty': order.transfer_weight,
                'product_uom': order.transfer_label_id.product_id.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': order.cutpiece_location_dest_id.id,
                'picking_id': picking.id,
                'label_id': order.transfer_label_id.id,
                'branch_id': order.branch_id.id,
                'company_id': order.company_id.id,
            })

            picking.action_confirm()
            picking.action_assign()
            for move_line in picking.move_line_ids:
                move_line.quantity = move_line.quantity_product_uom
            picking.button_validate()

            order.is_transferred = True

    @api.depends('order_line.label_id')
    def _compute_available_transfer_labels(self):
        for order in self:
            order.available_transfer_label_ids = order.order_line.mapped('label_id')

    @api.depends('transfer_label_id', 'cutpiece_location_dest_id')
    def _compute_dest_location_weight(self):
        for order in self:
            if order.transfer_label_id and order.cutpiece_location_dest_id:
                domain = [
                    ('location_id', '=', order.cutpiece_location_dest_id.id),
                    ('product_id', '=', order.transfer_label_id.product_id.id)
                ]
                if 'label_id' in self.env['stock.quant']._fields:
                    domain.append(('label_id', '=', order.transfer_label_id.id))
                
                quants = self.env['stock.quant'].search(domain)
                order.dest_location_weight = sum(quants.mapped('quantity'))
            else:
                order.dest_location_weight = 0.0

    def action_confirm(self):
        from odoo.exceptions import UserError
        from odoo import _
        for order in self:
            if order.is_transfer_remaining and not order.is_transferred:
                raise UserError(_("You have enabled 'Transfer Remaining Stock'. Please click the 'Transfer Remaining' button to complete the transfer before confirming the order."))
        return super(SaleOrder, self).action_confirm()
