from math import ceil
from odoo import models, api, fields


class AccountMove(models.Model):
    _inherit = 'account.move'

    amount_rounding = fields.Monetary(
        string="Round Off",
        currency_field='currency_id',
        default=0.0,
    )

    # --- 1. Update Invoice Frontend Widget Totals ---
    @api.depends_context('lang')
    @api.depends(
        'invoice_line_ids.price_subtotal', 
        'invoice_line_ids.tax_ids', 
        'invoice_payment_term_id', 
        'partner_id', 
        'currency_id', 
        'amount_rounding'
    )
    def _compute_tax_totals(self):
        # Calculate original totals first
        super()._compute_tax_totals()

        for move in self:
            if move.move_type != 'out_invoice':
                continue

            if not move.tax_totals:
                continue

            # Bypass modification if gold bullion rules apply
            has_gold_bullion = move.invoice_line_ids.filtered(
                lambda l: l.product_id.name == 'Gold Bullion'
            )
            if has_gold_bullion:
                continue

            # Ensure we are modifying a regular dict copy
            tax_totals = dict(move.tax_totals)
            original_total = tax_totals.get('amount_total', 0.0)

            # Simple logic: If no manual rounding value is provided, fallback to standard display
            if not move.amount_rounding:
                tax_totals['display_rounding'] = False
                move.tax_totals = tax_totals
                continue

            # Direct addition logic
            new_total = original_total + move.amount_rounding
            rounding_amount = move.amount_rounding

            # Format the data according to Odoo UI standards
            tax_totals['display_rounding'] = True
            tax_totals['rounding_amount'] = rounding_amount
            tax_totals['formatted_rounding_amount'] = (
                move.currency_id.symbol + " %.2f" % rounding_amount
            )

            tax_totals['amount_total'] = new_total
            tax_totals['formatted_amount_total'] = move.currency_id.format(new_total)

            # Assign back the updated object to refresh the view layer
            move.tax_totals = tax_totals


    # --- 2. Update Invoice Backend Database Record Values (Total, Residual & Signed Fields) ---
    @api.depends(
        'invoice_line_ids.price_subtotal', 
        'invoice_line_ids.tax_ids', 
        'line_ids.amount_currency', 
        'line_ids.balance', 
        'amount_rounding'
    )
    def _compute_amount(self):
        # Calculate baseline amounts first (including amount_total and amount_residual)
        super()._compute_amount()

        for move in self:
            if move.move_type != 'out_invoice':
                continue

            if not move.amount_rounding:
                continue

            # Bypass modification if gold bullion rules apply
            has_gold_bullion = move.invoice_line_ids.filtered(
                lambda l: l.product_id.name == 'Gold Bullion'
            )
            if has_gold_bullion:
                continue

            # Update the master total fields (Both normal and company-currency signed version)
            move.amount_total = move.amount_total + move.amount_rounding
            move.amount_total_signed = move.amount_total_signed + move.amount_rounding
            
            # Update the residual fields so the UI "Amount Due" matches perfectly
            move.amount_residual = move.amount_residual + move.amount_rounding
            move.amount_residual_signed = move.amount_residual_signed + move.amount_rounding
            # move.amount_total_in_currency_signed = move.amount_total_in_currency_signed + move.amount_rounding


# from math import ceil
# from odoo import models, api, fields


# class AccountMove(models.Model):
#     _inherit = 'account.move'

#     amount_rounding = fields.Monetary(
#         string="Round Off",
#         currency_field='currency_id',
#         default=0.0,
#     )

#     @api.depends_context('lang')
#     @api.depends('invoice_line_ids.price_subtotal','invoice_line_ids.tax_ids','invoice_payment_term_id','partner_id','currency_id','amount_rounding')
#     def _compute_tax_totals(self):
#         super()._compute_tax_totals()

#         for move in self:

#             if move.move_type != 'out_invoice':
#                 continue

#             if not move.tax_totals:
#                 continue

#             has_gold_bullion = move.invoice_line_ids.filtered(
#                 lambda l: l.product_id.name == 'Gold Bullion'
#             )

#             if has_gold_bullion:
#                 continue

#             tax_totals = dict(move.tax_totals)

#             original_total = tax_totals.get('amount_total', 0.0)

#             if not move.amount_rounding:
#                 tax_totals['display_rounding'] = False
#                 move.tax_totals = tax_totals
#                 continue

#             adjusted_total = original_total + move.amount_rounding

#             rounded_total = ceil(adjusted_total / 100.0) * 100

#             rounding_amount = rounded_total - original_total

#             tax_totals['display_rounding'] = True
#             tax_totals['rounding_amount'] = rounding_amount
#             tax_totals['formatted_rounding_amount'] = (
#                 move.currency_id.symbol + " %.2f" % rounding_amount
#             )

#             tax_totals['amount_total'] = rounded_total
#             tax_totals['formatted_amount_total'] = (
#                 move.currency_id.symbol + " %.2f" % rounded_total
#             )

#             move.tax_totals = tax_totals

#     @api.depends('invoice_line_ids.price_subtotal','invoice_line_ids.tax_ids','line_ids.amount_currency','line_ids.balance','amount_rounding')
#     def _compute_amount(self):
#         super()._compute_amount()

#         for move in self:

#             if move.move_type != 'out_invoice':
#                 continue

#             if not move.amount_rounding:
#                 continue

#             has_gold_bullion = move.invoice_line_ids.filtered(
#                 lambda l: l.product_id.name == 'Gold Bullion'
#             )

#             if has_gold_bullion:
#                 continue

#             adjusted_total = move.amount_total + move.amount_rounding

#             move.amount_total = ceil(adjusted_total / 100.0) * 100


  