# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    sale_id = fields.Many2one('sale.order', string="Sales Order", readonly=True)
    invoice_id = fields.Many2one(
        'account.move',
        string="Invoice",
        domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]",
        readonly=False,
    )

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id:
            inv = self.invoice_id
            if inv.partner_id:
                self.partner_id = inv.partner_id
            if inv.custom_total < 0:
                self.amount = abs(inv.custom_total)
            elif inv.amount_total < 0:
                self.amount = abs(inv.amount_total)
            elif getattr(inv, 'outstanding_balance_to_pay_customer', 0.0) > 0:
                self.amount = inv.outstanding_balance_to_pay_customer
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
                if getattr(payment, 'is_scheme_refund', False):
                    continue

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

                        # Prioritize remaining credit lines already applied to this invoice
                        if len(lines_to_reconcile) <= 1:
                            applied_credits = invoice._get_applied_credit_remaining_lines().filtered(
                                lambda l: l.account_id in pay_debtors.mapped('account_id')
                            )
                            lines_to_reconcile |= applied_credits

                    # Fallback: if still no counterpart line, search open credit lines for this partner
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
                        inv_vals = {'payment_to_id': payment.id}
                        if invoice.custom_total < 0:
                            inv_vals.update({
                                'is_paid': True,
                                'custom_total': 0.0,
                            })
                        invoice.write(inv_vals)
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

