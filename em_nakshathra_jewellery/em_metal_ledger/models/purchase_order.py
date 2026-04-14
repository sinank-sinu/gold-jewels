import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'


    def _create_metal_ledger_entries(self):
        MetalLedger = self.env['metal.ledger']
        for order in self:
            # Avoid duplicate ledger entries
            existing = MetalLedger.search([('purchase_order_id', '=', order.id)])
            if existing:
                _logger.info("Ledger entries already exist for PO %s", order.name)
                continue

            for line in order.order_line:
                if not line.purity_id:
                    continue

                # Ensure values are accessed to trigger computation
                metal_fine = line.fine_weight
                mc_fine = getattr(line, 'mc_fine', 0.0)
                fine_weight = metal_fine + mc_fine

                if fine_weight <= 0:
                    _logger.warning("Line %s has 0 fine weight, skipping ledger", line.name)
                    continue

                _logger.info("Creating ledger entry for PO %s line %s: %s grams", order.name, line.name, fine_weight)
                MetalLedger.create({
                    'date': order.date_order.date() if order.date_order else fields.Date.today(),
                    'voucher_name': order.name,
                    'transaction_type': 'purchase',
                    'metal_id': line.purity_id.id,
                    'metal_fine': metal_fine,
                    'mc_fine': mc_fine,
                    'fine_weight': fine_weight,
                    'stock_in': fine_weight,
                    'stock_out': 0.0,
                    'purchase_order_id': order.id,
                })
