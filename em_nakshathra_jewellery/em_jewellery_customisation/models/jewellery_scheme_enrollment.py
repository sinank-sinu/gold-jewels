from odoo import models, fields, api

class JewellerySchemeEnrollment(models.Model):
    _inherit = 'jewellery.scheme.enrollment'

    priority = fields.Integer(string="Priority", default=10, tracking=True)
    state = fields.Selection(
        selection_add=[('redeemed', 'Redeemed')]
    )
    is_redeemed = fields.Boolean(default=False, tracking=True)
    total_scheme_amount = fields.Float(
        string="Total Scheme Amount", 
        compute="_compute_total_scheme_amount", 
        tracking=True
    )

    @api.depends('duration', 'installment_amount')
    def _compute_total_scheme_amount(self):
        for rec in self:
            rec.total_scheme_amount = rec.duration * rec.installment_amount

    def action_print_single_scheme_report(self):
        """Action for printing the individual detailed report directly"""
        self.ensure_one()
        return self.env.ref(
            'em_jewellery_customisation.scheme_margin_xlsx_action'
        ).report_action(self)

    def action_print_combined_wizard(self):
        """Action tied to the form/list view button to launch the wizard popup"""
        return {
            'name': 'Print Combined Scheme Report',
            'type': 'ir.actions.act_window',
            'res_model': 'scheme.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_ids': self.ids},  # Sends selected IDs down to the wizard
        }
        
    @api.depends('scheme_line_ids.amount', 'scheme_line_ids.state')
    def _compute_totals(self):
        for rec in self:
            paid_lines = rec.scheme_line_ids.filtered(lambda l: l.state == 'paid')
            total = sum(paid_lines.mapped('amount'))
            
            rec.total_paid = total
            rec.paid_count = len(paid_lines)
            
            # Use fallback defaults to protect against accidental division/null errors
            duration = rec.duration or 0
            inst_amount = rec.installment_amount or 0.0
            
            expected_total = rec.total_scheme_amount if rec.total_scheme_amount > 0 else (duration * inst_amount)
            rec.balance_amount = expected_total - total

            # NOTE: If state is not a computed field, setting it here 
            # might only update the UI temporarily until the next refresh.
            if rec.state != 'redeemed':
                if total >= expected_total and expected_total > 0:
                    rec.state = 'completed'
                else:
                    rec.state = 'running'


class JewellerySchemeInstallment(models.Model):
    _inherit = 'jewellery.scheme.installment'

    def get_voucher_display_name(self):
        self.ensure_one()
        line = self.sudo()
        try:
            if line.move_id:
                m_name = line.move_id.sudo().name
                if m_name:
                    return m_name
        except Exception:
            pass
        try:
            if line.suspense_move_id:
                s_name = line.suspense_move_id.sudo().name
                if s_name:
                    return s_name
        except Exception:
            pass
        return line.transaction_id or line.remark or ''


# from odoo import models, fields, api


# class SaleOrderLine(models.Model):
#     _inherit = 'jewellery.scheme.enrollment'


#     priority = fields.Integer(string="Priority", default=10)
#     state = fields.Selection(
#         selection_add=[('redeemed', 'Redeemed')]
#     )
#     is_redeemed = fields.Boolean(default=False)

#     def action_print_scheme_report(self):
#         self.ensure_one()

#         return self.env.ref(
#             'em_jewellery_customisation.scheme_margin_xlsx_action'
#         ).report_action(self)

#     #To get combined scheme report
#     def action_print_scheme_report(self):
#         # Instead of going straight to print, return the wizard action
#         return {
#             'name': 'Print Scheme Report',
#             'type': 'ir.actions.act_window',
#             'res_model': 'scheme.report.wizard',
#             'view_mode': 'form',
#             'target': 'new',
#             'context': {'active_ids': self.ids}, # Send current ID to context
#         }

#     @api.depends('scheme_line_ids.amount', 'scheme_line_ids.state')
#     def _compute_totals(self):
#         for rec in self:
#             paid_lines = rec.scheme_line_ids.filtered(lambda l: l.state == 'paid')
#             total = sum(paid_lines.mapped('amount'))
#             rec.total_paid = total
#             rec.paid_count = len(paid_lines)
#             expected_total = rec.duration * rec.installment_amount
#             rec.balance_amount = expected_total - total

#             if total >= expected_total:
#                 rec.state = 'completed'
#             else:
#                 rec.state = 'running'