from collections import defaultdict
from math import ceil
from odoo import models, api, fields, _, Command
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    amount_rounding = fields.Monetary(
        string="Round Off",
        currency_field='currency_id',
        default=0.0,
    )

    has_customer_payment = fields.Boolean(
        string="Has Customer Payment",
        compute="_compute_has_customer_payment",
    )

    @api.depends(
        'custom_total',
        'is_paid',
        'payment_to_id',
        'old_gold_price',
        'sale_return_price',
        'move_type',
        'amount_total',
        'unfix',
    )
    def _compute_has_customer_payment(self):
        for move in self:
            deduction = (move.old_gold_price or 0.0) + (move.sale_return_price or 0.0)
            if move.unfix and move.move_type == 'out_invoice':
                deduction += move.vendor_bill_amount or 0.0
            move.has_customer_payment = (
                move.move_type == 'out_invoice' and (
                    move.currency_id.compare_amounts(move.custom_total, 0.0) < 0
                    or move.is_paid
                    or bool(move.payment_to_id)
                    or (deduction > 0 and deduction > move.amount_total)
                )
            )

    def _get_cash_difference_account(self, is_gain):
        self.ensure_one()
        company = self.company_id
        if is_gain:
            account = company.default_cash_difference_income_account_id
            if not account:
                account = self.env['account.account'].search([
                    ('company_id', '=', company.id),
                    ('code', '=', '999001'),
                ], limit=1)
            if not account:
                account = self.env['account.account'].search([
                    ('company_id', '=', company.id),
                    ('name', 'ilike', 'Cash Difference Gain'),
                ], limit=1)
        else:
            account = company.default_cash_difference_expense_account_id
            if not account:
                account = self.env['account.account'].search([
                    ('company_id', '=', company.id),
                    ('code', '=', '999002'),
                ], limit=1)
            if not account:
                account = self.env['account.account'].search([
                    ('company_id', '=', company.id),
                    ('name', 'ilike', 'Cash Difference Loss'),
                ], limit=1)

        if not account:
            account_type = 'income_other' if is_gain else 'expense'
            account = self.env['account.account'].search([
                ('company_id', '=', company.id),
                ('account_type', '=', account_type),
            ], limit=1)

        if not account:
            raise UserError(
                _("Please configure the Cash Difference %s Account for company %s in Accounting Settings.",
                  _("Gain") if is_gain else _("Loss"), company.name)
            )
        return account

    def _recompute_cash_rounding_lines(self):
        ''' Override to handle manual amount_rounding when standard invoice_cash_rounding_id is not set. '''
        for move in self:
            if move.state == 'posted':
                continue

            if move.invoice_cash_rounding_id:
                super(AccountMove, move)._recompute_cash_rounding_lines()
                continue

            existing_cash_rounding_lines = move.line_ids.filtered(lambda line: line.display_type == 'rounding')

            if not move.amount_rounding or move.currency_id.is_zero(move.amount_rounding):
                existing_cash_rounding_lines.unlink()
                continue

            # In out_invoice (customer invoice):
            # amount_rounding < 0 (e.g. -42.00) reduces the invoice total -> Debit 42.00 (loss, balance > 0)
            # amount_rounding > 0 (e.g. +10.00) increases the invoice total -> Credit 10.00 (gain, balance < 0)
            sign = move.direction_sign
            diff_amount_currency = sign * move.amount_rounding
            if move.currency_id == move.company_id.currency_id:
                diff_balance = diff_amount_currency
            else:
                diff_balance = move.currency_id._convert(
                    diff_amount_currency,
                    move.company_id.currency_id,
                    move.company_id,
                    move.invoice_date or move.date or fields.Date.today()
                )

            if move.is_sale_document(include_receipts=True):
                is_gain = (move.amount_rounding > 0.0)
            else:
                is_gain = (move.amount_rounding < 0.0)

            account = move._get_cash_difference_account(is_gain=is_gain)

            # Check if an update is really needed to prevent unnecessary writes
            if len(existing_cash_rounding_lines) == 1:
                line = existing_cash_rounding_lines[0]
                if (
                        move.currency_id.compare_amounts(line.balance, diff_balance) == 0
                        and move.currency_id.compare_amounts(line.amount_currency, diff_amount_currency) == 0
                        and line.account_id == account
                ):
                    continue

            rounding_line_vals = {
                'name': _('Round Off'),
                'balance': diff_balance,
                'debit': diff_balance if diff_balance > 0.0 else 0.0,
                'credit': -diff_balance if diff_balance < 0.0 else 0.0,
                'amount_currency': diff_amount_currency,
                'partner_id': move.partner_id.id,
                'move_id': move.id,
                'currency_id': move.currency_id.id,
                'company_id': move.company_id.id,
                'company_currency_id': move.company_id.currency_id.id,
                'display_type': 'rounding',
                'account_id': account.id,
                'tax_ids': [Command.clear()],
            }

            if existing_cash_rounding_lines:
                first_line = existing_cash_rounding_lines[0]
                (existing_cash_rounding_lines - first_line).unlink()
                first_line.write(rounding_line_vals)
            else:
                if isinstance(move.id, models.NewId):
                    move.line_ids = [Command.create(rounding_line_vals)]
                else:
                    move.env['account.move.line'].create(rounding_line_vals)

    @api.onchange('amount_rounding')
    def _onchange_amount_rounding(self):
        for move in self:
            if move.state == 'draft':
                move._recompute_cash_rounding_lines()

            deduction = (move.old_gold_price or 0.0) + (move.sale_return_price or 0.0)
            if move.unfix and move.move_type == 'out_invoice':
                deduction += move.vendor_bill_amount or 0.0

            if deduction and not move.is_paid:
                base_total = sum(move.invoice_line_ids.mapped('price_total'))
                eff_tot = base_total + (move.amount_rounding or 0.0)
                if eff_tot < deduction:
                    move.custom_total = eff_tot - deduction
                    move.amount_residual = 0.0
                else:
                    move.amount_residual = eff_tot - deduction
                    move.custom_total = 0.0

            move._compute_tax_totals()

    # --- 1. Update Invoice Frontend Widget Totals ---
    @api.depends_context('lang')
    @api.depends(
        'invoice_line_ids.price_subtotal',
        'invoice_line_ids.tax_ids',
        'invoice_payment_term_id',
        'partner_id',
        'currency_id',
        'amount_rounding'
    )
    def _compute_tax_totals(self):
        # Calculate original totals first
        super()._compute_tax_totals()

        for move in self:
            if move.move_type not in ('out_invoice', 'in_invoice', 'out_refund', 'in_refund'):
                continue

            if not move.tax_totals:
                continue

            # Bypass modification if gold bullion rules apply
            has_gold_bullion = move.invoice_line_ids.filtered(
                lambda l: l.product_id.name == 'Gold Bullion'
            )
            if has_gold_bullion:
                continue

            # Ensure we are modifying a regular dict copy
            tax_totals = dict(move.tax_totals)
            original_total = tax_totals.get('amount_total', 0.0)

            # Simple logic: If no manual rounding value is provided, fallback to standard display
            if not move.amount_rounding:
                tax_totals['display_rounding'] = False
                move.tax_totals = tax_totals
                continue

            # Direct addition logic
            new_total = original_total + move.amount_rounding
            rounding_amount = move.amount_rounding

            # Format the data according to Odoo UI standards
            tax_totals['display_rounding'] = True
            tax_totals['rounding_amount'] = rounding_amount
            tax_totals['formatted_rounding_amount'] = (
                    move.currency_id.symbol + " %.2f" % rounding_amount
            )

            tax_totals['amount_total'] = new_total
            tax_totals['formatted_amount_total'] = move.currency_id.format(new_total)

            # Assign back the updated object to refresh the view layer
            move.tax_totals = tax_totals


    # --- 2. Update Invoice Backend Database Record Values (Total, Residual & Signed Fields) ---
    @api.depends(
        'invoice_line_ids.price_subtotal',
        'invoice_line_ids.tax_ids',
        'line_ids.amount_currency',
        'line_ids.balance',
        'amount_rounding'
    )
    def _compute_amount(self):
        # Calculate baseline amounts first (including amount_total and amount_residual)
        super()._compute_amount()

        for move in self:
            if move.move_type not in ('out_invoice', 'in_invoice', 'out_refund', 'in_refund'):
                continue

            if not move.amount_rounding:
                continue

            # Bypass modification if gold bullion rules apply
            has_gold_bullion = move.invoice_line_ids.filtered(
                lambda l: l.product_id.name == 'Gold Bullion'
            )
            if has_gold_bullion:
                continue

            # If a cash rounding line already exists in line_ids, standard Odoo's
            # super()._compute_amount() already factored it into amount_total and amount_residual.
            if move.line_ids.filtered(lambda l: l.display_type == 'rounding'):
                continue

            # Fallback if no rounding line exists
            sign = move.direction_sign
            move.amount_total = move.amount_total + move.amount_rounding
            move.amount_total_signed = move.amount_total_signed + (sign * move.amount_rounding)

            # Update the residual fields so the UI "Amount Due" matches perfectly
            has_deduction = bool(getattr(move, 'old_gold_price', 0.0) or getattr(move, 'sale_return_price', 0.0) or (getattr(move, 'unfix', False) and move.move_type == 'out_invoice'))
            if not has_deduction and not move.currency_id.is_zero(move.amount_residual) and move.payment_state != 'paid':
                move.amount_residual = move.amount_residual + move.amount_rounding
                move.amount_residual_signed = move.amount_residual_signed + (sign * move.amount_rounding)
                if move.currency_id.is_zero(move.amount_residual):
                    move.amount_residual = 0.0
                    move.amount_residual_signed = 0.0
                    move.payment_state = 'paid'

        for move in self:
            if hasattr(move, '_compute_amount_one'):
                move._compute_amount_one()

    def _update_posted_cash_rounding(self, new_rounding):
        self.ensure_one()
        rounding_lines = self.line_ids.filtered(lambda l: l.display_type == 'rounding')
        sign = self.direction_sign
        diff_amount_currency = sign * new_rounding
        if self.currency_id == self.company_id.currency_id:
            diff_balance = diff_amount_currency
        else:
            diff_balance = self.currency_id._convert(
                diff_amount_currency,
                self.company_id.currency_id,
                self.company_id,
                self.invoice_date or self.date or fields.Date.today()
            )

        if not new_rounding or self.currency_id.is_zero(new_rounding):
            if rounding_lines:
                rounding_lines.with_context(check_move_validity=False).write({
                    'balance': 0.0,
                    'debit': 0.0,
                    'credit': 0.0,
                    'amount_currency': 0.0,
                })
            diff_balance = 0.0
            diff_amount_currency = 0.0
        else:
            if self.is_sale_document(include_receipts=True):
                is_gain = (new_rounding > 0.0)
            else:
                is_gain = (new_rounding < 0.0)
            account = self._get_cash_difference_account(is_gain=is_gain)
            rounding_vals = {
                'name': _('Round Off'),
                'balance': diff_balance,
                'debit': diff_balance if diff_balance > 0.0 else 0.0,
                'credit': -diff_balance if diff_balance < 0.0 else 0.0,
                'amount_currency': diff_amount_currency,
                'account_id': account.id,
            }
            if rounding_lines:
                first_line = rounding_lines[0]
                first_line.with_context(check_move_validity=False).write(rounding_vals)
                if len(rounding_lines) > 1:
                    (rounding_lines - first_line).with_context(check_move_validity=False).write({
                        'balance': 0.0,
                        'debit': 0.0,
                        'credit': 0.0,
                        'amount_currency': 0.0,
                    })
            else:
                create_vals = {
                    **rounding_vals,
                    'partner_id': self.partner_id.id,
                    'move_id': self.id,
                    'currency_id': self.currency_id.id,
                    'company_id': self.company_id.id,
                    'company_currency_id': self.company_id.currency_id.id,
                    'display_type': 'rounding',
                }
                self.env['account.move.line'].with_context(check_move_validity=False).create(create_vals)

        term_lines = self.line_ids.filtered(lambda l: l.display_type == 'payment_term')
        if not term_lines:
            term_lines = self.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable'))
        if term_lines:
            other_lines = self.line_ids.filtered(lambda l: l not in term_lines and l.display_type != 'rounding')
            other_balance = sum(other_lines.mapped('balance'))
            new_term_balance = -(other_balance + diff_balance)
            term_vals = {
                'balance': new_term_balance,
                'debit': new_term_balance if new_term_balance > 0.0 else 0.0,
                'credit': -new_term_balance if new_term_balance < 0.0 else 0.0,
            }
            if self.currency_id == self.company_id.currency_id:
                term_vals['amount_currency'] = new_term_balance
            else:
                term_sign = -self.direction_sign
                term_vals['amount_currency'] = term_sign * (abs(sum(self.invoice_line_ids.mapped('price_total'))) + new_rounding)
            term_lines[0].with_context(check_move_validity=False).write(term_vals)

        self._compute_tax_totals()
        self._compute_amount()
        if hasattr(self, '_compute_amount_one'):
            self._compute_amount_one()

    def write(self, vals):
        res = super().write(vals)
        if 'amount_rounding' in vals:
            for move in self:
                if move.state == 'posted' and move.has_customer_payment and not move.is_paid:
                    move._update_posted_cash_rounding(vals['amount_rounding'])
        return res

    has_outstanding_scheme_payment = fields.Boolean(
        string="Has Outstanding Scheme Payment",
        compute="_compute_has_outstanding_scheme_payment"
    )

    def _get_outstanding_scheme_payment_lines(self):
        self.ensure_one()
        if self.state != 'posted' or self.move_type != 'out_invoice':
            return self.env['account.move.line']

        pay_term_lines = self.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_receivable')
        if not pay_term_lines:
            return self.env['account.move.line']

        domain = [
            ('account_id', 'in', pay_term_lines.account_id.ids),
            ('parent_state', '=', 'posted'),
            ('partner_id', '=', self.commercial_partner_id.id),
            ('reconciled', '=', False),
            ('balance', '<', 0.0),
            '|', ('amount_residual', '!=', 0.0), ('amount_residual_currency', '!=', 0.0),
        ]

        other_companies = self.env['res.company'].sudo().search([('id', '!=', self.company_id.id)])
        other_company_names = other_companies.mapped('name')

        lines = self.env['account.move.line'].search(domain)
        scheme_lines = self.env['account.move.line']
        for line in lines:
            # Check if this line is linked to a scheme installment
            installment = self.env['jewellery.scheme.installment'].search([('move_id', '=', line.move_id.id)], limit=1)
            if installment:
                scheme_lines |= line
                continue

            # Fallback string check
            ref = line.ref or ''
            name = line.name or ''
            move_name = line.move_id.name or ''
            if any(term in ref or term in name or term in move_name
                   for term in ['Scheme Payment', 'Scheme Transfer', 'Scheme Installment', 'Scheme Redemption']):
                scheme_lines |= line
                continue

            # Cross-company check
            if any(comp_name == ref or comp_name == name for comp_name in other_company_names):
                scheme_lines |= line

        return scheme_lines

    @api.depends('invoice_outstanding_credits_debits_widget', 'state', 'partner_id', 'payment_state')
    def _compute_has_outstanding_scheme_payment(self):
        for move in self:
            if move.state == 'posted' and move.move_type == 'out_invoice' and move.payment_state not in ('paid', 'in_payment'):
                scheme_lines = move._get_outstanding_scheme_payment_lines()
                move.has_outstanding_scheme_payment = bool(scheme_lines)
            else:
                move.has_outstanding_scheme_payment = False

    scheme_balance_to_pay_customer = fields.Float(
        string="Scheme Balance to Pay", 
        compute="_compute_scheme_balance_to_pay_customer"
    )

    @api.depends('state', 'partner_id', 'payment_state', 'invoice_outstanding_credits_debits_widget')
    def _compute_scheme_balance_to_pay_customer(self):
        for move in self:
            if move.state == 'posted' and move.move_type == 'out_invoice':
                scheme_lines = move._get_outstanding_scheme_payment_lines()
                total = 0.0
                for l in scheme_lines:
                    if l.currency_id and l.currency_id == move.currency_id:
                        total += abs(l.amount_residual_currency)
                    else:
                        total += abs(l.amount_residual)
                move.scheme_balance_to_pay_customer = total
            else:
                move.scheme_balance_to_pay_customer = 0.0

    def action_pay_scheme_balance_to_customer(self):
        self.ensure_one()
        return {
            'name': 'Customer Payment',
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'form',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_payment_type': 'outbound',
                'default_partner_type': 'customer',
                'default_amount': self.scheme_balance_to_pay_customer,
                'default_is_scheme_refund': True,
                'default_scheme_refund_invoice_id': self.id,
            },
            'target': 'new',
        }

    def action_redeem_outstanding_schemes(self):
        self.ensure_one()
        scheme_lines = self._get_outstanding_scheme_payment_lines()
        if not scheme_lines:
            raise UserError(_("No outstanding scheme payment credits found for this customer."))

        for line in scheme_lines:
            # 1. Reconcile this line against the invoice
            invoice_receivable_lines = self.line_ids.filtered(
                lambda l: l.account_id == line.account_id and not l.reconciled
            )
            if invoice_receivable_lines:
                (line + invoice_receivable_lines).reconcile()

            # 2. Find the corresponding scheme enrollment(s) to mark as redeemed
            enrollments = self.env['jewellery.scheme.enrollment']
            installment = self.env['jewellery.scheme.installment'].search([('move_id', '=', line.move_id.id)])
            if installment:
                enrollments |= installment.mapped('enrollment_id')

            # Fallback: matching text in the ref / name / move name
            if not enrollments:
                partner_schemes = self.env['jewellery.scheme.enrollment'].search([
                    ('partner_id', '=', self.partner_id.id),
                    ('state', 'in', ('running', 'completed')),
                    ('is_redeemed', '=', False)
                ])
                ref = line.ref or ''
                name = line.name or ''
                move_name = line.move_id.name or ''
                for scheme in partner_schemes:
                    if (scheme.name and (scheme.name in ref or scheme.name in name or scheme.name in move_name)) or \
                       (scheme.ticket_number and (scheme.ticket_number in ref or scheme.ticket_number in name or scheme.ticket_number in move_name)):
                        enrollments |= scheme

                # Fallback: if there is only one running/completed scheme for the customer, use that
                if not enrollments and len(partner_schemes) == 1:
                    enrollments |= partner_schemes[0]

            # 3. Mark scheme as redeemed and create scheme.redemption record
            for scheme in enrollments:
                scheme.write({
                    'state': 'redeemed',
                    'is_redeemed': True,
                })
                # Find sale order
                sale_orders = self.invoice_line_ids.mapped('sale_line_ids.order_id')
                sale_order = sale_orders[0] if sale_orders else self.env['sale.order']

                # Create redemption record if it doesn't exist (only if sale_order exists)
                if sale_order:
                    existing_redemption = self.env['scheme.redemption'].search([
                        ('scheme_id', '=', scheme.id),
                        ('sale_order_id', '=', sale_order.id)
                    ], limit=1)

                    if not existing_redemption:
                        self.env['scheme.redemption'].sudo().create({
                            'scheme_id': scheme.id,
                            'sale_order_id': sale_order.id,
                            'amount': scheme.total_paid,
                            'date': sale_order.date_order.date() if sale_order and sale_order.date_order else fields.Date.today(),
                        })
                        if not sale_order.active_scheme_id:
                            sale_order.sudo().write({'active_scheme_id': scheme.id})

        return True

    def action_post(self):
        for move in self:
            if move.state == 'draft' and move.amount_rounding and not move.invoice_cash_rounding_id:
                move._recompute_cash_rounding_lines()
        res = super().action_post()
        for move in self:
            if move.move_type == 'out_invoice':
                # Check if any associated sale order has apply_scheme = True
                sale_orders = move.invoice_line_ids.mapped('sale_line_ids.order_id')
                if any(so.apply_scheme for so in sale_orders):
                    all_potential_schemes = self.env['jewellery.scheme.enrollment'].sudo().search([
                        ('partner_id', '=', move.partner_id.id),
                        ('state', 'in', ('running', 'completed')),
                        ('is_redeemed', '=', False),
                        '|', ('branch_id.company_id', '!=', move.company_id.id),
                             ('branch_id', '=', False),
                    ])

                    other_company_schemes = self.env['jewellery.scheme.enrollment'].sudo()
                    company_schemes = defaultdict(list)

                    for scheme in all_potential_schemes:
                        comp = scheme.branch_id.company_id
                        if not comp and scheme.scheme_line_ids:
                            paid_lines = scheme.scheme_line_ids.filtered(lambda l: l.state == 'paid' and l.move_id)
                            if paid_lines:
                                comp = paid_lines[0].move_id.company_id

                        if comp and comp.id != move.company_id.id:
                            other_company_schemes |= scheme
                            company_schemes[comp].append(scheme)

                    if other_company_schemes:

                        sale_order = sale_orders[0] if sale_orders else False
                        entry_date = fields.Date.to_date(sale_order.date_order) if sale_order and sale_order.date_order else fields.Date.today()

                        for comp, schemes in company_schemes.items():
                            total_amount = sum(s.total_paid for s in schemes)
                            if total_amount <= 0:
                                continue

                            # 1. Find bank/cash or general journal in current company
                            journal = self.env['account.journal'].search([
                                ('company_id', '=', move.company_id.id),
                                ('type', 'in', ('bank', 'cash'))
                            ], limit=1)
                            if not journal:
                                journal = self.env['account.journal'].search([
                                    ('company_id', '=', move.company_id.id),
                                    '|', ('name', 'ilike', 'suspense'), ('name', 'ilike', 'suspence')
                                ], limit=1)
                            if not journal:
                                journal = self.env['account.journal'].search([
                                    ('company_id', '=', move.company_id.id),
                                    ('type', '=', 'general')
                                ], limit=1)
                            if not journal:
                                raise UserError(_("No journal found in the current company."))

                            # 2. Find Outstanding Receipts account
                            outstanding_receipts_account = self.env['account.account'].search([
                                ('company_id', '=', move.company_id.id),
                                ('code', '=', '100203')
                            ], limit=1)
                            if not outstanding_receipts_account:
                                outstanding_receipts_account = self.env['account.account'].search([
                                    ('company_id', '=', move.company_id.id),
                                    '|', ('name', 'ilike', 'Outstanding Receipt'), ('name', 'ilike', 'Outstanding Reciept')
                                ], limit=1)
                            if not outstanding_receipts_account and journal:
                                pay_method_lines = journal.inbound_payment_method_line_ids.filtered(lambda l: l.payment_account_id)
                                if pay_method_lines:
                                    outstanding_receipts_account = pay_method_lines[0].payment_account_id
                            if not outstanding_receipts_account and journal:
                                outstanding_receipts_account = journal.suspense_account_id or journal.default_account_id
                            if not outstanding_receipts_account:
                                outstanding_receipts_account = self.env['account.account'].search([
                                    ('company_id', '=', move.company_id.id),
                                    ('code', '=', '100202')
                                ], limit=1)
                            if not outstanding_receipts_account:
                                outstanding_receipts_account = self.env['account.account'].search([
                                    ('company_id', '=', move.company_id.id),
                                    ('name', 'ilike', 'Bank Suspense Account')
                                ], limit=1)
                            if not outstanding_receipts_account:
                                outstanding_receipts_account = self.env['account.account'].search([
                                    ('company_id', '=', move.company_id.id)
                                ], limit=1)
                            if not outstanding_receipts_account:
                                raise UserError(_("Outstanding Receipts account not found in the current company."))

                            # 3. Find debtors/receivable account
                            debtors_account = self.env['account.account'].search([
                                ('company_id', '=', move.company_id.id),
                                ('code', '=', '100400')
                            ], limit=1)
                            if not debtors_account:
                                debtors_account = self.env['account.account'].search([
                                    ('company_id', '=', move.company_id.id),
                                    ('name', 'ilike', 'Debtors')
                                ], limit=1)
                            if not debtors_account:
                                debtors_account = self.env['account.account'].search([
                                    ('company_id', '=', move.company_id.id),
                                    ('account_type', '=', 'asset_receivable')
                                ], limit=1)
                            if not debtors_account:
                                pay_term_lines = move.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_receivable')
                                if pay_term_lines:
                                    debtors_account = pay_term_lines[0].account_id
                            if not debtors_account:
                                debtors_account = move.partner_id.with_company(move.company_id).property_account_receivable_id
                            if not debtors_account:
                                raise UserError(_("Debtors/Receivable account not found in the current company."))

                            # 4. Create draft entry
                            label = comp.name
                            move_vals = {
                                'journal_id': journal.id,
                                'date': entry_date,
                                'ref': label,
                                'company_id': move.company_id.id,
                                'partner_id': move.partner_id.id,
                                'branch_id': move.branch_id.id if hasattr(move, 'branch_id') and move.branch_id else False,
                                'line_ids': [
                                    (0, 0, {
                                        'account_id': outstanding_receipts_account.id,
                                        'partner_id': move.partner_id.id,
                                        'name': f"Scheme Payment - {label}",
                                        'debit': total_amount,
                                        'credit': 0.0,
                                    }),
                                    (0, 0, {
                                        'account_id': debtors_account.id,
                                        'partner_id': move.partner_id.id,
                                        'name': f"Scheme Payment - {label}",
                                        'debit': 0.0,
                                        'credit': total_amount,
                                    })
                                ]
                            }

                            new_move = self.env['account.move'].with_context(
                                default_move_type='entry',
                                default_journal_id=journal.id,
                            ).create(move_vals)
                            new_move.action_post()

                            # 5. Create another journal entry in the SAME company (move.company_id.id)
                            # Find partner named as the scheme's country name
                            scheme_country_name = comp.country_id.name or ''
                            other_partner = self.env['res.partner'].sudo().search([('name', '=', scheme_country_name)], limit=1)
                            if not other_partner:
                                other_partner = self.env['res.partner'].sudo().search([('name', '=', comp.name)], limit=1) or comp.partner_id

                            other_label = ", ".join(filter(None, [s.name for s in schemes])) or comp.name
                            other_move_vals = {
                                'journal_id': journal.id,
                                'date': entry_date,
                                'ref': other_label,
                                'company_id': move.company_id.id,
                                'partner_id': other_partner.id,
                                'branch_id': move.branch_id.id if hasattr(move, 'branch_id') and move.branch_id else False,
                                'line_ids': [
                                    (0, 0, {
                                        'account_id': debtors_account.id,
                                        'partner_id': other_partner.id,
                                        'name': other_label,
                                        'debit': total_amount,
                                        'credit': 0.0,
                                    }),
                                    (0, 0, {
                                        'account_id': outstanding_receipts_account.id,
                                        'partner_id': other_partner.id,
                                        'name': other_label,
                                        'debit': 0.0,
                                        'credit': total_amount,
                                    })
                                ]
                            }
                            other_new_move = self.env['account.move'].with_context(
                                default_move_type='entry',
                                default_journal_id=journal.id,
                            ).create(other_move_vals)
                            other_new_move.action_post()

                           
                    return res


