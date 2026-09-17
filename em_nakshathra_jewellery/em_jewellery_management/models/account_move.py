# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import formatLang


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = 'account.move'

    unfix = fields.Boolean(string="Unfix", default=False)
    job_work_id = fields.Many2one('jewellery.job.work')
    old_gold_price = fields.Monetary(string="Old Gold Price")
    sale_return_price = fields.Monetary(string="Sale Return Price")
    is_sale_return = fields.Boolean(string="Sale Return", compute="_compute_is_sale_return", store=True, readonly=False)
    custom_total = fields.Monetary(string="Paid to")

    is_paid = fields.Boolean(string="Is Paid")
    payment_to_id = fields.Many2one("account.payment",string="Payment ID")
    is_old_gold_bill = fields.Boolean(string="Is Old Gold Bill")
    unfix = fields.Boolean(string="Unfix", copy=False)
    is_approved = fields.Boolean(string="Manager Approved", default=False, copy=False)
    vendor_bill_amount = fields.Monetary(
        string="PO Amount",
        compute='_compute_vendor_bill_amount',
        store=False,
    )
# need to hide method after import saleorder
    def _set_next_sequence(self):
        """
        OVERRIDE to fix Odoo 17 concurrency race condition during sequence generation.
        The core sequence.mixin's while True retry loop only flushes `name`. 
        If `state` is not flushed to 'posted' in the DB, the `account_move_unique_name`
        UNIQUE constraint is bypassed during the loop and triggers outside of it, crashing the transaction.
        Flushing `state` ensures the UNIQUE constraint triggers INSIDE the retry loop.
        """
        for move in self:
            if move.state == 'posted':
                move.flush_recordset(['state'])
        return super()._set_next_sequence()

    @api.depends('invoice_line_ids.sale_line_ids.order_id.is_sale_return', 'invoice_line_ids.purchase_line_id.order_id.is_sale_return_po')
    def _compute_is_sale_return(self):
        for move in self:
            is_so_return = any(line.sale_line_ids.order_id.is_sale_return for line in move.invoice_line_ids if line.sale_line_ids)
            is_po_return = any(line.purchase_line_id.order_id.is_sale_return_po for line in move.invoice_line_ids if line.purchase_line_id)
            move.is_sale_return = is_so_return or is_po_return

    @api.depends('unfix', 'invoice_line_ids')
    def _compute_vendor_bill_amount(self):
        for move in self:
            amount = 0.0
            if move.unfix and move.move_type == 'out_invoice':
                # Find the linked sale order
                sale_orders = move.line_ids.mapped('sale_line_ids.order_id')
                for order in sale_orders:
                    po = order.purchase_order_id
                    if po:
                        bills = po.invoice_ids.filtered(
                            lambda m: m.move_type == 'in_invoice' and m.state == 'posted'
                        )
                        amount += sum(bills.mapped('amount_total'))
            move.vendor_bill_amount = amount

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        move_type = vals.get('move_type') or self._context.get('default_move_type')
        if move_type == 'in_invoice':
            today = fields.Date.context_today(self)
            if 'invoice_date' in fields_list and not vals.get('invoice_date'):
                vals['invoice_date'] = today
            if 'date' in fields_list and not vals.get('date'):
                vals['date'] = today
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.context_today(self)
        for vals in vals_list:
            move_type = vals.get('move_type') or self._context.get('default_move_type')
            if move_type == 'in_invoice':
                vals.setdefault('invoice_date', today)
                vals.setdefault('date', today)
        return super().create(vals_list)


    def _compute_tax_totals(self):
        res = super()._compute_tax_totals()
        for move in self.filtered(lambda move: move.tax_totals):
            if move.old_gold_price:
                move.tax_totals['amount_untaxed'] = move.tax_totals['amount_untaxed'] - move.old_gold_price
            if move.unfix and move.move_type == 'out_invoice' and move.vendor_bill_amount:
                move.tax_totals['amount_untaxed'] = move.tax_totals['amount_untaxed'] - move.vendor_bill_amount
            if move.sale_return_price:
                move.tax_totals['amount_untaxed'] = move.tax_totals['amount_untaxed'] - move.sale_return_price
        return res

    def _compute_amount_one(self):
        """Perform totals computation of a move with global discounts."""
        for move in self:
            deduction = (move.old_gold_price or 0.0) + (move.sale_return_price or 0.0)
            if move.unfix and move.move_type == 'out_invoice':
                deduction += move.vendor_bill_amount or 0.0

            if not deduction:
                continue

            term_lines = move.line_ids.filtered(lambda l: l.display_type == 'payment_term')
            if not term_lines:
                term_lines = move.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable'))

            sign = move.direction_sign
            if term_lines:
                raw_residual = -sign * sum(term_lines.mapped('amount_residual_currency'))
            else:
                raw_residual = move.amount_total

            if hasattr(move, 'amount_rounding') and move.amount_rounding and not move.line_ids.filtered(lambda l: l.display_type == 'rounding'):
                raw_residual += move.amount_rounding

            # Account for any amount already reconciled on this invoice to avoid double-deduction
            already_reconciled = max(0.0, move.amount_total - raw_residual)
            effective_deduction = max(0.0, deduction - already_reconciled)

            net_residual = raw_residual - effective_deduction

            if move.currency_id.compare_amounts(net_residual, 0.0) > 0:
                # Customer owes balance to the store
                move.custom_total = 0.0
                move.amount_residual = net_residual
                net_residual_signed = move.currency_id._convert(
                    net_residual,
                    move.company_currency_id,
                    move.company_id,
                    move.invoice_date or move.date or fields.Date.today()
                )
                move.amount_residual_signed = -sign * net_residual_signed if sign != 0 else net_residual_signed
                if move.state == 'posted':
                    total_base = move.amount_total
                    if move.currency_id.compare_amounts(raw_residual, total_base) < 0:
                        move.payment_state = 'partial'
                    else:
                        move.payment_state = 'not_paid'
            else:
                # Deduction covers or exceeds invoice total
                move.amount_residual = 0.0
                move.amount_residual_signed = 0.0
                if move.state == 'posted':
                    move.payment_state = 'paid'
                if not move.is_paid:
                    move.custom_total = net_residual  # Negative amount store owes customer
                else:
                    move.custom_total = 0.0

    @api.depends(
        "line_ids.matched_debit_ids.debit_move_id.move_id.payment_id.is_matched",
        "line_ids.matched_debit_ids.debit_move_id.move_id.line_ids.amount_residual",
        "line_ids.matched_debit_ids.debit_move_id.move_id.line_ids.amount_residual_currency",
        "line_ids.matched_credit_ids.credit_move_id.move_id.payment_id.is_matched",
        "line_ids.matched_credit_ids.credit_move_id.move_id.line_ids.amount_residual",
        "line_ids.matched_credit_ids.credit_move_id.move_id.line_ids.amount_residual_currency",
        "line_ids.balance",
        "line_ids.currency_id",
        "line_ids.amount_currency",
        "line_ids.amount_residual",
        "line_ids.amount_residual_currency",
        "line_ids.payment_id.state",
        "line_ids.full_reconcile_id",
        "old_gold_price",
        "sale_return_price"

    )
    def _compute_amount(self):
        """Modify totals computation for including global discounts."""
        res = super()._compute_amount()
        for record in self:
            if record.old_gold_price or record.sale_return_price or (record.unfix and record.move_type == 'out_invoice'):
                record._compute_amount_one()
            if self.env.context.get('bypass_negative_total_check') and record.amount_total < 0:
                record.amount_total = 0.0
        return res
    def action_approve_bill(self):
        for move in self:
            if not self.env.user.has_group('em_jewellery_management.group_jewellery_manager'):
                raise ValidationError(_("Only managers can approve vendor bills."))
            move.is_approved = True

    def action_post(self):
        for move in self:
            if move.move_type == 'in_invoice' and not move.is_approved:
                is_old_gold_po = any(po.is_old_gold for po in move.line_ids.mapped('purchase_line_id.order_id'))
                is_sale_return_po = any(po.is_sale_return_po for po in move.line_ids.mapped('purchase_line_id.order_id'))
                if move.is_old_gold_bill or move.is_sale_return or move.unfix or is_old_gold_po or is_sale_return_po:
                    continue
                raise ValidationError(_("This vendor bill must be approved by a manager before it can be confirmed."))
        res = super().action_post()
        for move in self:
            if move.move_type == 'out_invoice':
                sale_orders = move.line_ids.mapped('sale_line_ids.order_id')
                for order in sale_orders:
                    if order.old_gold_entry_id:
                        entry = order.old_gold_entry_id
                        entry_debtors = entry.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                        )
                        inv_debtors = move.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                        )
                        if entry_debtors and inv_debtors:
                            try:
                                (entry_debtors + inv_debtors).reconcile()
                            except Exception:
                                pass
                    if order.sale_return_entry_id:
                        sr_entry = order.sale_return_entry_id
                        sr_entry_debtors = sr_entry.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                        )
                        inv_debtors = move.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                        )
                        if sr_entry_debtors and inv_debtors:
                            try:
                                (sr_entry_debtors + inv_debtors).reconcile()
                            except Exception:
                                pass
        return res



    def _post(self, soft=True):
        posted = super(AccountMove, self.with_context(bypass_negative_total_check=True))._post(soft)
        for move in posted:
            move.with_context(bypass_negative_total_check=False)._compute_amount()
        return posted

    def action_open_customer_payment_wizard(self):
        self.ensure_one()
        if self.custom_total >= 0 and self.amount_total >= 0:
            raise ValidationError(_("Invoice is not negative."))

        domain = [
            ('company_id', '=', self.company_id.id),
            ('type', 'in', ('cash', 'bank')),
            ('default_account_id', '!=', False),
        ]
        journal = False
        if hasattr(self, 'branch_id') and self.branch_id:
            journal = self.env['account.journal'].search(
                domain + [('branch_id', '=', self.branch_id.id), ('type', '=', 'cash')], limit=1
            ) or self.env['account.journal'].search(
                domain + [('branch_id', '=', self.branch_id.id)], limit=1
            )
        if not journal:
            journal = self.env['account.journal'].search(domain, limit=1)
        if not journal:
            journal = self.env['account.journal'].search([
                ('company_id', '=', self.company_id.id),
                ('type', 'in', ('cash', 'bank')),
            ], limit=1)

        sale_order_id = False
        if hasattr(self, 'sale_id') and self.sale_id:
            sale_order_id = self.sale_id.id
        elif hasattr(self, 'line_ids'):
            sale_lines = self.line_ids.sale_line_ids
            if sale_lines:
                sale_order_id = sale_lines.order_id[0].id

        return {
            'name': _('Customer Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_payment_type': 'outbound',
                'default_partner_type': 'customer',
                'default_partner_id': self.partner_id.id,
                'default_amount': abs(self.custom_total) if self.custom_total < 0 else abs(self.amount_total),
                'default_journal_id': journal.id if journal else False,
                'default_branch_id': self.branch_id.id if hasattr(self, 'branch_id') and self.branch_id else False,
                'default_company_id': self.company_id.id,
                'default_ref': self.name,
                'default_invoice_id': self.id,
                'default_sale_id': sale_order_id,
            },
        }

    def action_customer_payment_wizard(self):
        return self.action_open_customer_payment_wizard()

    def action_create_old_gold_vendor_payment(self, journal=None, payment_date=None, memo=None, amount=None):
        Payment = self.env['account.payment']

        for move in self:
            if move.custom_total >= 0 and move.amount_total >= 0:
                raise ValidationError(_("Invoice is not negative."))

            pay_amount = amount if amount is not None else (abs(move.custom_total) if move.custom_total < 0 else abs(move.amount_total))

            pay_journal = journal
            if not pay_journal:
                domain = [
                    ('type', 'in', ('bank', 'cash')),
                    ('company_id', '=', move.company_id.id),
                    ('default_account_id', '!=', False)
                ]
                if hasattr(move, 'branch_id') and move.branch_id:
                    pay_journal = self.env['account.journal'].search(
                        domain + [('branch_id', '=', move.branch_id.id)], limit=1
                    )
                if not pay_journal:
                    pay_journal = self.env['account.journal'].search(domain, limit=1)
                if not pay_journal:
                    pay_journal = self.env['account.journal'].search([
                        ('type', 'in', ('bank', 'cash')),
                        ('company_id', '=', move.company_id.id)
                    ], limit=1)

            if not pay_journal:
                raise ValidationError(_("No bank/cash journal found."))
            elif not pay_journal.default_account_id:
                raise ValidationError(_("The selected journal '%s' is missing a Default Account. Please configure its accounts in Accounting settings to allow payments.") % pay_journal.name)

            receivable_account = move.partner_id.with_company(move.company_id).property_account_receivable_id
            inv_receivable = move.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
            destination_account_id = inv_receivable[0].account_id.id if inv_receivable else receivable_account.id

            sale_order_id = False
            if hasattr(move, 'sale_id') and move.sale_id:
                sale_order_id = move.sale_id.id
            elif hasattr(move, 'line_ids'):
                sale_lines = move.line_ids.sale_line_ids
                if sale_lines:
                    sale_order_id = sale_lines.order_id[0].id

            payment = Payment.create({
                'payment_type': 'outbound',
                'partner_type': 'customer',
                'partner_id': move.partner_id.id,
                'amount': pay_amount,
                'journal_id': pay_journal.id,
                'date': payment_date or fields.Date.today(),
                'ref': memo or move.name,
                'branch_id': move.branch_id.id if hasattr(move, 'branch_id') and move.branch_id else False,
                'destination_account_id': destination_account_id,
                'invoice_id': move.id,
                'sale_id': sale_order_id,
            })

            # Force the outstanding account if Odoo's internal compute failed to find one
            if not payment.outstanding_account_id and pay_journal.default_account_id:
                payment.outstanding_account_id = pay_journal.default_account_id.id

            payment.action_post()

        return True
