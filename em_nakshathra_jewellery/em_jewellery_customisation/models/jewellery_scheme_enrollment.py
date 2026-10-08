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

    def get_receipt_company(self):
        self.ensure_one()
        rec = self.sudo()
        if hasattr(rec, 'company_id') and rec.company_id:
            return rec.company_id
        if hasattr(rec, 'branch_id') and rec.branch_id and getattr(rec.branch_id, 'company_id', None):
            return rec.branch_id.company_id
        if hasattr(rec, 'user_id') and rec.user_id and getattr(rec.user_id, 'company_id', None):
            return rec.user_id.company_id
        return self.env.company

    def get_receipt_paid_lines(self):
        self.ensure_one()
        return self.sudo().scheme_line_ids.filtered(lambda l: l.state == 'paid').sorted('date')

    def get_receipt_display_lines(self):
        self.ensure_one()
        paid = self.get_receipt_paid_lines()
        return paid if paid else self.sudo().scheme_line_ids.sorted('date')

    def get_receipt_as_on_date(self):
        self.ensure_one()
        paid = self.get_receipt_paid_lines()
        if paid and paid[-1].date:
            return paid[-1].date.strftime('%d/%m/%Y')
        return fields.Date.today().strftime('%d/%m/%Y')

    def get_receipt_formatted_address(self):
        self.ensure_one()
        rec = self.sudo()
        raw = rec.address or (rec.partner_id.contact_address if rec.partner_id else '') or ''
        parts = [p.strip() for p in raw.replace('\n', ',').split(',') if p.strip()]
        return ', '.join(parts)

    def get_receipt_total_paid(self):
        self.ensure_one()
        return sum(self.get_receipt_display_lines().mapped('amount'))

    def get_line_voucher_name(self, line):
        self.ensure_one()
        l = line.sudo()
        try:
            if l.move_id:
                m_name = l.move_id.sudo().name
                if m_name:
                    return m_name
        except Exception:
            pass
        try:
            if l.suspense_move_id:
                s_name = l.suspense_move_id.sudo().name
                if s_name:
                    return s_name
        except Exception:
            pass
        return l.transaction_id or l.remark or ''

    def action_print_scheme_receipt(self):
        """Action for printing the customer scheme receipt PDF"""
        self.ensure_one()
        return self.env.ref(
            'em_jewellery_customisation.action_report_scheme_receipt'
        ).report_action(self.id)

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
        
    @api.depends('scheme_line_ids.amount', 'scheme_line_ids.state', 'duration', 'installment_amount', 'total_scheme_amount')
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