# from math import ceil
# from odoo import models, api, fields


# class AccountMove(models.Model):
#     _inherit = 'account.move'

#     amount_rounding = fields.Monetary(
#         string="Round Off",
#         currency_field='currency_id',
#         default=0.0,
#     )

#     @api.depends_context('lang')
#     @api.depends('invoice_line_ids.price_subtotal','invoice_line_ids.tax_ids','invoice_payment_term_id','partner_id','currency_id','amount_rounding')
#     def _compute_tax_totals(self):
#         super()._compute_tax_totals()

#         for move in self:

#             if move.move_type != 'out_invoice':
#                 continue

#             if not move.tax_totals:
#                 continue

#             has_gold_bullion = move.invoice_line_ids.filtered(
#                 lambda l: l.product_id.name == 'Gold Bullion'
#             )

#             if has_gold_bullion:
#                 continue

#             tax_totals = dict(move.tax_totals)

#             original_total = tax_totals.get('amount_total', 0.0)

#             if not move.amount_rounding:
#                 tax_totals['display_rounding'] = False
#                 move.tax_totals = tax_totals
#                 continue

#             adjusted_total = original_total + move.amount_rounding

#             rounded_total = ceil(adjusted_total / 100.0) * 100

#             rounding_amount = rounded_total - original_total

