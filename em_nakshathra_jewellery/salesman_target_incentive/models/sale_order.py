from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        res = super().action_confirm()
        self._update_salesman_targets()
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
                    ('state', 'in', ['draft', 'confirmed']),
                ])
                if targets:
                    targets._compute_achievements()
                    targets._incentive_add()
