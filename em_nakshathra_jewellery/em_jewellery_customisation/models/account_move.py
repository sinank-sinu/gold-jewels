from math import ceil
from odoo import models, api


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.depends(
        'invoice_line_ids.price_subtotal',
        'invoice_line_ids.tax_ids',
        'line_ids.amount_currency',
        'line_ids.balance',
    )
    def _compute_amount(self):
        super()._compute_amount()

        for move in self:

            # Only Customer Invoice
            if move.move_type != 'out_invoice':
                continue

            # Skip Gold Bullion
            has_gold_bullion = move.invoice_line_ids.filtered(
                lambda l: l.product_id.name == 'Gold Bullion'
            )

            if has_gold_bullion:
                continue

            rounded_total = ceil(move.amount_total / 100.0) * 100

            move.amount_total = rounded_total
    

    @api.depends_context('lang')
    @api.depends(
        'invoice_line_ids.price_subtotal',
        'invoice_line_ids.tax_ids',
        'invoice_payment_term_id',
        'partner_id',
        'currency_id',
    )
    def _compute_tax_totals(self):
        super()._compute_tax_totals()

        for move in self:

            if move.move_type != 'out_invoice':
                continue

            if not move.tax_totals:
                continue

            # Skip Gold Bullion
            has_gold_bullion = move.invoice_line_ids.filtered(
                lambda l: l.product_id.name == 'Gold Bullion'
            )

            if has_gold_bullion:
                continue
            
            tax_totals = move.tax_totals

            original_total = tax_totals.get('amount_total', 0.0)

            rounded_total = ceil(original_total / 100.0) * 100

            round_off = rounded_total - original_total

            tax_totals['amount_total'] = rounded_total
            tax_totals['formatted_amount_total'] = (
                move.currency_id.symbol + " %.2f" % rounded_total
            )

            tax_totals['display_rounding'] = True
            tax_totals['rounding_amount'] = round_off
            tax_totals['formatted_rounding_amount'] = (
                move.currency_id.symbol + " %.2f" % round_off
            )

            move.tax_totals = tax_totals