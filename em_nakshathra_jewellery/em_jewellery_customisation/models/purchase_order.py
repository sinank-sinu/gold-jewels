from math import floor
from odoo import models, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.depends_context('lang')
    @api.depends(
        'order_line.taxes_id',
        'order_line.price_unit',
        'amount_total',
        'amount_untaxed',
    )
    def _compute_tax_totals(self):
        super()._compute_tax_totals()

        for order in self:

            # Apply only for Old Gold Purchase
            if not order.is_old_gold:
                continue

            if not order.tax_totals:
                continue

            tax_totals = order.tax_totals

            original_total = tax_totals.get('amount_total', 0.0)

            rounded_total = floor(original_total / 100.0) * 100

            round_off = rounded_total - original_total

            tax_totals['amount_total'] = rounded_total
            tax_totals['formatted_amount_total'] = (
                order.currency_id.symbol + " %.2f" % rounded_total
            )

            tax_totals['display_rounding'] = True
            tax_totals['rounding_amount'] = round_off
            tax_totals['formatted_rounding_amount'] = (
                order.currency_id.symbol + " %.2f" % round_off
            )

            order.tax_totals = tax_totals

    #need to hide  after the import
    # @api.depends('order_line.price_total', 'order_line.price_subtotal', 'order_line.price_unit', 'order_line.product_qty')
    # def _amount_all(self):
    #     super()._amount_all()
    #     for order in self:
    #         # Recompute total if custom price_subtotal evaluates to 0.0 but price_unit is provided (e.g., imports)
    #         if order.amount_untaxed == 0.0 and any(line.price_unit for line in order.order_line):
    #             amount_untaxed = sum(line.price_unit * line.product_qty for line in order.order_line)
    #             order.amount_untaxed = amount_untaxed
    #             order.amount_total = amount_untaxed + order.amount_tax