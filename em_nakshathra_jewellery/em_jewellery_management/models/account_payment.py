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
