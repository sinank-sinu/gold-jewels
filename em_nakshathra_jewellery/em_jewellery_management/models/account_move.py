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
        deduction = (self.old_gold_price or 0.0) + (self.sale_return_price or 0.0)
        if self.unfix and self.move_type == 'out_invoice':
            deduction += self.vendor_bill_amount or 0.0
        
        if deduction:
            self.custom_total = 0.0
            if self.amount_residual < deduction:
                self.custom_total = self.amount_residual - deduction
                self.amount_residual = 0.0
                self.payment_state = 'paid'
            else:
                self.amount_residual = self.amount_residual - deduction

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
        return super().action_post()



    def _post(self, soft=True):
        posted = super(AccountMove, self.with_context(bypass_negative_total_check=True))._post(soft)
        for move in posted:
            move.with_context(bypass_negative_total_check=False)._compute_amount()
        return posted

    def action_create_old_gold_vendor_payment(self):
        Payment = self.env['account.payment']

        for move in self:
            if move.custom_total >= 0 and move.amount_total >= 0:
                raise ValidationError(_("Invoice is not negative."))

            amount = abs(move.custom_total) if move.custom_total < 0 else abs(move.amount_total)

            journal = self.env['account.journal'].search([
                ('type', 'in', ('bank', 'cash')),
                ('company_id', '=', move.company_id.id),
                ('default_account_id', '!=', False)
            ], limit=1)
            
            if not journal:
                journal = self.env['account.journal'].search([
                    ('type', 'in', ('bank', 'cash')),
                    ('company_id', '=', move.company_id.id)
                ], limit=1)

            if not journal:
                raise ValidationError(_("No bank/cash journal found."))
            elif not journal.default_account_id:
                raise ValidationError(_("The selected journal '%s' is missing a Default Account. Please configure its accounts in Accounting settings to allow payments.") % journal.name)

            payable_line = move.line_ids.filtered(lambda l: l.display_type == 'payment_term' or l.account_type == 'liability_payable')
            destination_account_id = payable_line[0].account_id.id if payable_line else move.partner_id.with_company(move.company_id).property_account_payable_id.id
            
            payment = Payment.create({
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'partner_id': move.partner_id.id,
                'amount': amount,
                'journal_id': journal.id,
                'date': fields.Date.today(),
                'ref': move.name,
                'destination_account_id': destination_account_id,
            })
            
            # Force the outstanding account if Odoo's internal compute failed to find one
            if not payment.outstanding_account_id and journal.default_account_id:
                payment.outstanding_account_id = journal.default_account_id.id

            payment.action_post()
            if payment.state == 'posted':
                self.custom_total =0.0
                self.is_paid = True
                self.payment_to_id = payment.id


        return True
