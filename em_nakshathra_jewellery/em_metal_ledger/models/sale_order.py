import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'


    def _create_metal_ledger_entries(self):
        MetalLedger = self.env['metal.ledger']
        for order in self:
            # Avoid duplicate ledger entries
            existing = MetalLedger.search([('sale_order_id', '=', order.id)])
            if existing:
                _logger.info("Ledger entries already exist for SO %s", order.name)
                continue

            for line in order.order_line:
                if not line.purity_id:
                    continue
                # Use fine_weight from sale order line (it is a float field)
                # If 0, try to compute from net_weight and purity percentage
                metal_fine = line.fine_weight
                if not metal_fine and line.net_weight and line.purity_id.percentage:
                    metal_fine = line.net_weight * (line.purity_id.percentage / 100.0)
                
                # MC fine: default to 0 for sales unless specifically tracked
                mc_fine = 0.0
                fine_weight = metal_fine + mc_fine

                if fine_weight <= 0:
                    _logger.warning("Line %s has 0 fine weight, skipping ledger", line.name)
                    continue

                _logger.info("Creating ledger entry for SO %s line %s: %s grams", order.name, line.name, fine_weight)
                MetalLedger.create({
                    'date': order.date_order.date() if order.date_order else fields.Date.today(),
                    'voucher_name': order.name,
                    'transaction_type': 'sale',
                    'metal_id': line.purity_id.id,
                    'metal_fine': metal_fine,
                    'mc_fine': mc_fine,
                    'fine_weight': fine_weight,
                    'stock_in': 0.0,
                    'stock_out': fine_weight,
                    'sale_order_id': order.id,
                })
