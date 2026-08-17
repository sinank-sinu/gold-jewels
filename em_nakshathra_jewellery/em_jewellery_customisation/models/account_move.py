from collections import defaultdict
from math import ceil
from odoo import models, api, fields, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    amount_rounding = fields.Monetary(
        string="Round Off",
        currency_field='currency_id',
        default=0.0,
    )

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
            if move.move_type != 'out_invoice':
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
            if move.move_type != 'out_invoice':
                continue

            if not move.amount_rounding:
                continue

            # Bypass modification if gold bullion rules apply
            has_gold_bullion = move.invoice_line_ids.filtered(
                lambda l: l.product_id.name == 'Gold Bullion'
            )
            if has_gold_bullion:
                continue

            # Update the master total fields (Both normal and company-currency signed version)
            move.amount_total = move.amount_total + move.amount_rounding
            move.amount_total_signed = move.amount_total_signed + move.amount_rounding

            # Update the residual fields so the UI "Amount Due" matches perfectly
            move.amount_residual = move.amount_residual + move.amount_rounding
            move.amount_residual_signed = move.amount_residual_signed + move.amount_rounding
            # move.amount_total_in_currency_signed = move.amount_total_in_currency_signed + move.amount_rounding

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
                        self.env['scheme.redemption'].create({
                            'scheme_id': scheme.id,
                            'sale_order_id': sale_order.id,
                            'amount': abs(line.amount_residual or line.balance),
                            'date': sale_order.date_order.date() if sale_order and sale_order.date_order else fields.Date.today(),
                        })
        return True

    def action_post(self):
        res = super().action_post()
        for move in self:
            if move.move_type == 'out_invoice':
                # Automatically redeem schemes if possible
                try:
                    all_company_ids = self.env['res.company'].sudo().search([]).ids
                    move_sudo = move.sudo().with_context(allowed_company_ids=all_company_ids)
                    if move_sudo._get_outstanding_scheme_payment_lines():
                        move_sudo.action_redeem_outstanding_schemes()
                except Exception as e:
                    pass

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
                                'date': sale_order.date_order.date(),
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

                            for scheme in schemes:
                                scheme.write({
                                    'state': 'redeemed',
                                    'is_redeemed': True,
                                })
                                if sale_order:
                                    self.env['scheme.redemption'].sudo().create({
                                        'scheme_id': scheme.id,
                                        'sale_order_id': sale_order.id,
                                        'amount': scheme.total_paid,
                                        'date': sale_order.date_order.date() if sale_order and sale_order.date_order else fields.Date.today(),
                                    })
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


