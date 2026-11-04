from odoo import models, fields, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    amount_rounding = fields.Monetary(
        string="Round Off",
        currency_field='currency_id',
        default=0.0,
        store=True,
    )

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.is_sale_return_po and not (self.is_old_gold or getattr(self, 'is_diamond_og', False)):
            vals.update({
                'amount_rounding': self.amount_rounding,
            })
        return vals

    # --- 1. Update Frontend Widget Totals ---
    @api.depends_context('lang')
    @api.depends(
        'order_line.taxes_id',
        'order_line.price_unit',
        'amount_total',
        'amount_untaxed',
        'amount_rounding',
        'is_old_gold',
        'is_sale_return_po',
    )
    def _compute_tax_totals(self):
        super()._compute_tax_totals()

        for order in self:
            if not order.tax_totals:
                continue

            if not (order.is_old_gold or order.is_sale_return_po or getattr(order, 'is_diamond_og', False)):
                continue

            tax_totals = dict(order.tax_totals)
            original_total = tax_totals.get('amount_total', 0.0)

            if not order.amount_rounding:
                tax_totals['display_rounding'] = False
                order.tax_totals = tax_totals
                continue

            new_total = original_total + order.amount_rounding
            rounding_amount = order.amount_rounding

            tax_totals['display_rounding'] = True
            tax_totals['rounding_amount'] = rounding_amount
            tax_totals['formatted_rounding_amount'] = (
                order.currency_id.symbol + " %.2f" % rounding_amount
            )

            tax_totals['amount_total'] = new_total
            tax_totals['formatted_amount_total'] = order.currency_id.format(new_total)

            order.tax_totals = tax_totals

    @api.depends(
        'order_line.price_total',
        'order_line.price_subtotal',
        'amount_rounding',
        'is_old_gold',
        'is_sale_return_po',
    )
    def _amount_all(self):
        super()._amount_all()
        for order in self:
            if not (order.is_old_gold or order.is_sale_return_po or getattr(order, 'is_diamond_og', False)):
                continue
            if not order.amount_rounding:
                continue
            order.amount_total = order.amount_total + order.amount_rounding