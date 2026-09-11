from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    customer_schemes = fields.Many2many(
        'jewellery.scheme.enrollment',
        'account_move_customer_schemes_rel',
        'move_id',
        'scheme_id',
        string="Customer Schemes",
        compute='_compute_customer_schemes',
        store=True,
        readonly=False,
        precompute=True
    )

    is_scheme_redeemed = fields.Boolean(
        string="Is Scheme Redeemed",
        compute="_compute_is_scheme_redeemed",
        store=True
    )

    @api.depends('customer_schemes', 'customer_schemes.is_redeemed', 'customer_schemes.state')
    def _compute_is_scheme_redeemed(self):
        for rec in self:
            rec.is_scheme_redeemed = bool(rec.customer_schemes) and any(
                s.is_redeemed or s.state == 'redeemed' for s in rec.customer_schemes
            )

    @api.depends('partner_id', 'line_ids.sale_line_ids.order_id')
    def _compute_customer_schemes(self):
        for rec in self:
            so_schemes = self.env['jewellery.scheme.enrollment']
            sale_orders = rec.line_ids.mapped('sale_line_ids.order_id')
            if sale_orders:
                if hasattr(sale_orders, 'customer_schemes'):
                    so_schemes |= sale_orders.mapped('customer_schemes')
                if hasattr(sale_orders, 'active_scheme_id'):
                    so_schemes |= sale_orders.mapped('active_scheme_id').filtered(lambda s: not s.is_redeemed)

            if so_schemes:
                rec.customer_schemes = so_schemes
            elif rec.partner_id:
                partner_ids = list(set([p.id for p in (rec.partner_id | rec.commercial_partner_id) if p]))
                schemes = self.env['jewellery.scheme.enrollment'].with_context(active_test=False).search([
                    ('partner_id', 'in', partner_ids),
                    ('state', 'in', ('running', 'completed')),
                    ('is_redeemed', '=', False),
                ])
                completed_schemes = schemes.filtered(lambda s: s.state == 'completed')
                selected_schemes = completed_schemes if completed_schemes else schemes
                rec.customer_schemes = selected_schemes
            else:
                rec.customer_schemes = False

    @api.onchange('partner_id')
    def _onchange_partner_set_scheme(self):
        res = super()._onchange_partner_set_scheme() if hasattr(super(), '_onchange_partner_set_scheme') else None
        for rec in self:
            if rec.partner_id:
                partner_ids = list(set([p.id for p in (rec.partner_id | rec.commercial_partner_id) if p]))
                schemes = self.env['jewellery.scheme.enrollment'].with_context(active_test=False).search([
                    ('partner_id', 'in', partner_ids),
                    ('state', 'in', ('running', 'completed')),
                    ('is_redeemed', '=', False),
                ])
                completed_schemes = schemes.filtered(lambda s: s.state == 'completed')
                selected_schemes = completed_schemes if completed_schemes else schemes
                rec.customer_schemes = [(6, 0, selected_schemes.ids)] if selected_schemes else [(6, 0, [])]
            else:
                rec.customer_schemes = [(6, 0, [])]
        return res

    def _get_outstanding_scheme_payment_lines(self):
        lines = super()._get_outstanding_scheme_payment_lines()
        self.ensure_one()
        if not self.customer_schemes:
            return lines

        filtered_lines = self.env['account.move.line']
        selected_schemes = self.customer_schemes
        selected_scheme_ids = set(selected_schemes.ids)
        selected_names = set(filter(None, selected_schemes.mapped('name')))
        selected_tickets = set(filter(None, selected_schemes.mapped('ticket_number')))
        selected_scheme_companies = set(selected_schemes.mapped('branch_id.company_id').ids)

        other_companies = self.env['res.company'].sudo().search([('id', '!=', self.company_id.id)])

        for line in lines:
            # 1. Direct installment check
            installment = self.env['jewellery.scheme.installment'].search([('move_id', '=', line.move_id.id)], limit=1)
            if installment:
                if installment.enrollment_id.id in selected_scheme_ids:
                    filtered_lines |= line
                continue

            # 2. Text / Ticket / Name check
            ref = line.ref or ''
            name = line.name or ''
            move_name = line.move_id.name or ''

            text_match = False
            for s_name in selected_names:
                if s_name and (s_name in ref or s_name in name or s_name in move_name):
                    text_match = True
                    break
            if not text_match:
                for s_ticket in selected_tickets:
                    if s_ticket and (s_ticket in ref or s_ticket in name or s_ticket in move_name):
                        text_match = True
                        break

            if text_match:
                filtered_lines |= line
                continue

            # 3. Cross-company check: match company of selected schemes
            for comp in other_companies:
                if comp.id in selected_scheme_companies:
                    if comp.name == ref or comp.name == name:
                        filtered_lines |= line
                        break

        return filtered_lines

    def action_redeem_outstanding_schemes(self):
        self.ensure_one()
        if not self.customer_schemes:
            return super().action_redeem_outstanding_schemes()

        scheme_lines = self._get_outstanding_scheme_payment_lines()
        if not scheme_lines:
            raise UserError(_("No outstanding scheme payment credits found for the selected customer schemes."))

        for line in scheme_lines:
            # 1. Reconcile this line against the invoice
            invoice_receivable_lines = self.line_ids.filtered(
                lambda l: l.account_id == line.account_id and not l.reconciled
            )
            if invoice_receivable_lines:
                (line + invoice_receivable_lines).reconcile()

            # 2. Find corresponding scheme enrollment(s) strictly within self.customer_schemes
            enrollments = self.env['jewellery.scheme.enrollment']
            installment = self.env['jewellery.scheme.installment'].search([('move_id', '=', line.move_id.id)])
            if installment:
                enrollments |= installment.mapped('enrollment_id').filtered(lambda s: s in self.customer_schemes)

            if not enrollments:
                ref = line.ref or ''
                name = line.name or ''
                move_name = line.move_id.name or ''
                for scheme in self.customer_schemes:
                    if (scheme.name and (scheme.name in ref or scheme.name in name or scheme.name in move_name)) or \
                       (scheme.ticket_number and (scheme.ticket_number in ref or scheme.ticket_number in name or scheme.ticket_number in move_name)):
                        enrollments |= scheme

                if not enrollments:
                    # Cross company matching
                    for scheme in self.customer_schemes:
                        if scheme.branch_id and scheme.branch_id.company_id and scheme.branch_id.company_id.name in (ref, name):
                            enrollments |= scheme

            # 3. Mark selected scheme(s) as redeemed and create scheme.redemption record
            for scheme in enrollments:
                scheme.write({
                    'state': 'redeemed',
                    'is_redeemed': True,
                })

                sale_orders = self.invoice_line_ids.mapped('sale_line_ids.order_id')
                sale_order = sale_orders[0] if sale_orders else self.env['sale.order']

                if sale_order:
                    existing_redemption = self.env['scheme.redemption'].search([
                        ('scheme_id', '=', scheme.id),
                        ('sale_order_id', '=', sale_order.id)
                    ], limit=1)

                    if not existing_redemption:
                        self.env['scheme.redemption'].sudo().create({
                            'scheme_id': scheme.id,
                            'sale_order_id': sale_order.id,
                            'amount': scheme.total_paid,
                            'date': sale_order.date_order.date() if sale_order and sale_order.date_order else fields.Date.today(),
                        })
                        if hasattr(sale_order, 'active_scheme_id') and not sale_order.active_scheme_id:
                            sale_order.sudo().write({'active_scheme_id': scheme.id})

        return True
