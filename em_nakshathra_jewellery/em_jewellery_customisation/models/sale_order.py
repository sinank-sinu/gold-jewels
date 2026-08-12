from collections import defaultdict
from math import ceil
from odoo import models, fields,api,_
from odoo.exceptions import UserError, ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    amount_rounding = fields.Monetary(
        string="Round Off",
        currency_field='currency_id',
        default=0.0,
        store=True,
    )
    # amount_rounding = fields.Char(string="Amount Rounding")
    cash_rounding_id = fields.Many2one('account.cash.rounding')
    # round_off_amount = fields.Monetary(string="Round Off", compute="_compute_round_off")
    has_gold_bullion = fields.Boolean(
        compute="_compute_has_gold_bullion",
        store=True,
    )


    @api.depends('order_line.product_id')
    def _compute_has_gold_bullion(self):
        for order in self:
            order.has_gold_bullion = any(
                line.product_template_id.name == 'Gold Bullion'
                for line in order.order_line
            )

    def _get_customer_scheme_records(self):
        self.ensure_one()
        return self.env['jewellery.scheme.enrollment'].search([
                ('partner_id', '=', self.partner_id.id),
                ('active', '=', True),
                ('state', 'in', ('running', 'completed')),
            ])

    def action_apply_scheme(self):
        for order in self:
            if not order.partner_id:
                raise UserError(_("Select customer first."))

            # Prevent duplicate apply
            if order.scheme_line_id:
                raise UserError(_("Scheme already applied."))

            completed_schemes = order._get_customer_scheme_records().filtered(
                lambda s: s.state in ('running', 'completed') and not s.is_redeemed
            )

            if order.apply_scheme and completed_schemes:

                # pick lowest priority
                completed_schemes = order._get_customer_scheme_records().filtered(
                    lambda s: s.state in ('running', 'completed') and not s.is_redeemed
                ).sorted(key=lambda s: (s.priority, s.create_date))
            
                if not completed_schemes:
                    raise UserError(_("No active scheme available for this customer."))
                
                # Take latest / first scheme
                scheme = completed_schemes[0]
               
                scheme_amount = scheme.total_paid

                if scheme_amount <= 0:
                    raise UserError(_("Invalid scheme amount."))

                quotation_total = order.amount_total

                if quotation_total <= 0:
                    raise UserError(_("Quotation total is zero."))

                if quotation_total < scheme_amount:
                    raise UserError(_("Cannot apply scheme. The purchase amount (%.2f) must be equal to or greater than the scheme amount (%.2f).") % (quotation_total, scheme_amount))

                redeem_amount = min(quotation_total, scheme_amount)

                product_code = f"SCHEME-{scheme.id}"

                product = self.env['product.product'].search([
                    ('default_code', '=', product_code)
                ], limit=1)

                if not product:
                    product = self.env['product.product'].create({
                        'name': f"{scheme.name} - {order.partner_id.name}",
                        'default_code': product_code,
                        'type': 'service',
                        'list_price': 0.0,
                    })


                line = self.env['sale.order.line'].create({
                    'order_id': order.id,
                    'product_id': product.id,
                    'product_uom_qty': 1,
                    'product_uom': product.uom_id.id,
                    'name': f"{product.name} (Scheme Redemption)",
                    'is_scheme_line': True,
                    'price_unit': -redeem_amount,
                    'price_subtotal': -redeem_amount,
                })
                order.scheme_line_id = line
                scheme.write({
                    'state': 'redeemed',
                    'is_redeemed': True, 
                })
                self.env['scheme.redemption'].create({
                    'scheme_id': scheme.id,
                    'sale_order_id': order.id,
                    'amount': redeem_amount,
                })

            # else:
            #     schemes = order._get_customer_scheme_records()

            #     if not schemes:
            #         raise UserError(_("No active scheme available for this customer."))

            #     total_mc = sum(order.order_line.mapped('mc_amount'))

            #     if total_mc <= 0:
            #         raise UserError(_("No Making Charge found to apply scheme."))

            #     scheme_product = order._get_scheme_product()
               
            #     line = self.env['sale.order.line'].create({
            #         'order_id': order.id,
            #         'product_id': scheme_product.id,
            #         'product_uom_qty': 1,
            #         'product_uom': scheme_product.uom_id.id,
            #         'name': f"{scheme_product.name} (MC Discount)",
            #         'is_scheme_line': True,
            #         'price_unit': -total_mc,
            #         'price_subtotal': -total_mc,
            #     })

            #     order.scheme_line_id = line

            #     # deactivate schemes
            #     schemes.write({'active': False})

            #     # zero out MC
            #     for ol in order.order_line:
            #         if hasattr(ol, 'mc_amount') and ol.mc_amount > 0:
            #             ol.mc_amount = 0


  
    def _prepare_invoice(self):
        vals = super()._prepare_invoice()

        vals.update({
            'amount_rounding': self.amount_rounding,
        })
        return vals



    # --- 1. Update Frontend Widget Totals ---
    @api.depends_context('lang')
    @api.depends(
        'order_line.tax_id',
        'order_line.price_unit',
        'amount_total',
        'amount_untaxed',
        'amount_rounding'
    )
    def _compute_tax_totals(self):
        # Calculate original totals first
        super()._compute_tax_totals()

        for order in self:
            if not order.tax_totals:
                continue

            # Bypass modification if gold bullion rules apply
            if order.has_gold_bullion:
                continue

            # Ensure we are modifying a regular dict copy
            tax_totals = dict(order.tax_totals)
            original_total = tax_totals.get('amount_total', 0.0)

            # Simple logic: If no manual rounding value is provided, fallback to standard display
            if not order.amount_rounding:
                tax_totals['display_rounding'] = False
                order.tax_totals = tax_totals
                continue

            # NEW REQUIREMENT: Direct addition without the 'ceil to 100' logic
            new_total = original_total + order.amount_rounding
            rounding_amount = order.amount_rounding

            # Format the data according to Odoo UI standards
            tax_totals['display_rounding'] = True
            tax_totals['rounding_amount'] = rounding_amount
            tax_totals['formatted_rounding_amount'] = (order.currency_id.symbol + " %.2f" % rounding_amount)

            tax_totals['amount_total'] = new_total
            tax_totals['formatted_amount_total'] = order.currency_id.format(new_total)
            

            # Assign back the updated object to refresh the view layer
            order.tax_totals = tax_totals


    @api.depends(
        'order_line.price_total',
        'order_line.price_tax',
        'amount_rounding'
    )
    def _compute_amounts(self):
        # Calculate baseline amounts first
        super()._compute_amounts()
        
        for order in self:
            if order.has_gold_bullion:
                continue
            
            if not order.amount_rounding:
                continue
            
            # Directly append your entered amount to the master record total
            order.amount_total = order.amount_total + order.amount_rounding


    # @api.depends_context('lang')
    # @api.depends(
    #     'order_line.tax_id',
    #     'order_line.price_unit',
    #     'amount_total',
    #     'amount_untaxed',
    #     'amount_rounding'
    # )
    # def _compute_tax_totals(self):
    #     super()._compute_tax_totals()

    #     for order in self:
    #         if not order.tax_totals:
    #             continue

    #         if order.has_gold_bullion:
    #             continue

    #         tax_totals = dict(order.tax_totals)

    #         original_total = tax_totals.get('amount_total', 0.0)

    #         # User has not entered Round Off
    #         if not order.amount_rounding:
    #             tax_totals['display_rounding'] = False
    #             order.tax_totals = tax_totals
    #             continue
    #         # adjusted_total = original_total + order.amount_rounding
    #         # rounded_total = ceil(adjusted_total / 100.0) * 100
    #         # rounding_amount = rounded_total - adjusted_total
    #         adjusted_total = original_total + order.amount_rounding
    #         rounded_total = ceil(adjusted_total / 100.0) * 100
    #         rounding_amount = rounded_total - original_total

    #         tax_totals['display_rounding'] = True
    #         tax_totals['rounding_amount'] = rounding_amount
    #         tax_totals['formatted_rounding_amount'] = (
    #             order.currency_id.symbol + " %.2f" % rounding_amount
    #         )

    #         tax_totals['amount_total'] = rounded_total
    #         tax_totals['formatted_amount_total'] = (
    #             order.currency_id.symbol + " %.2f" % rounded_total
    #         )
    #         order.tax_totals = tax_totals

    # @api.depends(
    #     'order_line.price_total',
    #     'order_line.price_tax',
    #     'amount_rounding'
    # )
    # def _compute_amounts(self):
    #     super()._compute_amounts()
    #     for order in self:
    #         if order.has_gold_bullion:
    #             continue
    #         # No manual round off entered
    #         if not order.amount_rounding:
    #             continue
    #         original_total = order.amount_total
    #         adjusted_total = original_total + order.amount_rounding
    #         rounded_total = ceil(adjusted_total / 100.0) * 100
    #         order.amount_total = rounded_total

    scheme_enrollment_id = fields.Many2one(
        'jewellery.scheme.enrollment',
        string='Scheme',
        copy=False,
    )

    scheme_redeemed = fields.Boolean(
        string='Scheme Redeemed',
        default=False,
        copy=False,
        readonly=True,
    )

    scheme_redemption_move_id = fields.Many2one(
        'account.move',
        string='Scheme Redemption Entry',
        copy=False,
        readonly=True,
    )

    def action_confirm(self):
        res = super().action_confirm()

        for order in self:
            # if order.scheme_enrollment_id and not order.scheme_redeemed:
                order._create_scheme_multicompany_entries()

        return res

    def _create_scheme_multicompany_entries(self):
        self.ensure_one()

        scheme = self.scheme_enrollment_id
        # if not scheme:
        #     return

        customer = self.partner_id
        current_company = self.company_id
        amount_by_company = {}

        # Read existing paid scheme installments. The payment company
        # is taken directly from the existing installment move.
        installments = self.env['jewellery.scheme.installment'].sudo().search([
            ('enrollment_id', '=', 64603),
            ('state', '=', 'paid'),
            ('move_id', '!=', False),
        ])

        for installment in installments:
            payment_company = installment.move_id.company_id
            amount_by_company[payment_company.id] = (
                amount_by_company.get(payment_company.id, 0.0)
                + installment.amount
            )
            print(payment_company)

        # Only create settlement entries for companies other than
        # the company in which the sale is being confirmed.
        for company_id, amount in amount_by_company.items():
            payment_company = self.env['res.company'].browse(company_id)

            if payment_company.id == current_company.id:
                continue

            # =========================================================
            # ENTRY 1 - CURRENT / SALE COMPANY
            #
            # Debtor account              Dr
            #     Partner = CURRENT COMPANY
            #
            # Outstanding account         Cr
            #     Partner = SALE ORDER CUSTOMER
            # =========================================================

            debtor_account = self.env['account.account'].with_company(
                current_company
            ).sudo().search([
                ('company_id', '=', current_company.id),
                ('name', '=', 'Debtors'),
            ], limit=1)


            journal = self.env['account.journal'].with_company(
                current_company
            ).sudo().search([
                ('company_id', '=', current_company.id),
                ('type', '=', 'general'),
            ], limit=1)
            outstanding_account = self.env['account.account'].with_company(
                current_company
            ).sudo().search([
                ('company_id', '=', current_company.id),
                ('name', '=', 'Outstanding Receipts'),
            ], limit=1)


            move_vals = {
                'company_id': current_company.id,
                'journal_id': journal.id,
                'date': fields.Date.context_today(self),
                'ref': 'Scheme Redemption - %s' % scheme.display_name,
                'line_ids': [
                    (0, 0, {
                        'account_id': debtor_account.id,
                        'partner_id':  customer.id,
                        'name': 'Scheme Debtor - %s' % payment_company.name,
                        'debit': 0.0,
                        'credit': amount,
                    }),
                    (0, 0, {
                        'account_id': outstanding_account.id,
                        'partner_id': customer.id,
                        'name': 'Scheme Outstanding - %s' % payment_company.name,
                        'debit': amount,
                        'credit': 0.0,
                    }),
                ],
            }
            print(move_vals)

            current_move = self.env['account.move'].with_company(
                current_company
            ).sudo().create(move_vals)

            current_move.action_post()
            print(current_move)

            # =========================================================
            # ENTRY 2 - ORIGINAL PAYMENT COMPANY
            #
            # Debtor account              Dr
            #     Partner = SALE ORDER CUSTOMER
            #
            # Creditor account            Cr
            #     Partner = SALE COMPANY
            # =========================================================

            other_debtor_account = self.env['account.account'].with_company(
                payment_company
            ).sudo().search([
                ('company_id', '=', payment_company.id),
                ('name', '=', 'Debtors'),
            ], limit=1)

            creditor_account = self._get_intercompany_creditor_account(
                payment_company
            )

            other_journal = self.env['account.journal'].with_company(
                payment_company
            ).sudo().search([
                ('company_id', '=', payment_company.id),
                ('type', '=', 'general'),
            ], limit=1)

            other_move_vals = {
                'company_id': payment_company.id,
                'journal_id': other_journal.id,
                'date': fields.Date.context_today(self),
                'ref': 'Scheme Redemption - %s' % scheme.display_name,
                'line_ids': [
                    (0, 0, {
                        'account_id': other_debtor_account.id,
                        'partner_id': customer.id,
                        'name': 'Scheme Debtor - %s' % current_company.name,
                        'debit': amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'account_id': creditor_account.id,
                        'partner_id': current_company.partner_id.id,
                        'name': 'Scheme Creditor - %s' % current_company.name,
                        'debit': 0.0,
                        'credit': amount,
                    }),
                ],
            }
            print(other_move_vals)

            other_move = self.env['account.move'].with_company(
                payment_company
            ).sudo().create(other_move_vals)
            print(other_move)

            other_move.action_post()
            print(other_move)

            # Keep the current-company move on the sale order.
            self.scheme_redemption_move_id = current_move.id

        self.scheme_redeemed = True

    def _get_intercompany_creditor_account(self, company):
        return self.env['account.account'].with_company(company).sudo().search([
            ('company_id', '=', company.id),
            ('name', '=', 'Creditors'),
        ], limit=1)