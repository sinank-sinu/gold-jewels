import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        res = super(StockPicking, self).button_validate()
        for picking in self:
            if picking.state == 'done':
                _logger.info("Picking %s validated, creating metal ledger entries", picking.name)
                picking._create_metal_ledger_entries()
        return res

    def _create_metal_ledger_entries(self):
        MetalLedger = self.env['metal.ledger']
        for picking in self:
            for move in picking.move_ids:
                if move.state != 'done':
                    continue
                
                # Check for Purchase Order
                if move.purchase_line_id:
                    line = move.purchase_line_id
                    order = line.order_id
                    
                    # Exclude Old Gold Purchase
                    if order.is_old_gold:
                        _logger.info("Skipping Metal Ledger for Old Gold Purchase PO %s", order.name)
                        continue

                    if not line.purity_id:
                        continue

                    # Calculate proportional weights for this move
                    # Original line proportions
                    total_qty = line.product_qty or 1.0
                    move_ratio = move.product_uom_qty / total_qty
                    
                    metal_fine = line.fine_weight * move_ratio
                    mc_fine = getattr(line, 'mc_fine', 0.0) * move_ratio
                    fine_weight = metal_fine + mc_fine

                    if fine_weight <= 0:
                        continue

                    # Avoid duplicate for this move
                    existing = MetalLedger.search([('picking_id', '=', picking.id), ('purchase_order_id', '=', order.id), ('metal_id', '=', line.purity_id.id), ('fine_weight', '=', fine_weight)])
                    if existing:
                        continue

                    MetalLedger.create({
                        'date': fields.Date.today(),
                        'voucher_name': picking.name,
                        'transaction_type': 'purchase',
                        'metal_id': line.purity_id.id,
                        'metal_fine': metal_fine,
                        'mc_fine': mc_fine,
                        'fine_weight': fine_weight,
                        'stock_in': fine_weight,
                        'stock_out': 0.0,
                        'purchase_order_id': order.id,
                        'picking_id': picking.id,
                        'partner_id': picking.partner_id.id,
                        'branch_id': picking.branch_id.id if hasattr(picking, 'branch_id') else False,
                    })

                # Check for Sale Order
                elif move.sale_line_id:
                    line = move.sale_line_id
                    order = line.order_id

                    # Exclude Old Gold Sales if needed (usually these are exchanges)
                    # Monitoring has_old_gold to skip if it's primarily an old gold transaction
                    if order.has_old_gold:
                        _logger.info("Skipping Metal Ledger for Old Gold Sale (Exchange) SO %s", order.name)
                        continue

                    if not line.purity_id:
                        continue

                    # Calculate proportional weights
                    total_qty = line.product_uom_qty or 1.0
                    move_ratio = move.product_uom_qty / total_qty
                    
                    # Same logic as in original sale_order.py
                    metal_fine = line.fine_weight
                    if not metal_fine and line.net_weight and line.purity_id.percentage:
                        metal_fine = line.net_weight * (line.purity_id.percentage / 100.0)
                    
                    metal_fine = metal_fine * move_ratio
                    mc_fine = 0.0 # Default for sales in original logic
                    fine_weight = metal_fine + mc_fine

                    if fine_weight <= 0:
                        continue

                    # Avoid duplicate
                    existing = MetalLedger.search([('picking_id', '=', picking.id), ('sale_order_id', '=', order.id), ('metal_id', '=', line.purity_id.id), ('fine_weight', '=', fine_weight)])
                    if existing:
                        continue

                    MetalLedger.create({
                        'date': fields.Date.today(),
                        'voucher_name': picking.name,
                        'transaction_type': 'sale',
                        'metal_id': line.purity_id.id,
                        'metal_fine': metal_fine,
                        'mc_fine': mc_fine,
                        'fine_weight': fine_weight,
                        'stock_in': 0.0,
                        'stock_out': fine_weight,
                        'sale_order_id': order.id,
                        'picking_id': picking.id,
                        'partner_id': picking.partner_id.id,
                        'branch_id': picking.branch_id.id if hasattr(picking, 'branch_id') else False,
                    })