#             tax_totals['display_rounding'] = True
#             tax_totals['rounding_amount'] = rounding_amount
#             tax_totals['formatted_rounding_amount'] = (
#                 move.currency_id.symbol + " %.2f" % rounding_amount
#             )

#             tax_totals['amount_total'] = rounded_total
#             tax_totals['formatted_amount_total'] = (
#                 move.currency_id.symbol + " %.2f" % rounded_total
#             )

#             move.tax_totals = tax_totals

#     @api.depends('invoice_line_ids.price_subtotal','invoice_line_ids.tax_ids','line_ids.amount_currency','line_ids.balance','amount_rounding')
#     def _compute_amount(self):
#         super()._compute_amount()

#         for move in self:

#             if move.move_type != 'out_invoice':
#                 continue

#             if not move.amount_rounding:
#                 continue

#             has_gold_bullion = move.invoice_line_ids.filtered(
#                 lambda l: l.product_id.name == 'Gold Bullion'
#             )

#             if has_gold_bullion:
#                 continue

#             adjusted_total = move.amount_total + move.amount_rounding

#             move.amount_total = ceil(adjusted_total / 100.0) * 100

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    is_scheme_refund = fields.Boolean(string="Is Scheme Refund")
    scheme_refund_invoice_id = fields.Many2one('account.move', string="Refund Invoice")

    def action_post(self):
        res = super().action_post()
        for payment in self:
            if payment.is_scheme_refund and payment.scheme_refund_invoice_id:
                scheme_lines = payment.scheme_refund_invoice_id._get_outstanding_scheme_payment_lines()
                payment_line = payment.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'asset_receivable' and l.debit > 0
                )
                if scheme_lines and payment_line:
                    (scheme_lines + payment_line).reconcile()
        return res


