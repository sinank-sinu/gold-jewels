# -*- coding: utf-8 -*-

from datetime import timedelta
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
    is_old_gold = fields.Boolean(
        string="Old Gold",
        compute="_compute_is_old_gold",
        store=True,
        readonly=True,
        copy=False,
    )
    is_diamond_og = fields.Boolean(
        string="Diamond OG",
        compute="_compute_is_diamond_og",
        store=True,
        readonly=True,
        copy=False,
    )
    unfix = fields.Boolean(string="Unfix", copy=False)
    is_approved = fields.Boolean(string="Manager Approved", default=False, copy=False)
    vendor_bill_amount = fields.Monetary(
        string="PO Amount",
        compute='_compute_vendor_bill_amount',
        store=False,
    )
    show_approve_bill = fields.Boolean(
        string="Show Approve Bill",
        compute="_compute_show_approve_bill",
    )

    @api.depends(
        'is_old_gold_bill',
        'invoice_line_ids.purchase_line_id.order_id.is_old_gold',
        'line_ids.purchase_line_id.order_id.is_old_gold',
    )
    def _compute_is_old_gold(self):
        for move in self:
            pos = (move.invoice_line_ids | move.line_ids).mapped('purchase_line_id.order_id')
            is_og_po = any(po.is_old_gold for po in pos)
            move.is_old_gold = bool(is_og_po or move.is_old_gold_bill)

    @api.depends(
        'is_sale_return',
        'invoice_line_ids.purchase_line_id.order_id.is_sale_return_shop',
        'invoice_line_ids.purchase_line_id.order_id.is_sale_return_po',
        'line_ids.purchase_line_id.order_id.is_sale_return_shop',
        'line_ids.purchase_line_id.order_id.is_sale_return_po',
    )
    def _compute_is_diamond_og(self):
        for move in self:
            pos = (move.invoice_line_ids | move.line_ids).mapped('purchase_line_id.order_id')
            is_diamond_po = any(
                (getattr(po, 'is_sale_return_shop', False) or getattr(po, 'is_sale_return_po', False))
                for po in pos
            )
            move.is_diamond_og = bool(is_diamond_po or move.is_sale_return)

    def _is_og_or_diamond_og(self):
        self.ensure_one()
        return bool(
            self.is_old_gold
            or self.is_diamond_og
            or getattr(self, 'is_old_gold_bill', False)
            or getattr(self, 'is_sale_return', False)
            or getattr(self, 'is_sale_return_shop', False)
        )

    @api.depends('move_type', 'state', 'is_approved', 'is_old_gold', 'is_diamond_og', 'is_old_gold_bill', 'is_sale_return')
    def _compute_show_approve_bill(self):
        is_manager = self.env.user.has_group('em_jewellery_management.group_jewellery_manager')
        is_billing = self.env.user.has_group('em_jewellery_management.group_jewellery_billing_staff')
        for move in self:
            if move.move_type != 'in_invoice' or move.state != 'draft' or move.is_approved:
                move.show_approve_bill = False
            elif is_manager:
                move.show_approve_bill = True
            elif is_billing and move._is_og_or_diamond_og():
                move.show_approve_bill = True
            else:
                move.show_approve_bill = False

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
                if vals.get('is_old_gold'):
                    vals['is_old_gold_bill'] = True
                if vals.get('is_diamond_og'):
                    vals['is_sale_return_shop'] = True
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
        is_manager = self.env.user.has_group('em_jewellery_management.group_jewellery_manager')
        is_billing = self.env.user.has_group('em_jewellery_management.group_jewellery_billing_staff')
        for move in self:
            if not is_manager:
                if not (is_billing and move._is_og_or_diamond_og()):
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

    def action_create_old_gold_vendor_payment(self, journal=None, payment_date=None, memo=None, amount=None, account=None):
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
            if hasattr(move, 'line_ids'):
                sale_lines = move.line_ids.sale_line_ids
                if sale_lines:
                    sale_order_id = sale_lines.order_id[0].id

            # NEW LOGIC: "every cash journal change to ca"
            # If account is not explicitly passed, but a cash journal is used, force the CA (Cash Account).
            if not account and pay_journal.type == 'cash' and pay_journal.default_account_id:
                account = pay_journal.default_account_id

            if account:
                # Bypass account.payment to avoid Odoo 17 outstanding account synchronization issues.
                # Create a direct journal entry to guarantee the chosen Cash Account is used.
                move_vals = {
                    'journal_id': pay_journal.id,
                    'date': payment_date or fields.Date.today(),
                    'ref': memo or move.name,
                    'move_type': 'entry',
                    'company_id': move.company_id.id,
                    'branch_id': move.branch_id.id if hasattr(move, 'branch_id') and move.branch_id else False,
                    'line_ids': [
                        (0, 0, {
                            'account_id': account.id,
                            'name': memo or move.name,
                            'debit': pay_amount,
                            'credit': 0.0,
                            'partner_id': move.partner_id.id,
                            'branch_id': move.branch_id.id if hasattr(move, 'branch_id') and move.branch_id else False,
                        }),
                        (0, 0, {
                            'account_id': destination_account_id,
                            'name': memo or move.name,
                            'debit': 0.0,
                            'credit': pay_amount,
                            'partner_id': move.partner_id.id,
                            'branch_id': move.branch_id.id if hasattr(move, 'branch_id') and move.branch_id else False,
                        }),
                    ]
                }
                new_move = self.env['account.move'].create(move_vals)
                new_move.action_post()
                
                # Reconcile the new move with the invoice
                lines_to_reconcile = new_move.line_ids.filtered(lambda l: l.account_id.id == destination_account_id) + inv_receivable
                if len(lines_to_reconcile) > 1:
                    try:
                        lines_to_reconcile.reconcile()
                    except Exception:
                        pass
                continue

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

            if not payment.outstanding_account_id and pay_journal.default_account_id:
                payment.outstanding_account_id = pay_journal.default_account_id.id

            payment.action_post()

        return True

    def _get_report_old_gold_lines(self):
        self.ensure_one()
        lines = self.env['sale.old.gold.line']
        sale_orders = self.line_ids.mapped('sale_line_ids.order_id')
        if not sale_orders and self.invoice_origin:
            sale_orders = self.env['sale.order'].sudo().search([('name', '=', self.invoice_origin)])
        for so in sale_orders:
            if hasattr(so, 'old_gold_line_ids'):
                lines |= so.old_gold_line_ids
        if not lines:
            po_orders = (self.invoice_line_ids | self.line_ids).mapped('purchase_line_id.order_id')
            for po in po_orders:
                if hasattr(po, 'old_gold_line_ids') and po.old_gold_line_ids:
                    lines |= po.old_gold_line_ids
                if hasattr(po, 'sale_id') and po.sale_id and hasattr(po.sale_id, 'old_gold_line_ids'):
                    lines |= po.sale_id.old_gold_line_ids
        return lines

    def _get_report_sale_return_lines(self):
        self.ensure_one()
        lines = self.env['sale.return.line']
        sale_orders = self.line_ids.mapped('sale_line_ids.order_id')
        if not sale_orders and self.invoice_origin:
            sale_orders = self.env['sale.order'].sudo().search([('name', '=', self.invoice_origin)])
        for so in sale_orders:
            if hasattr(so, 'sale_return_line_ids'):
                lines |= so.sale_return_line_ids
        if not lines:
            po_orders = (self.invoice_line_ids | self.line_ids).mapped('purchase_line_id.order_id')
            for po in po_orders:
                if hasattr(po, 'sale_id') and po.sale_id and hasattr(po.sale_id, 'sale_return_line_ids'):
                    lines |= po.sale_id.sale_return_line_ids
                for pl in po.order_line:
                    if hasattr(pl, 'sale_return_line_id') and pl.sale_return_line_id:
                        lines |= pl.sale_return_line_id
        return lines

    def _get_report_sale_return_details(self):
        self.ensure_one()
        details = []
        seen_bills = set()
        seen_sos = set()

        # 1. Search linked Sale Orders
        sale_orders = self.line_ids.mapped('sale_line_ids.order_id')
        if not sale_orders and self.invoice_origin:
            sale_orders = self.env['sale.order'].sudo().search([('name', '=', self.invoice_origin)])

        for so in sale_orders:
            if getattr(so, 'is_sale_return', False) or (hasattr(so, 'sale_return_line_ids') and so.sale_return_line_ids):
                bill = getattr(so, 'sale_return_bill_id', False)
                if bill:
                    if bill.id not in seen_bills:
                        seen_bills.add(bill.id)
                        amt = bill.amount_total or getattr(so, 'sale_return_bill_amount', 0.0) or sum(so.sale_return_line_ids.mapped('amount'))
                        b_name = bill.name if (bill.name and bill.name != '/') else (bill.ref or so.name or '')
                        details.append({
                            'bill_no': b_name,
                            'amount': amt,
                        })
                elif so.id not in seen_sos:
                    seen_sos.add(so.id)
                    amt = sum(so.sale_return_line_ids.mapped('amount')) if hasattr(so, 'sale_return_line_ids') else 0.0
                    if amt:
                        details.append({
                            'bill_no': so.name or '',
                            'amount': amt,
                        })

        # 2. Check purchase orders if not found from sale orders
        if not details:
            po_orders = (self.invoice_line_ids | self.line_ids).mapped('purchase_line_id.order_id')
            for po in po_orders:
                if hasattr(po, 'sale_id') and po.sale_id:
                    so = po.sale_id
                    bill = getattr(so, 'sale_return_bill_id', False)
                    if bill:
                        if bill.id not in seen_bills:
                            seen_bills.add(bill.id)
                            amt = bill.amount_total or getattr(so, 'sale_return_bill_amount', 0.0) or sum(so.sale_return_line_ids.mapped('amount'))
                            b_name = bill.name if (bill.name and bill.name != '/') else (bill.ref or so.name or '')
                            details.append({
                                'bill_no': b_name,
                                'amount': amt,
                            })
                    elif so.id not in seen_sos:
                        seen_sos.add(so.id)
                        amt = sum(so.sale_return_line_ids.mapped('amount')) if hasattr(so, 'sale_return_line_ids') else 0.0
                        if amt:
                            details.append({
                                'bill_no': so.name or '',
                                'amount': amt,
                            })
                for pl in po.order_line:
                    sr_line = getattr(pl, 'sale_return_line_id', False)
                    if sr_line and sr_line.sale_id:
                        so = sr_line.sale_id
                        bill = getattr(so, 'sale_return_bill_id', False)
                        if bill:
                            if bill.id not in seen_bills:
                                seen_bills.add(bill.id)
                                amt = bill.amount_total or getattr(so, 'sale_return_bill_amount', 0.0) or sum(so.sale_return_line_ids.mapped('amount'))
                                b_name = bill.name if (bill.name and bill.name != '/') else (bill.ref or so.name or '')
                                details.append({
                                    'bill_no': b_name,
                                    'amount': amt,
                                })
                        elif so.id not in seen_sos:
                            seen_sos.add(so.id)
                            amt = sum(so.sale_return_line_ids.mapped('amount')) if hasattr(so, 'sale_return_line_ids') else 0.0
                            if amt:
                                details.append({
                                    'bill_no': so.name or '',
                                    'amount': amt,
                                })

        # 3. Check report_sr_lines if still no details
        if not details:
            sr_lines = self._get_report_sale_return_lines()
            if sr_lines:
                for line in sr_lines:
                    so = getattr(line, 'sale_id', False)
                    bill = getattr(so, 'sale_return_bill_id', False) if so else False
                    if bill and bill.id not in seen_bills:
                        seen_bills.add(bill.id)
                        amt = bill.amount_total or getattr(so, 'sale_return_bill_amount', 0.0) or sum(so.sale_return_line_ids.mapped('amount'))
                        b_name = bill.name if (bill.name and bill.name != '/') else (bill.ref or so.name or '')
                        details.append({'bill_no': b_name, 'amount': amt})
                    elif so and so.id not in seen_sos:
                        seen_sos.add(so.id)
                        amt = sum(so.sale_return_line_ids.mapped('amount'))
                        if amt:
                            details.append({'bill_no': so.name or '', 'amount': amt})

        # 4. Fallback: if move has sale_return_price
        if not details and getattr(self, 'sale_return_price', 0.0):
            details.append({
                'bill_no': self.invoice_origin or self.ref or '-',
                'amount': self.sale_return_price,
            })

        return details


    def _get_report_scheme_info(self):
        self.ensure_one()
        is_redeemed = getattr(self, 'is_scheme_redeemed', False)
        amt = getattr(self, 'scheme_amount', 0.0) or 0.0
        tickets = []

        if hasattr(self, 'customer_schemes') and self.customer_schemes:
            for s in self.customer_schemes:
                if getattr(s, 'is_redeemed', False) or s.state == 'redeemed':
                    is_redeemed = True
                    if getattr(s, 'ticket_number', None):
                        tickets.append(s.ticket_number)
                    elif s.name:
                        tickets.append(s.name)

        if not is_redeemed or not amt:
            sale_orders = self.line_ids.mapped('sale_line_ids.order_id')
            if not sale_orders and self.invoice_origin:
                sale_orders = self.env['sale.order'].sudo().search([('name', '=', self.invoice_origin)])
            for so in sale_orders:
                if getattr(so, 'is_scheme_redeemed', False) and getattr(so, 'scheme_amount', 0.0):
                    is_redeemed = True
                    amt = max(amt, so.scheme_amount)
                if hasattr(so, 'customer_schemes') and so.customer_schemes:
                    for s in so.customer_schemes:
                        if (getattr(s, 'is_redeemed', False) or s.state == 'redeemed') and getattr(s, 'ticket_number', None) and s.ticket_number not in tickets:
                            tickets.append(s.ticket_number)

        if not is_redeemed or not amt:
            if 'scheme.redemption' in self.env:
                redemptions = self.env['scheme.redemption'].sudo().search([('move_id', '=', self.id)])
                if redemptions:
                    is_redeemed = True
                    amt = sum(redemptions.mapped('amount'))
                    for r in redemptions:
                        if r.scheme_id and getattr(r.scheme_id, 'ticket_number', None) and r.scheme_id.ticket_number not in tickets:
                            tickets.append(r.scheme_id.ticket_number)

        return {
            'is_redeemed': bool(is_redeemed and amt > 0),
            'amount': amt,
            'ticket': ', '.join(tickets),
        }

    def _get_report_payment_details(self):
        self.ensure_one()
        payments_info = []
        seen_ids = set()

        def _classify_payment(pay=None, journal=None, item_data=None):
            j_name = (journal.name or '').lower() if journal else ''
            j_type = (journal.type or '').lower() if journal else ''
            
            pml = pay.payment_method_line_id if pay else None
            pml_name = (pml.name or '').lower() if pml else ''
            pml_code = (pml.code or '').lower() if pml else ''
            
            bank_ref = (getattr(pay, 'bank_reference', None) or '').strip() if pay else ''
            cheque_ref = (getattr(pay, 'cheque_reference', None) or '').strip() if pay else ''
            pine_ref = (getattr(pay, 'pinelabs_txn_ref', None) or '').strip() if pay else ''
            pine_app = (getattr(pay, 'pinelabs_approval_code', None) or '').strip() if pay else ''
            payment_ref = (getattr(pay, 'payment_reference', None) or '').strip() if pay else ''
            memo_ref = (pay.ref or '').strip() if pay else ((item_data.get('ref') or '').strip() if item_data else '')
            item_name = (item_data.get('name') or '').strip() if item_data else ''

            # If cash journal -> Method is Cash, no reference
            if j_type == 'cash' or 'cash' in j_name:
                return 'Cash', ''

            ref_parts = []
            if bank_ref:
                ref_parts.append(bank_ref)
            if cheque_ref and cheque_ref not in ref_parts:
                ref_parts.append(cheque_ref)
            if pine_ref and pine_ref not in ref_parts:
                ref_parts.append(pine_ref)
            if pine_app and pine_app not in ref_parts:
                ref_parts.append(pine_app)
            if payment_ref and payment_ref not in ref_parts and not any(p in payment_ref for p in ['/202', 'PCSH', 'PBNK', 'MISC/']):
                ref_parts.append(payment_ref)

            # If no specific transaction ref, check memo_ref excluding internal sequences
            if not ref_parts and memo_ref:
                clean_memo = memo_ref.replace(f"({self.name})", "").strip() if self.name and self.name in memo_ref else memo_ref
                is_internal_seq = (
                    clean_memo == self.name or
                    any(p in clean_memo for p in ['/202', 'PCSH', 'PBNK', 'MISC/'])
                )
                if not is_internal_seq and clean_memo:
                    ref_parts.append(clean_memo)

            final_ref = ', '.join(ref_parts)

            # Detect UPI / Card / Bank
            search_str = f"{j_name} {pml_name} {pml_code} {bank_ref.lower()} {cheque_ref.lower()} {memo_ref.lower()} {item_name.lower()}"

            upi_keywords = ['upi', 'gpay', 'google pay', 'googlepay', 'phonepe', 'phone pe', 'paytm', 'bhim']
            if any(k in search_str for k in upi_keywords):
                return 'UPI', final_ref

            card_keywords = ['card', 'pine', 'pos', 'debit', 'credit', 'visa', 'mastercard', 'rupay']
            if pine_ref or pine_app or any(k in search_str for k in card_keywords):
                return 'Card', final_ref

            if j_type == 'bank' or 'bank' in j_name or any(b in j_name for b in ['hdfc', 'federal', 'sbi', 'icici', 'axis']):
                return 'Bank', final_ref

            return 'Bank' if j_type == 'bank' else 'Payment', final_ref

        widget = self.sudo().invoice_payments_widget
        content = widget.get('content', []) if widget else []
        for item in content:
            name = item.get('name') or ''
            ref = item.get('ref') or ''
            journal_name = item.get('journal_name') or ''

            # Exclude Old Gold, Scheme, and Sale Return adjustments here as they are shown in separate deduction sections
            if 'Old Gold' in name or 'Old Gold' in ref or (journal_name == 'Miscellaneous Operations' and 'Old Gold' in ref):
                continue
            if 'Scheme' in name or 'Scheme' in ref or 'Scheme' in journal_name:
                continue

            c_move = self.env['account.move'].browse(item.get('move_id')) if item.get('move_id') else False
            is_credit_note = bool(c_move and c_move.move_type in ('out_refund', 'in_refund'))

            # Exclude Sale Return only if already deducted as sale_return_price in invoice totals
            has_sr_deduction = bool(getattr(self, 'sale_return_price', 0.0) > 0)
            if has_sr_deduction and ('Sale Return' in name or 'Sale Return' in ref or (journal_name == 'Miscellaneous Operations' and 'Sale Return' in ref)):
                continue
            elif not has_sr_deduction and (journal_name == 'Miscellaneous Operations' and 'Sale Return' in ref):
                continue

            pay_id = item.get('account_payment_id')
            pay = self.env['account.payment'].browse(pay_id) if pay_id else False

            is_outstanding = False
            if is_credit_note:
                is_outstanding = True
            elif pay:
                seen_ids.add(pay.id)
                # Check if payment was an outstanding credit / advance added to this invoice
                inv_name = self.name or ''
                has_inv_ref = bool(inv_name and ((inv_name in (pay.ref or '')) or (inv_name in (ref or ''))))
                created_before = bool(pay.create_date and self.create_date and pay.create_date < (self.create_date - timedelta(seconds=10)))
                date_before = bool(pay.date and self.invoice_date and pay.date < self.invoice_date)
                is_so_advance = bool(pay.sale_id and not has_inv_ref)
                if is_so_advance or (not has_inv_ref) or created_before or date_before:
                    is_outstanding = True
            else:
                is_outstanding = True

            journal = pay.journal_id if pay else self.env['account.journal'].search([('name', '=', journal_name)], limit=1)
            pay_method, pay_ref = _classify_payment(pay=pay, journal=journal, item_data=item)

            if is_credit_note:
                pay_method = 'Sale Return Amt'
                cn_name = c_move.name or (item.get('ref') or '').split(' ')[0]
                cn_ref = c_move.ref or ''
                if cn_ref and cn_ref != cn_name and not any(p in cn_ref for p in ['/202', 'PCSH', 'PBNK', 'MISC/']) and not cn_ref.startswith('Reversal of:'):
                    pay_ref = f"{cn_name} ({cn_ref})"
                else:
                    pay_ref = cn_name
            elif is_outstanding:
                if pay and getattr(pay, 'sale_id', False) and not pay_ref:
                    pay_ref = pay.sale_id.name or ''
                if pay_method and pay_method != 'Payment':
                    pay_method = f"Outstanding Added ({pay_method})"
                else:
                    pay_method = "Outstanding Added"

            payments_info.append({
                'method': pay_method,
                'ref': pay_ref,
                'amount': item.get('amount', 0.0),
                'date': item.get('date'),
                'is_outstanding': is_outstanding,
                'is_credit_note': is_credit_note,
            })

        if hasattr(self, 'payment_to_id') and self.payment_to_id and self.payment_to_id.id not in seen_ids:
            pay = self.payment_to_id
            seen_ids.add(pay.id)
            pay_method, pay_ref = _classify_payment(pay=pay, journal=pay.journal_id)
            payments_info.append({
                'method': pay_method,
                'ref': pay_ref,
                'amount': pay.amount,
                'date': pay.date,
            })

        return payments_info

    def _get_report_salesman_name(self):
        """ Return salesman name for report """
        self.ensure_one()
        salesmen = []
        for line in self.invoice_line_ids:
            for sline in line.sale_line_ids:
                if getattr(sline, 'salesman_id', False) and sline.salesman_id.name:
                    if sline.salesman_id.name not in salesmen:
                        salesmen.append(sline.salesman_id.name)
        if not salesmen:
            for line in self.invoice_line_ids:
                for sline in line.sale_line_ids:
                    if sline.order_id and sline.order_id.user_id and sline.order_id.user_id.name:
                        if sline.order_id.user_id.name not in salesmen:
                            salesmen.append(sline.order_id.user_id.name)
        if not salesmen and self.invoice_user_id and self.invoice_user_id.name:
            salesmen.append(self.invoice_user_id.name)
        if not salesmen and self.user_id and self.user_id.name:
            salesmen.append(self.user_id.name)
        return ', '.join(salesmen)

    def _get_report_gold_rates(self):
        """ Return list of dicts [{'label': '18CT Gold Rate:', 'rate': '₹ 11,400.00'}] for report """
        self.ensure_one()
        rate_by_purity = {}
        distinct_rates = []
        for line in self.invoice_line_ids:
            rate = 0.0
            purity = getattr(line, 'purity_id', False)
            for sline in line.sale_line_ids:
                if getattr(sline, 'gold_rate', False):
                    rate = sline.gold_rate
                    if not purity and getattr(sline, 'purity_id', False):
                        purity = sline.purity_id
                    break
            if not rate and hasattr(line, 'purchase_line_id') and line.purchase_line_id:
                pline = line.purchase_line_id
                if getattr(pline, 'gold_rate', False):
                    rate = pline.gold_rate
            if not rate and getattr(line, 'label_id', False) and getattr(line.label_id, 'purity_id', False):
                purity = line.label_id.purity_id

            if rate > 0:
                p_name = purity.name.split('(')[0].strip() if purity and purity.name else ''
                if p_name and p_name.isdigit():
                    p_name = f"{p_name}CT"
                if p_name:
                    if p_name not in rate_by_purity:
                        rate_by_purity[p_name] = rate
                elif rate not in distinct_rates:
                    distinct_rates.append(rate)

        results = []
        if rate_by_purity:
            for p, r in rate_by_purity.items():
                results.append({
                    'label': f"{p} Gold Rate:",
                    'rate': formatLang(self.env, r, currency_obj=self.currency_id)
                })
            return results

        if distinct_rates:
            for r in distinct_rates:
                results.append({
                    'label': 'Gold Rate:',
                    'rate': formatLang(self.env, r, currency_obj=self.currency_id)
                })
            return results

        inv_date = self.invoice_date or self.date or fields.Date.context_today(self)
        grm = self.env['gold.rate.master'].search([
            ('rate_type', '=', 'sale'),
            ('date', '<=', inv_date)
        ], order='date desc, id desc', limit=1)
        if grm and grm.rate_per_gram:
            results.append({
                'label': 'Gold Rate:',
                'rate': formatLang(self.env, grm.rate_per_gram, currency_obj=self.currency_id)
            })
            return results

        return results

    def _get_report_gold_rate(self):
        """ Return gold rate for report """
        rates = self._get_report_gold_rates()
        if not rates:
            return ''
        if len(rates) == 1:
            return rates[0]['rate']
        return ', '.join(f"{item['label'].replace(' Gold Rate:', '')}: {item['rate']}" for item in rates)

    def _get_report_net_amount(self):
        """ Return calculated net amount after deducting old gold, sale return, and scheme """
        self.ensure_one()
        net = self.amount_total - (getattr(self, 'old_gold_price', 0.0) or 0.0) - (getattr(self, 'sale_return_price', 0.0) or 0.0)
        scheme_info = self._get_report_scheme_info() if hasattr(self, '_get_report_scheme_info') else {}
        if scheme_info.get('is_redeemed') and scheme_info.get('amount'):
            net -= scheme_info['amount']
        return net

    def _get_report_total_subtotal_amount(self):
        """ Return untaxed lines total amount as float """
        self.ensure_one()
        return sum(line.price_subtotal for line in self.invoice_line_ids if line.display_type == 'product' or not line.display_type)

    def _get_report_net_amount_in_words(self):
        """ Return Net Amount in words based on calculated net amount """
        self.ensure_one()
        amount = self._get_report_net_amount()
        try:
            from num2words import num2words
            words = num2words(amount, lang='en_IN', to='currency', currency='INR')
            return words.title() + ' Only'
        except Exception:
            text = self.currency_id.amount_to_text(amount) if self.currency_id else ''
            return (text + ' Only') if text else ''

    def _get_report_total_gross_weight(self):
        """ Return sum of gross weight of invoice lines """
        self.ensure_one()
        total_gw = 0.0
        for line in self.invoice_line_ids:
            if line.display_type and line.display_type != 'product':
                continue
            sl = line.sale_line_ids[:1]
            pl = line.purchase_line_id
            gw = 0.0
            if sl:
                gw = getattr(sl, 'product_uom_qty', 0.0) or getattr(sl, 'gross_weight', 0.0)
            elif pl:
                gw = getattr(pl, 'product_qty', 0.0) or getattr(pl, 'gross_weight', 0.0)
            elif getattr(line, 'label_id', False) and getattr(line.label_id, 'gross_weight', 0.0):
                gw = line.label_id.gross_weight
            else:
                gw = getattr(line, 'gross_weight', 0.0) or line.quantity
            total_gw += (gw or 0.0)
        return f"{total_gw:,.3f}"

    def _get_report_total_net_weight(self):
        """ Return sum of net weight of invoice lines """
        self.ensure_one()
        total_nw = 0.0
        for line in self.invoice_line_ids:
            if line.display_type and line.display_type != 'product':
                continue
            sl = line.sale_line_ids[:1]
            pl = line.purchase_line_id
            nw = 0.0
            if sl and getattr(sl, 'net_weight', 0.0):
                nw = sl.net_weight
            elif pl and getattr(pl, 'net_weight', 0.0):
                nw = pl.net_weight
            elif getattr(line, 'label_id', False):
                lbl = line.label_id
                nw = getattr(lbl, 'sale_net_weight', 0.0) or getattr(lbl, 'purchase_net_weight', 0.0) or getattr(lbl, 'net_weight', 0.0)
            elif getattr(line, 'net_weight', 0.0):
                nw = line.net_weight
            total_nw += (nw or 0.0)
        return f"{total_nw:,.3f}"

    def _get_report_total_subtotal(self):
        """ Return total subtotal formatted with currency """
        self.ensure_one()
        total_sub = sum(line.price_subtotal for line in self.invoice_line_ids)
        return formatLang(self.env, total_sub, currency_obj=self.currency_id)

    def _get_report_visible_columns(self):
        """ Return dictionary of boolean flags indicating which table columns have values """
        self.ensure_one()
        cols = {
            'crt': False,
            'gr_wt': False,
            'nt_wt': False,
            'st_wt': False,
            'd_wt': False,
            'gold_rate': False,
            'metal_amt': False,
            'st_amt': False,
            'd_amt': False,
            'mc_amt': False,
            'mrp': False,
            'disc': False,
        }
        for line in self.invoice_line_ids:
            if line.display_type and line.display_type != 'product':
                continue
            sale_line = line.sale_line_ids and line.sale_line_ids[0] or False
            purchase_line = line.purchase_line_id or False

            # CRT
            if (sale_line and getattr(sale_line, 'purity_id', False)) or (purchase_line and getattr(purchase_line, 'purity_id', False)) or getattr(line, 'purity_id', False):
                cols['crt'] = True

            # Gr.Wt
            gw = 0.0
            if sale_line:
                gw = getattr(sale_line, 'product_uom_qty', 0.0) or getattr(sale_line, 'gross_weight', 0.0)
            elif purchase_line:
                gw = getattr(purchase_line, 'product_qty', 0.0) or getattr(purchase_line, 'gross_weight', 0.0)
            elif getattr(line, 'label_id', False) and getattr(line.label_id, 'gross_weight', 0.0):
                gw = line.label_id.gross_weight
            else:
                gw = getattr(line, 'gross_weight', 0.0) or line.quantity or 0.0
            if gw and gw > 0:
                cols['gr_wt'] = True

            # Nt.Wt
            nw = 0.0
            if sale_line and getattr(sale_line, 'net_weight', 0.0):
                nw = sale_line.net_weight
            elif purchase_line and getattr(purchase_line, 'net_weight', 0.0):
                nw = purchase_line.net_weight
            elif getattr(line, 'label_id', False):
                lbl = line.label_id
                nw = getattr(lbl, 'sale_net_weight', 0.0) or getattr(lbl, 'purchase_net_weight', 0.0) or getattr(lbl, 'net_weight', 0.0)
            elif getattr(line, 'net_weight', 0.0):
                nw = line.net_weight
            if nw and nw > 0:
                cols['nt_wt'] = True

            # St.Wt
            st_wt = (sale_line and getattr(sale_line, 'sale_stone_weight', 0.0)) or (sale_line and sale_line.label_id and getattr(sale_line.label_id, 'sale_stone_weight', 0.0)) or (line.label_id and getattr(line.label_id, 'sale_stone_weight', 0.0)) or (purchase_line and getattr(purchase_line, 'stone_weight', 0.0)) or 0.0
            if st_wt and st_wt > 0:
                cols['st_wt'] = True

            # D.Wt(c)
            d_wt = (sale_line and getattr(sale_line, 'sale_diamond_weight_ct', 0.0)) or (sale_line and sale_line.label_id and getattr(sale_line.label_id, 'sale_diamond_weight_ct', 0.0)) or (line.label_id and getattr(line.label_id, 'sale_diamond_weight_ct', 0.0)) or (sale_line and getattr(sale_line, 'sale_diamond_weight_gm', 0.0) and sale_line.sale_diamond_weight_gm * 5.0) or (line.label_id and getattr(line.label_id, 'sale_diamond_weight_gm', 0.0) and line.label_id.sale_diamond_weight_gm * 5.0) or (purchase_line and getattr(purchase_line, 'diamond_weight_gm', 0.0) and purchase_line.diamond_weight_gm * 5.0) or 0.0
            if d_wt and d_wt > 0:
                cols['d_wt'] = True

            # Gold Rate
            gr = (sale_line and getattr(sale_line, 'gold_rate', 0.0)) or (purchase_line and getattr(purchase_line, 'gold_rate', 0.0)) or 0.0
            if gr and gr > 0:
                cols['gold_rate'] = True

            # Metal Amt
            ma = (sale_line and getattr(sale_line, 'metal_amount', 0.0)) or (purchase_line and getattr(purchase_line, 'metal_amount', 0.0)) or 0.0
            if ma and ma > 0:
                cols['metal_amt'] = True

            # St.Amt
            st_amt = (sale_line and getattr(sale_line, 'sale_stone_rate', 0.0)) or (sale_line and sale_line.label_id and getattr(sale_line.label_id, 'sale_stone_rate', 0.0)) or (line.label_id and getattr(line.label_id, 'sale_stone_rate', 0.0)) or (purchase_line and getattr(purchase_line, 'stone_rate', 0.0)) or 0.0
            if st_amt and st_amt > 0:
                cols['st_amt'] = True

            # D.Amt
            d_amt = (sale_line and getattr(sale_line, 'sale_diamond_rate', 0.0)) or (sale_line and sale_line.label_id and getattr(sale_line.label_id, 'sale_diamond_rate', 0.0)) or (line.label_id and getattr(line.label_id, 'sale_diamond_rate', 0.0)) or (purchase_line and getattr(purchase_line, 'diamond_rate', 0.0)) or 0.0
            if d_amt and d_amt > 0:
                cols['d_amt'] = True

            # MC
            mc = (sale_line and getattr(sale_line, 'mc_amount', 0.0)) or (purchase_line and getattr(purchase_line, 'mc_amount', 0.0)) or 0.0
            if mc and mc > 0:
                cols['mc_amt'] = True

            # Disc / MRP
            disc = 0.0
            if sale_line and getattr(sale_line, 'price_subtotal_actual', 0.0):
                disc = getattr(sale_line, 'mc_discount', 0.0) if getattr(sale_line, 'mc_discount', 0.0) else (sale_line.price_subtotal_actual - sale_line.price_subtotal)
            elif sale_line and getattr(sale_line, 'mc_amount', 0.0) and getattr(sale_line, 'mc_amount_actual', 0.0):
                disc = sale_line.mc_amount - sale_line.mc_amount_actual
            elif getattr(line, 'discount', 0.0):
                disc = (line.price_unit * line.quantity) * (line.discount / 100.0)
            if disc and disc > 0:
                cols['disc'] = True
                cols['mrp'] = True

        return cols

    def _get_report_round_off(self):
        """ Return round off amount for report """
        self.ensure_one()
        val = 0.0
        if hasattr(self, 'amount_rounding') and self.amount_rounding is not False and abs(self.amount_rounding or 0.0) >= 0.005:
            val = self.amount_rounding
        elif self.tax_totals and isinstance(self.tax_totals, dict) and self.tax_totals.get('display_rounding'):
            val = self.tax_totals.get('rounding_amount', 0.0)
        else:
            round_lines = self.line_ids.filtered(lambda l: 'round' in (l.name or '').lower())
            if round_lines:
                net_bal = sum(l.debit - l.credit for l in round_lines)
                if abs(net_bal) >= 0.005:
                    val = -net_bal
            else:
                lines_sub = sum(l.price_subtotal for l in self.invoice_line_ids if l.display_type == 'product' or not l.display_type)
                tax = self.amount_tax or 0.0
                diff = self.amount_total - (lines_sub + tax)
                if abs(diff) >= 0.005:
                    val = diff
        return val if abs(val) >= 0.005 else 0.0

    def action_print_without_discount(self):
        """ Print jewellery invoice without MRP, Disc, and Total Disc columns """
        return self.env.ref('em_jewellery_management.action_report_invoice_without_discount').with_context(hide_discount=True).report_action(self, config=False)



