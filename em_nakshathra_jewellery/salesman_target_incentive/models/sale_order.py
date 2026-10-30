# -*- coding: utf-8 -*-
from odoo import models, fields, _
from dateutil.relativedelta import relativedelta


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        res = super().action_confirm()
        self._update_salesman_targets()
        self._process_sale_return_deductions()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._update_salesman_targets()
        return res

    def _update_salesman_targets(self):
        Target = self.env['salesman.target']
        for order in self:
            if not order.date_order:
                continue
            order_date = order.date_order.date()
            salesmen_ids = set()
            if order.user_id:
                salesmen_ids.add(order.user_id.id)
            for line in order.order_line:
                if hasattr(line, 'salesman_id') and line.salesman_id:
                    salesmen_ids.add(line.salesman_id.id)

            for sid in salesmen_ids:
                targets = Target.search([
                    ('salesman_id', '=', sid),
                    ('branch_id', '=', order.branch_id.id),
                    ('date_from', '<=', order_date),
                    ('date_to', '>=', order_date),
                    ('state', 'in', ['draft', 'confirmed', 'transferred']),
                ])
                if targets:
                    targets._compute_achievements()
                    targets._incentive_add()

    def _process_sale_return_deductions(self):
        """When a sale order is confirmed with return lines or is_sale_return,
        create a pending incentive deduction scheduled for the NEXT calendar month."""
        Deduction = self.env['salesman.incentive.deduction']
        for order in self:
            is_return = getattr(order, 'is_sale_return', False)
            return_lines = getattr(order, 'sale_return_line_ids', False)
            if not is_return and not return_lines:
                continue

            salesman = order.user_id
            if not salesman:
                continue

            order_date = order.date_order.date() if order.date_order else fields.Date.today()
            next_month_start = (order_date + relativedelta(months=1)).replace(day=1)
            next_month_end = next_month_start + relativedelta(months=1, days=-1)

            total_return_amount = 0.0
            total_return_grams = 0.0
            total_deduction_amount = 0.0

            if return_lines:
                for r_line in return_lines:
                    grams = r_line.net_weight or r_line.gross_weight or 1.0
                    amt = r_line.amount or (grams * (r_line.rate or 0.0))
                    purity_name = (r_line.purity_id.name or '').upper().strip() if r_line.purity_id else ''

                    total_return_amount += amt
                    total_return_grams += grams

                    # Clawback rate based on purity
                    if '18KTD' in purity_name:
                        rate_pct = 8.0
                    elif '18CT' in purity_name:
                        rate_pct = 5.0
                    elif '22CT' in purity_name or '22KT' in purity_name or '22K' in purity_name:
                        rate_pct = 2.0
                    else:
                        rate_pct = 2.0

                    # Making charge clawback or proportional rate
                    line_mc = getattr(r_line, 'mc_amount', 0.0) or (amt * 0.10)
                    total_deduction_amount += line_mc * (rate_pct / 100.0)
            else:
                total_return_amount = abs(order.amount_total or 0.0)
                total_deduction_amount = total_return_amount * 0.02

            if total_deduction_amount > 0:
                ded_rec = Deduction.create({
                    'salesman_id': salesman.id,
                    'branch_id': order.branch_id.id if order.branch_id else False,
                    'sale_order_ids': [(6, 0, [order.id])],
                    'sale_order_id': order.id,
                    'return_date': order_date,
                    'return_amount': total_return_amount,
                    'return_grams': total_return_grams,
                    'deduction_amount': round(total_deduction_amount, 2),
                    'deduction_month_start': next_month_start,
                    'deduction_month_end': next_month_end,
                    'notes': _('Automatic deduction from confirmed sale return order %s') % order.name,
                    'state': 'pending',
                })
                order.message_post(
                    body=_(
                        "<b>Sale Return Incentive Deduction Scheduled:</b> %s %s to be deducted from salesman %s's next month incentive (Period %s to %s)."
                    ) % (
                        order.currency_id.symbol or '',
                        ded_rec.deduction_amount,
                        salesman.name,
                        next_month_start,
                        next_month_end,
                    )
                )
