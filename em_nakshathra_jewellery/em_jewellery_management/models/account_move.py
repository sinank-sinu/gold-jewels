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
    custom_total = fields.Monetary(string="Paid to")
    is_paid = fields.Boolean(string="Is Paid")
    payment_to_id = fields.Many2one("account.payment",string="Payment ID")
    is_old_gold_bill = fields.Boolean(string="Is Old Gold Bill")
    unfix = fields.Boolean(string="Unfix", copy=False)
    vendor_bill_amount = fields.Monetary(
        string="PO Amount",
        compute='_compute_vendor_bill_amount',
        store=False,
    )

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
        return res

    def _compute_amount_one(self):
        """Perform totals computation of a move with global discounts."""
        deduction = self.old_gold_price or 0.0
        if self.unfix and self.move_type == 'out_invoice':
            deduction += self.vendor_bill_amount or 0.0
        
        if deduction:
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
        "old_gold_price"

    )
    def _compute_amount(self):
        """Modify totals computation for including global discounts."""
        res = super()._compute_amount()
        for record in self:
            if record.old_gold_price or (record.unfix and record.move_type == 'out_invoice'):
                record._compute_amount_one()
            if self.env.context.get('bypass_negative_total_check') and record.amount_total < 0:
                record.amount_total = 0.0
        return res

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
                ('company_id', '=', move.company_id.id)
            ], limit=1)

            if not journal:
                raise ValidationError(_("No bank/cash journal found."))

            payment = Payment.create({
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'partner_id': move.partner_id.id,
                'amount': amount,
                'journal_id': journal.id,
                'date': fields.Date.today(),
                'ref': move.name,
            })

            payment.action_post()
            if payment.state == 'posted':
                self.custom_total =0.0
                self.is_paid = True
                self.payment_to_id = payment.id


        return True
