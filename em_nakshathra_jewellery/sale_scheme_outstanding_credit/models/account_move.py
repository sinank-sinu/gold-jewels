import re
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
    )

    is_scheme_redeemed = fields.Boolean(
        string="Is Scheme Redeemed",
        compute="_compute_is_scheme_redeemed",
    )

    scheme_amount = fields.Monetary(
        string="Customer Paid",
        compute="_compute_scheme_amount",
        currency_field="currency_id",
    )
    customer_paid = fields.Monetary(
        string="Customer Paid",
        related="scheme_amount",
    )

    @api.depends('customer_schemes', 'customer_schemes.total_paid')
    def _compute_scheme_amount(self):
        for rec in self:
            rec.scheme_amount = sum(rec.customer_schemes.mapped('total_paid'))

    @api.depends('customer_schemes', 'customer_schemes.is_redeemed', 'customer_schemes.state')
    def _compute_is_scheme_redeemed(self):
        for rec in self:
            has_redemption = False
            if rec.id and 'scheme.redemption' in self.env:
                sale_orders = rec.invoice_line_ids.mapped('sale_line_ids.order_id') | rec.line_ids.mapped('sale_line_ids.order_id')
                if not sale_orders and rec.invoice_origin:
                    sale_orders = self.env['sale.order'].sudo().search([('name', '=', rec.invoice_origin)])
                domain = ['|', ('move_id', '=', rec.id), ('sale_order_id', 'in', sale_orders.ids)] if sale_orders else [('move_id', '=', rec.id)]
                has_redemption = bool(self.env['scheme.redemption'].sudo().search_count(domain))
            rec.is_scheme_redeemed = has_redemption or (
                bool(rec.customer_schemes) and any(
                    getattr(s, 'is_redeemed', False) or s.state == 'redeemed' for s in rec.customer_schemes
                )
            )

    def _get_customer_default_schemes(self):
        self.ensure_one()
        if not self.partner_id:
            return self.env['jewellery.scheme.enrollment']

        partner_ids = list(set([p.id for p in (self.partner_id | self.commercial_partner_id) if p]))
        all_schemes = self.env['jewellery.scheme.enrollment'].sudo().with_context(active_test=False).search([
            ('partner_id', 'in', partner_ids),
            ('state', 'in', ('running', 'completed')),
            ('is_redeemed', '=', False),
        ])

        if not all_schemes:
            return self.env['jewellery.scheme.enrollment']

        # 1st Priority: If customer has unredeemed completed scheme(s), only fill completed scheme(s)
        completed_schemes = all_schemes.filtered(
            lambda s: s.state == 'completed' or (s.duration > 0 and s.total_paid >= (s.duration * s.installment_amount)) or (s.duration > 0 and getattr(s, 'paid_count', 0) >= s.duration)
        ).sorted(key=lambda s: (getattr(s, 'priority', 10), s.create_date or fields.Datetime.now()))

        if completed_schemes:
            return completed_schemes

        # 2nd Priority: If completed schemes are redeemed or none exist, only fill running scheme(s)
        running_schemes = all_schemes.filtered(
            lambda s: s.state == 'running'
        ).sorted(key=lambda s: (getattr(s, 'priority', 10), s.create_date or fields.Datetime.now()))

        if running_schemes:
            return running_schemes

        return all_schemes

    @api.depends('partner_id', 'line_ids.sale_line_ids.order_id')
    def _compute_customer_schemes(self):
        for rec in self:
            if rec.move_type != 'out_invoice':
                rec.customer_schemes = False
                continue

            sale_orders = rec.line_ids.mapped('sale_line_ids.order_id')
            if not sale_orders and rec.invoice_origin:
                sale_orders = self.env['sale.order'].sudo().search([('name', '=', rec.invoice_origin)])

            so_schemes = self.env['jewellery.scheme.enrollment']
            if sale_orders:
                if hasattr(sale_orders, 'customer_schemes') and sale_orders.customer_schemes:
                    so_schemes |= sale_orders.mapped('customer_schemes')
                elif hasattr(sale_orders, 'active_scheme_id') and sale_orders.active_scheme_id:
                    so_schemes |= sale_orders.mapped('active_scheme_id')

            if so_schemes:
                rec.customer_schemes = so_schemes
            elif not rec.customer_schemes and not rec.is_scheme_redeemed:
                rec.customer_schemes = rec._get_customer_default_schemes()

    @api.onchange('partner_id')
    def _onchange_partner_set_scheme(self):
        res = super()._onchange_partner_set_scheme() if hasattr(super(), '_onchange_partner_set_scheme') else None
        for rec in self:
            if rec.move_type == 'out_invoice' and rec.partner_id and not rec.is_scheme_redeemed:
                schemes = rec._get_customer_default_schemes()
                rec.customer_schemes = [(6, 0, schemes.ids)] if schemes else [(6, 0, [])]
            elif not rec.partner_id and not rec.is_scheme_redeemed:
                rec.customer_schemes = [(6, 0, [])]
        return res

    def _get_scheme_for_aml(self, line):
        self.ensure_one()
        line = line.sudo()
        # 1. Direct installment check
        installment = self.env['jewellery.scheme.installment'].sudo().search([('move_id', '=', line.move_id.id)], limit=1)
        if installment and installment.enrollment_id:
            return installment.enrollment_id

        # 2. Origin check for cross-company transfers
        if line.move_id.invoice_origin and line.move_id.invoice_origin.startswith('SchemeTransfer:'):
            parts = line.move_id.invoice_origin.split(':')
            if len(parts) >= 3 and parts[2].isdigit():
                t_inst = self.env['jewellery.scheme.installment'].sudo().browse(int(parts[2]))
                if t_inst.exists() and t_inst.enrollment_id:
                    return t_inst.enrollment_id

        # 3. Match against partner's schemes by ticket_number / name
        partner_ids = list(set([p.id for p in (self.partner_id | self.commercial_partner_id) if p]))
        all_schemes = self.env['jewellery.scheme.enrollment'].sudo().with_context(active_test=False).search([('partner_id', 'in', partner_ids)])
        ref_text = f"{line.ref or ''} {line.name or ''}"
        for s in all_schemes:
            if s.ticket_number and re.search(r'\b' + re.escape(s.ticket_number) + r'\b', ref_text, re.IGNORECASE):
                return s
            if s.name and s.name != 'New' and re.search(r'\b' + re.escape(s.name) + r'\b', ref_text, re.IGNORECASE):
                return s

        # 4. Check if text matches company of another branch scheme
        for s in all_schemes:
            comp = s.branch_id.company_id if s.branch_id else False
            if comp and (comp.name == line.ref or comp.name == line.name):
                return s

        return False


    def _get_outstanding_scheme_payment_lines(self):
        self.ensure_one()
        unredeemed_schemes = self.customer_schemes.filtered(
            lambda s: not getattr(s, 'is_redeemed', False) and s.state != 'redeemed'
        )
        if not unredeemed_schemes:
            return self.env['account.move.line']

        lines = super()._get_outstanding_scheme_payment_lines()
        filtered_lines = self.env['account.move.line']
        selected_names = set(filter(None, [s.name for s in unredeemed_schemes if s.name != 'New']))
        selected_tickets = set(filter(None, unredeemed_schemes.mapped('ticket_number')))

        for line in lines:
            scheme = self._get_scheme_for_aml(line)
            if scheme:
                if scheme in unredeemed_schemes and not getattr(scheme, 'is_redeemed', False) and scheme.state != 'redeemed':
                    filtered_lines |= line
                continue

            installment = self.env['jewellery.scheme.installment'].sudo().search([('move_id', '=', line.move_id.id)], limit=1)
            if installment and installment.enrollment_id:
                if installment.enrollment_id in unredeemed_schemes and not getattr(installment.enrollment_id, 'is_redeemed', False) and installment.enrollment_id.state != 'redeemed':
                    filtered_lines |= line
                continue

            ref = line.ref or ''
            name = line.name or ''
            ref_text = f"{ref} {name}"

            text_match = False
            for s_name in selected_names:
                if s_name and s_name != self.partner_id.name and re.search(r'\b' + re.escape(s_name) + r'\b', ref_text, re.IGNORECASE):
                    text_match = True
                    break
            if not text_match:
                for s_ticket in selected_tickets:
                    if s_ticket and s_ticket != self.partner_id.name and re.search(r'\b' + re.escape(s_ticket) + r'\b', ref_text, re.IGNORECASE):
                        text_match = True
                        break

            if text_match:
                filtered_lines |= line

        return filtered_lines

    @api.depends('customer_schemes')
    def _compute_has_outstanding_scheme_payment(self):
        super()._compute_has_outstanding_scheme_payment()

    @api.onchange('customer_schemes')
    def _onchange_customer_schemes(self):
        for rec in self:
            if hasattr(rec, '_compute_has_outstanding_scheme_payment'):
                rec._compute_has_outstanding_scheme_payment()

    def write(self, vals):
        res = super().write(vals)
        if 'customer_schemes' in vals:
            if hasattr(self, '_sync_cross_company_scheme_transfers'):
                self._sync_cross_company_scheme_transfers()
            if not self.env.context.get('skip_invoice_sync'):
                for move in self:
                    sale_orders = move.invoice_line_ids.mapped('sale_line_ids.order_id') | move.line_ids.mapped('sale_line_ids.order_id')
                    if not sale_orders and move.invoice_origin:
                        sale_orders = self.env['sale.order'].sudo().search([('name', '=', move.invoice_origin)])
                    if sale_orders:
                        sale_orders.with_context(skip_invoice_sync=True).sudo().write({
                            'customer_schemes': [(6, 0, move.customer_schemes.ids)],
                            'active_scheme_id': move.customer_schemes[:1].id if move.customer_schemes else False,
                            'apply_scheme': bool(move.customer_schemes),
                        })
        return res

    def action_redeem_outstanding_schemes(self):
        self.ensure_one()
        if not self.customer_schemes:
            raise UserError(_("No scheme selected in the 'Customer Schemes' field. Please select a scheme before redeeming."))
        res = super().action_redeem_outstanding_schemes()
        self.is_scheme_redeemed = True
        sale_orders = self.invoice_line_ids.mapped('sale_line_ids.order_id') | self.line_ids.mapped('sale_line_ids.order_id')
        if not sale_orders and self.invoice_origin:
            sale_orders = self.env['sale.order'].sudo().search([('name', '=', self.invoice_origin)])
        if sale_orders:
            sale_orders.with_context(skip_invoice_sync=True).sudo().write({
                'customer_schemes': [(6, 0, self.customer_schemes.ids)],
                'active_scheme_id': self.customer_schemes[:1].id if self.customer_schemes else False,
                'apply_scheme': bool(self.customer_schemes),
            })
        return res

    def js_assign_outstanding_line(self, line_id):
        self.ensure_one()
        line = self.env['account.move.line'].browse(line_id)
        scheme = self._get_scheme_for_aml(line) if hasattr(self, '_get_scheme_for_aml') else False
        if not scheme:
            installment = self.env['jewellery.scheme.installment'].sudo().search([('move_id', '=', line.move_id.id)], limit=1)
            if installment:
                scheme = installment.enrollment_id

        if not scheme:
            ref = line.ref or ''
            name = line.name or ''
            move_name = line.sudo().move_id.name or ''
            text = f"{ref} {name} {move_name}"
            if any(t in text for t in ['Scheme Payment', 'Scheme Transfer', 'Scheme Installment', 'Scheme Redemption']):
                scheme = True
            else:
                partner_ids = list(set([p.id for p in (self.partner_id | self.commercial_partner_id) if p]))
                all_schemes = self.env['jewellery.scheme.enrollment'].sudo().with_context(active_test=False).search([('partner_id', 'in', partner_ids)])
                for s in all_schemes:
                    if (s.name and s.name != 'New' and s.name in text) or (s.ticket_number and s.ticket_number in text):
                        scheme = s
                        break

        if scheme:
            raise UserError(_("Please click the 'Redeem Scheme' button to redeem scheme payments."))

        return super().js_assign_outstanding_line(line_id)
