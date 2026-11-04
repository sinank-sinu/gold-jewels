import re
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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

    phone = fields.Char(
        string="Phone Number",
        compute="_compute_phone",
        store=True,
        readonly=False,
    )

    other_person_phone = fields.Char(string="Other Person Phone", copy=False)

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

    @api.depends('partner_id', 'partner_id.phone', 'partner_id.mobile', 'invoice_origin', 'line_ids.sale_line_ids.order_id')
    def _compute_phone(self):
        for rec in self:
            sale_orders = rec.line_ids.mapped('sale_line_ids.order_id')
            if not sale_orders and rec.invoice_origin:
                sale_orders = self.env['sale.order'].sudo().search([('name', '=', rec.invoice_origin)])
            if sale_orders and hasattr(sale_orders[0], 'phone') and sale_orders[0].phone:
                rec.phone = sale_orders[0].phone
            elif rec.partner_id:
                rec.phone = rec.partner_id.phone or rec.partner_id.mobile or False
            else:
                rec.phone = False

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
                if hasattr(sale_orders[0], 'other_person_phone') and sale_orders[0].other_person_phone and not rec.other_person_phone:
                    rec.other_person_phone = sale_orders[0].other_person_phone

            if so_schemes:
                rec.customer_schemes = so_schemes
            elif not rec.customer_schemes and not rec.is_scheme_redeemed:
                rec.customer_schemes = rec._get_customer_default_schemes()

    @api.onchange('partner_id')
    def _onchange_partner_set_scheme(self):
        res = super()._onchange_partner_set_scheme() if hasattr(super(), '_onchange_partner_set_scheme') else None
        for rec in self:
            rec.other_person_phone = False
            rec.phone = rec.partner_id.phone or rec.partner_id.mobile or False
            if rec.move_type == 'out_invoice' and rec.partner_id and not rec.is_scheme_redeemed:
                schemes = rec._get_customer_default_schemes()
                rec.customer_schemes = [(6, 0, schemes.ids)] if schemes else [(6, 0, [])]
            elif not rec.partner_id and not rec.is_scheme_redeemed:
                rec.customer_schemes = [(6, 0, [])]
        return res

    @api.onchange('other_person_phone')
    def _onchange_other_person_phone(self):
        for rec in self:
            if not rec.other_person_phone:
                continue

            phone_input = rec.other_person_phone.strip()
            digits = ''.join(filter(str.isdigit, phone_input))
            search_digits = digits[-10:] if len(digits) >= 10 else digits

            if not search_digits:
                continue

            # 1. Search in jewellery.scheme.enrollment by normalized phone
            self.env.cr.execute("""
                SELECT id FROM jewellery_scheme_enrollment 
                WHERE regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g') LIKE %s
                  AND state IN ('running', 'completed')
                  AND NOT is_redeemed
                ORDER BY (state = 'completed') DESC, create_date ASC
            """, (f"%{search_digits}%",))
            matched_ids = [r[0] for r in self.env.cr.fetchall()]

            # 2. Search in res.partner for contacts matching this phone / mobile
            self.env.cr.execute("""
                SELECT id FROM res_partner 
                WHERE (regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g') LIKE %s
                    OR regexp_replace(COALESCE(mobile, ''), '[^0-9]', '', 'g') LIKE %s)
            """, (f"%{search_digits}%", f"%{search_digits}%"))
            partner_res = [r[0] for r in self.env.cr.fetchall()]

            if partner_res:
                p_schemes = self.env['jewellery.scheme.enrollment'].sudo().search([
                    ('partner_id', 'in', partner_res),
                    ('state', 'in', ('running', 'completed')),
                    ('is_redeemed', '=', False),
                ])
                matched_ids = list(dict.fromkeys(matched_ids + p_schemes.ids))

            if matched_ids:
                other_schemes = self.env['jewellery.scheme.enrollment'].browse(matched_ids)
                rec.customer_schemes = rec.customer_schemes | other_schemes
                if rec.state == 'posted' and hasattr(rec, '_sync_cross_company_scheme_transfers'):
                    rec._sync_cross_company_scheme_transfers()
                if hasattr(rec, '_compute_payments_widget_to_reconcile_info'):
                    rec._compute_payments_widget_to_reconcile_info()
            else:
                return {
                    'warning': {
                        'title': _("No Active Scheme Found"),
                        'message': _("No unredeemed running or completed scheme found for phone number: %s") % rec.other_person_phone
                    }
                }

    def _get_scheme_for_aml(self, line):
        self.ensure_one()
        line = line.sudo()
        if line.move_id.move_type in ('out_refund', 'in_refund'):
            return False

        # 1. Direct installment check
        installment = self.env['jewellery.scheme.installment'].sudo().search([('move_id', '=', line.move_id.id)], limit=1)
        if installment and installment.enrollment_id:
            return installment.enrollment_id

        # 2. Origin check for transfers (cross-company or same-company other person)
        if line.move_id.invoice_origin and (
            line.move_id.invoice_origin.startswith('SchemeTransfer:') or
            line.move_id.invoice_origin.startswith('SchemeTransferSameComp:')
        ):
            parts = line.move_id.invoice_origin.split(':')
            if len(parts) >= 3 and parts[2].isdigit():
                t_inst = self.env['jewellery.scheme.installment'].sudo().browse(int(parts[2]))
                if t_inst.exists() and t_inst.enrollment_id:
                    return t_inst.enrollment_id

        # 3. Match against partner's schemes by ticket_number / name
        partner_ids = list(set([p.id for p in (self.partner_id | self.commercial_partner_id) if p]))
        if self.customer_schemes:
            for s in self.customer_schemes:
                if s.partner_id:
                    partner_ids.extend([s.partner_id.id, getattr(s.partner_id, 'commercial_partner_id', s.partner_id).id])
            partner_ids = list(set(partner_ids))
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
        if not self.customer_schemes:
            return self.env['account.move.line']

        target_schemes = self.customer_schemes
        lines = super()._get_outstanding_scheme_payment_lines()
        filtered_lines = self.env['account.move.line']
        selected_names = set(filter(None, [s.name for s in target_schemes if s.name != 'New']))
        selected_tickets = set(filter(None, target_schemes.mapped('ticket_number')))
        target_partner_names = set(filter(None, [self.partner_id.name] + [s.partner_id.name for s in target_schemes if s.partner_id]))

        for line in lines:
            if line.move_id.move_type in ('out_refund', 'in_refund'):
                continue

            scheme = self._get_scheme_for_aml(line)
            if scheme:
                if scheme in target_schemes:
                    filtered_lines |= line
                continue

            installment = self.env['jewellery.scheme.installment'].sudo().search([('move_id', '=', line.move_id.id)], limit=1)
            if installment and installment.enrollment_id:
                if installment.enrollment_id in target_schemes:
                    filtered_lines |= line
                continue

            ref = line.ref or ''
            name = line.name or ''
            ref_text = f"{ref} {name}"

            text_match = False
            for s_name in selected_names:
                if s_name and s_name not in target_partner_names and re.search(r'\b' + re.escape(s_name) + r'\b', ref_text, re.IGNORECASE):
                    text_match = True
                    break
            if not text_match:
                for s_ticket in selected_tickets:
                    if s_ticket and s_ticket not in target_partner_names and re.search(r'\b' + re.escape(s_ticket) + r'\b', ref_text, re.IGNORECASE):
                        text_match = True
                        break

            if text_match:
                filtered_lines |= line

        return filtered_lines

    @api.depends('customer_schemes', 'is_scheme_redeemed', 'payment_state', 'state', 'invoice_outstanding_credits_debits_widget')
    def _compute_has_outstanding_scheme_payment(self):
        for move in self:
            if getattr(move, 'is_scheme_redeemed', False) or move.payment_state in ('paid', 'in_payment'):
                move.has_outstanding_scheme_payment = False
            else:
                unredeemed = move.customer_schemes.filtered(
                    lambda s: not getattr(s, 'is_redeemed', False) and s.state != 'redeemed'
                )
                if not unredeemed:
                    move.has_outstanding_scheme_payment = False
                else:
                    super(AccountMove, move)._compute_has_outstanding_scheme_payment()

    @api.depends('customer_schemes', 'is_scheme_redeemed')
    def _compute_scheme_balance_to_pay_customer(self):
        super()._compute_scheme_balance_to_pay_customer()

    @api.depends(
        'move_type',
        'line_ids.amount_residual',
        'line_ids.amount_residual_currency',
        'state',
        'partner_id',
        'customer_schemes',
        'is_scheme_redeemed',
    )
    def _compute_payments_widget_to_reconcile_info(self):
        super()._compute_payments_widget_to_reconcile_info()
        widget_field = self._fields['invoice_outstanding_credits_debits_widget']
        for move in self:
            existing_widget = move.env.cache.get(move.with_context(bin_size=False), widget_field, None)

            if move.state != 'posted' or move.payment_state in ('paid', 'in_payment') or not move.is_invoice(include_receipts=True):
                continue
            if getattr(move, 'is_scheme_redeemed', False):
                if existing_widget and existing_widget.get('content'):
                    move.env.cache.set(move, widget_field, dict(existing_widget))
                    move.env.cache.set(move.with_context(bin_size=True), widget_field, dict(existing_widget))
                    move.env.cache.set(move.with_context(bin_size=False), widget_field, dict(existing_widget))
                continue
            if not getattr(move, 'customer_schemes', None):
                if existing_widget and existing_widget.get('content'):
                    move.env.cache.set(move, widget_field, dict(existing_widget))
                    move.env.cache.set(move.with_context(bin_size=True), widget_field, dict(existing_widget))
                    move.env.cache.set(move.with_context(bin_size=False), widget_field, dict(existing_widget))
                continue

            scheme_lines = move._get_outstanding_scheme_payment_lines()
            if not scheme_lines:
                if existing_widget and existing_widget.get('content'):
                    move.env.cache.set(move, widget_field, dict(existing_widget))
                    move.env.cache.set(move.with_context(bin_size=True), widget_field, dict(existing_widget))
                    move.env.cache.set(move.with_context(bin_size=False), widget_field, dict(existing_widget))
                continue

            widget = dict(existing_widget) if isinstance(existing_widget, dict) else {
                'outstanding': True,
                'content': [],
                'move_id': move.id,
                'title': _('Outstanding credits') if move.is_inbound() else _('Outstanding debits')
            }
            content = list(widget.get('content', []))
            existing_ids = {item['id'] for item in content}

            for line in scheme_lines:
                if line.id not in existing_ids and not line.reconciled and (
                    line.amount_residual < 0.0 if move.is_inbound() else line.amount_residual > 0.0
                ):
                    if line.currency_id == move.currency_id:
                        amount = abs(line.amount_residual_currency)
                    else:
                        amount = line.company_currency_id._convert(
                            abs(line.amount_residual),
                            move.currency_id,
                            move.company_id,
                            line.date,
                        )
                    if move.currency_id.is_zero(amount):
                        continue
                    content.append({
                        'journal_name': line.ref or line.move_id.name,
                        'amount': amount,
                        'currency_id': move.currency_id.id,
                        'id': line.id,
                        'move_id': line.move_id.id,
                        'date': fields.Date.to_string(line.date),
                        'account_payment_id': line.payment_id.id,
                    })

            if content:
                widget['content'] = content
                move.invoice_outstanding_credits_debits_widget = dict(widget)
                move.invoice_has_outstanding = True
                move.env.cache.set(move, widget_field, dict(widget))
                move.env.cache.set(move.with_context(bin_size=True), widget_field, dict(widget))
                move.env.cache.set(move.with_context(bin_size=False), widget_field, dict(widget))
            elif existing_widget and existing_widget.get('content'):
                move.invoice_has_outstanding = True
                move.env.cache.set(move, widget_field, dict(existing_widget))
                move.env.cache.set(move.with_context(bin_size=True), widget_field, dict(existing_widget))
                move.env.cache.set(move.with_context(bin_size=False), widget_field, dict(existing_widget))

    def action_post(self):
        res = super().action_post()
        for move in self:
            if hasattr(move, '_compute_payments_widget_to_reconcile_info'):
                move._compute_payments_widget_to_reconcile_info()
            if hasattr(move, '_compute_has_outstanding_scheme_payment'):
                move._compute_has_outstanding_scheme_payment()
        return res

    @api.onchange('customer_schemes')
    def _onchange_customer_schemes(self):
        for rec in self:
            if hasattr(rec, '_compute_has_outstanding_scheme_payment'):
                rec._compute_has_outstanding_scheme_payment()
            if hasattr(rec, '_compute_scheme_balance_to_pay_customer'):
                rec._compute_scheme_balance_to_pay_customer()
            if hasattr(rec, '_compute_payments_widget_to_reconcile_info'):
                rec._compute_payments_widget_to_reconcile_info()

    def write(self, vals):
        res = super().write(vals)
        if 'customer_schemes' in vals:
            if hasattr(self, '_sync_cross_company_scheme_transfers'):
                self._sync_cross_company_scheme_transfers()
            if hasattr(self, '_compute_scheme_balance_to_pay_customer'):
                self._compute_scheme_balance_to_pay_customer()
            if hasattr(self, '_compute_payments_widget_to_reconcile_info'):
                self._compute_payments_widget_to_reconcile_info()
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
        if getattr(self, 'is_scheme_redeemed', False):
            raise UserError(_("The selected scheme(s) have already been redeemed on this invoice."))
        if hasattr(self, '_sync_cross_company_scheme_transfers'):
            self._sync_cross_company_scheme_transfers()
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
        if hasattr(self, '_compute_scheme_balance_to_pay_customer'):
            self._compute_scheme_balance_to_pay_customer()
        return res

    def js_assign_outstanding_line(self, line_id):
        self.ensure_one()
        line = self.env['account.move.line'].browse(line_id)
        if line.move_id.move_type in ('out_refund', 'in_refund'):
            return super().js_assign_outstanding_line(line_id)

        scheme = False
        if hasattr(self, '_get_outstanding_scheme_payment_lines'):
            if line in self._get_outstanding_scheme_payment_lines():
                scheme = True

        if not scheme:
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
            elif line.move_id.invoice_origin and (
                line.move_id.invoice_origin.startswith('SchemeTransfer:') or
                line.move_id.invoice_origin.startswith('SchemeTransferSameComp:')
            ):
                scheme = True

        if scheme:
            raise UserError(_("Scheme amount cannot be redeemed by clicking the 'Add' button. Please click the 'Redeem Scheme' button to redeem."))

        return super().js_assign_outstanding_line(line_id)

    def _unredeem_customer_schemes(self):
        for move in self:
            if move.move_type == 'out_invoice':
                for scheme in move.customer_schemes:
                    scheme.sudo().write({'is_redeemed': False})
                    if scheme.state == 'redeemed':
                        expected_total = getattr(scheme, 'total_scheme_amount', 0.0) or (scheme.duration * scheme.installment_amount)
                        new_state = 'completed' if (scheme.duration > 0 and scheme.total_paid >= expected_total and expected_total > 0) else 'running'
                        scheme.sudo().write({'state': new_state})

                sale_orders = move.invoice_line_ids.mapped('sale_line_ids.order_id') | move.line_ids.mapped('sale_line_ids.order_id')
                if not sale_orders and move.invoice_origin:
                    sale_orders = self.env['sale.order'].sudo().search([('name', '=', move.invoice_origin)])

                if 'scheme.redemption' in self.env:
                    domain = [('move_id', '=', move.id)]
                    if sale_orders and move.customer_schemes:
                        domain = ['|', ('move_id', '=', move.id), '&', ('sale_order_id', 'in', sale_orders.ids), ('scheme_id', 'in', move.customer_schemes.ids)]
                    redemptions = self.env['scheme.redemption'].sudo().search(domain)
                    if redemptions:
                        redemptions.unlink()

                transfer_moves = self.env['account.move'].sudo().search([
                    '|', '|',
                    ('invoice_origin', '=like', f"SchemeTransfer:{move.id}:%"),
                    ('invoice_origin', '=like', f"SchemeTransferOut:{move.id}:%"),
                    ('invoice_origin', '=like', f"SchemeTransferSameComp:{move.id}:%"),
                    ('state', '!=', 'cancel'),
                ])
                for t in transfer_moves:
                    try:
                        t.line_ids.remove_move_reconcile()
                        t.button_draft()
                        t.button_cancel()
                    except Exception as e:
                        _logger.warning("Failed to cancel transfer move %s: %s", t.name, e)

                move.is_scheme_redeemed = False

                if sale_orders:
                    for so in sale_orders:
                        so_redemptions = self.env['scheme.redemption'].sudo().search([('sale_order_id', '=', so.id)])
                        if not so_redemptions:
                            so.with_context(skip_invoice_sync=True).sudo().write({
                                'is_scheme_redeemed': False,
                            })

                if hasattr(move, '_compute_has_outstanding_scheme_payment'):
                    move._compute_has_outstanding_scheme_payment()
                if hasattr(move, '_compute_payments_widget_to_reconcile_info'):
                    move._compute_payments_widget_to_reconcile_info()

    def button_draft(self):
        res = super().button_draft()
        self._unredeem_customer_schemes()
        return res

    def button_cancel(self):
        res = super().button_cancel()
        self._unredeem_customer_schemes()
        return res
