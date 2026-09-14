# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CustomerPaymentWizard(models.TransientModel):
    _name = 'customer.payment.wizard'
    _description = 'Customer Payment Wizard'

    invoice_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        default=lambda self: self.env.context.get('default_invoice_id') or (
            self.env.context.get('active_model') == 'account.move' and self.env.context.get('active_id')
        ),
    )
    partner_id = fields.Many2one('res.partner', related='invoice_id.partner_id', string='Customer', readonly=True)
    company_id = fields.Many2one('res.company', related='invoice_id.company_id', string='Company', readonly=True)
    branch_id = fields.Many2one('res.branch', related='invoice_id.branch_id', string='Branch', readonly=True)

    amount = fields.Monetary(string='Amount to Pay', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        readonly=True
    )
    payment_date = fields.Date(string='Payment Date', required=True, default=fields.Date.context_today)
    communication = fields.Char(string='Memo / Reference')

    available_journal_ids = fields.Many2many(
        'account.journal',
        compute='_compute_available_journals',
        string='Available Journals'
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        required=True,
    )

    @api.depends('invoice_id', 'company_id', 'branch_id')
    def _compute_available_journals(self):
        for rec in self:
            company = rec.company_id or rec.invoice_id.company_id or self.env.company
            branch = rec.branch_id or (rec.invoice_id.branch_id if hasattr(rec.invoice_id, 'branch_id') else False)
            domain = [
                ('type', 'in', ('bank', 'cash')),
                ('company_id', '=', company.id),
                ('default_account_id', '!=', False),
            ]
            if branch:
                branch_journals = self.env['account.journal'].search(domain + [('branch_id', '=', branch.id)])
                if branch_journals:
                    rec.available_journal_ids = branch_journals
                else:
                    rec.available_journal_ids = self.env['account.journal'].search(
                        domain + ['|', ('branch_id', '=', branch.id), ('branch_id', '=', False)]
                    )
            else:
                rec.available_journal_ids = self.env['account.journal'].search(domain)
            if not rec.available_journal_ids:
                rec.available_journal_ids = self.env['account.journal'].search([
                    ('type', 'in', ('bank', 'cash')),
                    ('company_id', '=', company.id),
                ])

    @api.model
    def _get_default_journal_static(self, invoice):
        company = invoice.company_id if invoice and invoice.company_id else self.env.company
        branch = invoice.branch_id if invoice and hasattr(invoice, 'branch_id') and invoice.branch_id else False

        domain = [
            ('company_id', '=', company.id),
            ('type', 'in', ('cash', 'bank')),
            ('default_account_id', '!=', False),
        ]

        if branch:
            j = self.env['account.journal'].search(domain + [('branch_id', '=', branch.id), ('type', '=', 'cash')], limit=1)
            if j:
                return j
            j = self.env['account.journal'].search(domain + [('branch_id', '=', branch.id)], limit=1)
            if j:
                return j

        return self.env['account.journal'].search(domain, limit=1)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        invoice_id = self.env.context.get('default_invoice_id') or res.get('invoice_id') or (
            self.env.context.get('active_model') == 'account.move' and self.env.context.get('active_id')
        )
        if invoice_id:
            invoice = self.env['account.move'].browse(invoice_id)
            res['invoice_id'] = invoice.id
            if 'amount' in fields_list and not res.get('amount'):
                res['amount'] = abs(invoice.custom_total) if invoice.custom_total < 0 else abs(invoice.amount_total)
            if 'currency_id' in fields_list and not res.get('currency_id'):
                res['currency_id'] = invoice.currency_id.id
            if 'communication' in fields_list and not res.get('communication'):
                res['communication'] = invoice.name
            if 'journal_id' in fields_list and not res.get('journal_id'):
                default_j = self._get_default_journal_static(invoice)
                if default_j:
                    res['journal_id'] = default_j.id
        return res

    def action_confirm_payment(self):
        self.ensure_one()
        move = self.invoice_id
        if not move:
            raise UserError(_("No invoice linked to this payment."))
        if move.state != 'posted':
            raise UserError(_("Payment can only be created for posted invoices."))
        if not self.journal_id:
            raise UserError(_("Please select a journal to proceed with payment."))
        if self.amount <= 0:
            raise UserError(_("Payment amount must be greater than zero."))

        move.action_create_old_gold_vendor_payment(
            journal=self.journal_id,
            payment_date=self.payment_date,
            memo=self.communication,
            amount=self.amount,
        )

        return {'type': 'ir.actions.act_window_close'}
