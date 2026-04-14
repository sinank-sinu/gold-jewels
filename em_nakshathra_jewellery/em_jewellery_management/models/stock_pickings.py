from odoo import models, fields,api

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


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    branch_id = fields.Many2one(
        'res.branch', 
        string='Branch', 
        store=True,
        readonly=False,
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

