# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    phone = fields.Char(string="Phone Number", copy=False, tracking=True)
    sale_id = fields.Many2one('sale.order', string="Sales Order", readonly=True)
    invoice_id = fields.Many2one(
        'account.move',
        string="Invoice",
        domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]",
        readonly=False,
    )

    @staticmethod
    def _normalize_phone_digits(value):
        digits = ''.join(filter(str.isdigit, (value or '').strip()))
        return digits[-10:] if len(digits) >= 10 else digits

    def _sync_phone_to_partner(self):
        for payment in self:
            if payment.is_internal_transfer or not payment.partner_id or not payment.phone:
                continue
            partner = payment.partner_id
            vals_to_write = {}
            if not partner.phone:
                vals_to_write['phone'] = payment.phone
            if not partner.mobile:
                vals_to_write['mobile'] = payment.phone
            if vals_to_write:
                try:
                    partner.sudo().write(vals_to_write)
                except Exception:
                    pass

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('partner_id') and not vals.get('phone') and not vals.get('is_internal_transfer'):
                partner = self.env['res.partner'].browse(vals['partner_id'])
                vals['phone'] = partner.phone or partner.mobile or False
        payments = super().create(vals_list)
        payments._sync_phone_to_partner()
        return payments

    def write(self, vals):
        res = super().write(vals)
        if 'phone' in vals or 'partner_id' in vals:
            self._sync_phone_to_partner()
        return res

    @api.onchange('phone')
    def _onchange_phone_set_partner(self):
        for rec in self:
            if rec.is_internal_transfer or rec.state != 'draft' or not rec.phone:
                continue

            search_digits = self._normalize_phone_digits(rec.phone)
            if not search_digits:
                continue

            rank_column = 'supplier_rank' if rec.partner_type == 'supplier' else 'customer_rank'
            self.env.cr.execute(f"""
                SELECT id FROM res_partner
                WHERE COALESCE(active, true) = true
                  AND (regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g') LIKE %s
                    OR regexp_replace(COALESCE(mobile, ''), '[^0-9]', '', 'g') LIKE %s)
                ORDER BY {rank_column} DESC, id DESC
                LIMIT 1
            """, (f"%{search_digits}%", f"%{search_digits}%"))
            partner_res = self.env.cr.fetchone()

            if partner_res:
                rec.partner_id = partner_res[0]
            elif not rec.partner_id:
                partner_label = _("Vendor") if rec.partner_type == 'supplier' else _("Customer")
                return {
                    'warning': {
                        'title': _("New %s") % partner_label,
                        'message': _(
                            "No existing %s found with phone number: %s. "
                            "Please enter or select the %s in the %s field."
                        ) % (partner_label.lower(), rec.phone, partner_label.lower(), partner_label),
                    }
                }

    @api.onchange('partner_id')
    def _onchange_partner_set_phone(self):
        for rec in self:
            if rec.is_internal_transfer or not rec.partner_id:
                rec.phone = False
                continue

            current_phone = self._normalize_phone_digits(rec.phone)
            valid_phones = [
                self._normalize_phone_digits(p)
                for p in (rec.partner_id.phone, rec.partner_id.mobile)
                if p
            ]
            valid_phones = [p for p in valid_phones if p]

            if not current_phone or current_phone not in valid_phones:
                rec.phone = rec.partner_id.phone or rec.partner_id.mobile or False

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id:
            inv = self.invoice_id
            if inv.partner_id:
                self.partner_id = inv.partner_id
                self.phone = inv.partner_id.phone or inv.partner_id.mobile or False
            if inv.custom_total < 0:
                self.amount = abs(inv.custom_total)
            elif inv.amount_total < 0:
                self.amount = abs(inv.amount_total)
            self.ref = inv.name
            self.payment_type = 'outbound'
            self.partner_type = 'customer'
            if hasattr(inv, 'branch_id') and inv.branch_id:
                self.branch_id = inv.branch_id
            if hasattr(inv, 'sale_id') and inv.sale_id:
                self.sale_id = inv.sale_id
            elif hasattr(inv, 'line_ids'):
                sale_lines = inv.line_ids.sale_line_ids
                if sale_lines:
                    self.sale_id = sale_lines.order_id[0]

    def action_post(self):
        res = super().action_post()
        for payment in self:
            if payment.payment_type == 'outbound' and payment.partner_type == 'customer':
                # Locate linked customer invoice
                invoice = payment.invoice_id
                if not invoice and payment.ref:
                    invoice = self.env['account.move'].search([
                        ('name', '=', payment.ref),
                        ('move_type', '=', 'out_invoice'),
                        ('company_id', '=', payment.company_id.id)
                    ], limit=1)

                # Get payment's unreconciled receivable move lines (Debtors)
                pay_debtors = payment.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                )
                if pay_debtors:
                    lines_to_reconcile = pay_debtors
                    if invoice:
                        # Linked sale order old gold / sale return entries
                        order = invoice.sale_id if hasattr(invoice, 'sale_id') and invoice.sale_id else False
                        if not order and hasattr(invoice, 'line_ids'):
                            sale_lines = invoice.line_ids.sale_line_ids
                            if sale_lines:
                                order = sale_lines.order_id[0]

                        if order:
                            if hasattr(order, 'old_gold_entry_id') and order.old_gold_entry_id:
                                og_debtors = order.old_gold_entry_id.line_ids.filtered(
                                    lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                                )
                                lines_to_reconcile |= og_debtors
                            if hasattr(order, 'sale_return_entry_id') and order.sale_return_entry_id:
                                sr_debtors = order.sale_return_entry_id.line_ids.filtered(
                                    lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                                )
                                lines_to_reconcile |= sr_debtors

                        inv_debtors = invoice.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                        )
                        lines_to_reconcile |= inv_debtors

                    # If only the payment's line is present, search open credit lines for this partner
                    if len(lines_to_reconcile) <= 1:
                        open_credits = self.env['account.move.line'].search([
                            ('partner_id', '=', payment.partner_id.id),
                            ('account_id', 'in', pay_debtors.mapped('account_id').ids),
                            ('credit', '>', 0),
                            ('reconciled', '=', False),
                            ('company_id', '=', payment.company_id.id),
                        ])
                        lines_to_reconcile |= open_credits

                    if len(lines_to_reconcile) > 1:
                        try:
                            lines_to_reconcile.reconcile()
                        except Exception:
                            pass

                    if invoice:
                        invoice.write({
                            'is_paid': True,
                            'custom_total': 0.0,
                            'payment_to_id': payment.id,
                        })
                        if not payment.invoice_id:
                            payment.invoice_id = invoice.id
                        if not payment.sale_id and hasattr(invoice, 'sale_id') and invoice.sale_id:
                            payment.sale_id = invoice.sale_id.id

        return res

    def _get_display_payment_method(self):
        """Determine a clean, descriptive payment method label for receipts and invoices.
        Prioritizes Pine Labs transaction details (UPI / Card type) when available."""
        self.ensure_one()
        txn = getattr(self, 'pinelabs_transaction_id', False)
        if not txn and 'pinelabs.transaction' in self.env:
            txn = self.env['pinelabs.transaction'].search([
                ('payment_id', '=', self.id),
                ('state', '=', 'success'),
            ], limit=1)
            if not txn and self.sale_id:
                txn = self.env['pinelabs.transaction'].search([
                    ('sale_order_id', '=', self.sale_id.id),
                    ('state', '=', 'success'),
                ], limit=1)

        if txn:
            mode = (txn.payment_mode or '').strip().upper()
            card_type = (txn.card_type or '').strip().upper()
            if mode == 'UPI' or card_type == 'UPI':
                return 'UPI'
            elif card_type in ('CREDIT', 'DEBIT'):
                return f"Card ({card_type.title()})"
            elif mode == 'CARD':
                return 'Card'
            elif txn.payment_mode:
                return txn.payment_mode.title()

        if self.journal_id:
            j_type = (self.journal_id.type or '').lower()
            j_name = self.journal_id.name or ''
            j_name_lower = j_name.lower()

            if j_type == 'cash' or 'cash' in j_name_lower:
                return 'Cash'
            if any(k in j_name_lower for k in ['upi', 'gpay', 'google pay', 'phonepe', 'paytm', 'bhim']):
                return 'UPI'
            if any(k in j_name_lower for k in ['card', 'pos', 'pine', 'credit', 'debit', 'visa', 'mastercard']):
                return 'Card'

            ref_lower = (self.ref or '').lower()
            if any(k in ref_lower for k in ['upi', 'gpay', 'phonepe', 'paytm']):
                return 'UPI'
            if any(k in ref_lower for k in ['card', 'pos', 'pine']):
                return 'Card'

            pml_name = self.payment_method_line_id.name if self.payment_method_line_id else ''
            if pml_name and pml_name.lower() not in ('manual', ''):
                return pml_name

            return j_name

        return (self.payment_method_id.name if self.payment_method_id else '') or 'Manual'

