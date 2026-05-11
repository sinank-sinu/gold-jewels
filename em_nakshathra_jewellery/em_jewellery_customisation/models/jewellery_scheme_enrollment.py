from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'jewellery.scheme.enrollment'


    priority = fields.Integer(string="Priority", default=10)
    state = fields.Selection(
        selection_add=[('redeemed', 'Redeemed')]
    )
    is_redeemed = fields.Boolean(default=False)

    def action_print_scheme_report(self):
        self.ensure_one()

        return self.env.ref(
            'em_jewellery_customisation.scheme_margin_xlsx_action'
        ).report_action(self)
    
    @api.depends('scheme_line_ids.amount', 'scheme_line_ids.state')
    def _compute_totals(self):
        for rec in self:
            paid_lines = rec.scheme_line_ids.filtered(lambda l: l.state == 'paid')
            total = sum(paid_lines.mapped('amount'))
            rec.total_paid = total
            rec.paid_count = len(paid_lines)
            expected_total = rec.duration * rec.installment_amount
            rec.balance_amount = expected_total - total

            if total >= expected_total:
                rec.state = 'completed'
            else:
                rec.state = 'running'