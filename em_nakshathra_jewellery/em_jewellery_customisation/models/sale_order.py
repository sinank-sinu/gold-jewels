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
    round_off_amount = fields.Monetary(string="Round Off", compute="_compute_round_off")
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
                # ('state', '=', 'running'),
                ('balance_amount', '=', 0)
            ])

    def action_apply_scheme(self):
        for order in self:
            if not order.partner_id:
                raise UserError(_("Select customer first."))

            # Prevent duplicate apply
            if order.scheme_line_id:
                raise UserError(_("Scheme already applied."))

            completed_schemes = order._get_customer_scheme_records().filtered(
                lambda s: s.state == 'completed' and not s.is_redeemed
            )

            if order.apply_scheme and completed_schemes:

                # pick lowest priority
                completed_schemes = order._get_customer_scheme_records().filtered(
                    lambda s: s.state == 'completed' and not s.is_redeemed
                ).sorted(key=lambda s: (s.priority, s.create_date))
            
                if not completed_schemes:
                    raise UserError(_("No completed scheme available for this customer."))
                
                # Take latest / first scheme
                scheme = completed_schemes[0]
               
                scheme_amount = scheme.total_paid

                if scheme_amount <= 0:
                    raise UserError(_("Invalid scheme amount."))

                quotation_total = order.amount_total

                if quotation_total <= 0:
                    raise UserError(_("Quotation total is zero."))

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


    def action_apply_old_gold(self):
        PurchaseOrder = self.env['purchase.order']
        PurchaseLine = self.env['purchase.order.line']
        AccountMove = self.env['account.move']
        Payment = self.env['account.payment']

        product = self.env.ref(
            'em_jewellery_management.product_old_gold',
            raise_if_not_found=False
        )
        if not product:
            raise ValidationError(_("Old Gold product not configured."))

        journal = self.env['account.journal'].search(
            [('type', 'in', ('cash', 'bank')),
             ('company_id', '=', self.env.company.id)],
            limit=1
        )
        if not journal:
            raise ValidationError(_("Cash/Bank journal not found."))

        for order in self:
            if not order.old_gold_line_ids:
                raise ValidationError(_("No Old Gold lines found."))

            # ------------------------------------------------
            # 1️⃣ CREATE OLD GOLD PURCHASE (LOGICAL RECORD)
            # ------------------------------------------------
            self.env['old.gold.purchase'].create({
                'partner_id': order.partner_id.id,
                'date': fields.Date.today(),
                'branch_location_id': order.branch_location_id.id,
                'sale_id': order.id,
                'branch_id': order.branch_id.id,
                'old_gold_line_ids': [
                    (0, 0, {
                        'purity_id': l.purity_id.id,
                        'gross_weight': l.gross_weight,
                        'stone_weight': l.stone_weight,
                        'rate': l.rate,
                    }) for l in order.old_gold_line_ids
                ],
            })

            # ------------------------------------------------
            # 2️⃣ GROUP AMOUNT BY PURITY
            # ------------------------------------------------
            purity_map = {}

            for line in order.old_gold_line_ids:
                purity = line.purity_id

                if purity not in purity_map:
                    purity_map[purity] = {
                        'weight': 0.0,
                        'amount': 0.0,
                    }

                purity_map[purity]['weight'] += line.net_weight
                purity_map[purity]['amount'] += line.amount

            # ------------------------------------------------
            # 3️⃣ CREATE PURCHASE ORDER
            # ------------------------------------------------
            po = PurchaseOrder.create({
                'partner_id': order.partner_id.id,
                'date_order': fields.Date.today(),
                'origin': order.name,
                'branch_id': order.branch_id.id,
                'sale_id': order.id,
                # 'amount_total':order.old_gold_line_ids.amount
            })

            for purity, vals in purity_map.items():
                total_weight = vals['weight']
                total_amount = vals['amount']

                if not total_weight:
                    continue

                rate = total_amount / total_weight  # 👈 derived gold rate

                PurchaseLine.create({
                    'order_id': po.id,
                    'product_id': product.id,
                    'name': f'Old Gold Purchase ({purity.name})',
                    'product_qty': total_weight,  # ✅ grams
                    'gold_rate': rate,
                    'price_unit':rate,# ✅ gold rate
                    'product_uom': product.uom_po_id.id,
                    'taxes_id': [(6, 0, [])],
                    'purity_id':purity.id
                })
            # ------------------------------------------------
            # 4️⃣ CONFIRM PO
            # ------------------------------------------------
            po.button_confirm()
            self.purchase_order_id =po.id

            for picking in po.picking_ids:
                picking.action_confirm()
                picking.action_assign()

                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty

                picking.button_validate()

            # ------------------------------------------------
            # 5️⃣ CREATE & POST VENDOR BILL
            # ------------------------------------------------
            bill_action = po.action_create_invoice()
            bill = AccountMove.browse(bill_action['res_id'])
            bill.invoice_date = fields.Date.context_today(self)

            bill.action_post()
            self.old_gold_bill_id =bill.id

            # ------------------------------------------------
            # 6️⃣ REGISTER & POST PAYMENT
            # ------------------------------------------------
            payment = Payment.create({
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'partner_id': order.partner_id.id,
                'amount': bill.amount_total,
                'journal_id': journal.id,
                'date': fields.Date.today(),
                'ref': bill.name,
            })
            payment.action_post()

            # ------------------------------------------------
            # 7️⃣ RECONCILE BILL & PAYMENT
            # ------------------------------------------------
            payable = bill.line_ids.filtered(
                lambda l: l.account_id.account_type == 'liability_payable'
            )

            (payment.line_ids + payable).filtered(
                lambda l: l.account_id == payable.account_id
            ).reconcile()

        return True

    @api.depends('amount_total')
    def _compute_round_off(self):
        for order in self:
            rounded_total = ceil(order.amount_total / 100.0) * 100
            order.round_off_amount = rounded_total - order.amount_total

    @api.depends_context('lang')
    @api.depends('order_line.tax_id', 'order_line.price_unit', 'amount_total', 'amount_untaxed')
    def _compute_tax_totals(self):
        super()._compute_tax_totals()

        for order in self:
            if not order.tax_totals:
                continue
            
            has_gold_bullion = order.order_line.filtered(
                lambda l: l.product_template_id.name == 'Gold Bullion'
            )

            if has_gold_bullion:
                continue

            tax_totals = order.tax_totals

            original_total = tax_totals.get('amount_total', 0.0)

            rounded_total = ceil(original_total / 100.0) * 100
            round_off = rounded_total - original_total

            tax_totals['amount_total'] = rounded_total
            tax_totals['formatted_amount_total'] = order.currency_id.symbol + " %.2f" % rounded_total

            # optional: show rounding line
            tax_totals['display_rounding'] = True
            tax_totals['rounding_amount'] = round_off
            tax_totals['formatted_rounding_amount'] = (
                order.currency_id.symbol + " %.2f" % round_off
            )

            order.tax_totals = tax_totals

    @api.depends(
        'order_line.price_total',
        'order_line.price_tax',
    )
    def _compute_amounts(self):
        super()._compute_amounts()

        for order in self:

            # Skip Gold Bullion
            has_gold_bullion = order.order_line.filtered(
                lambda l: l.product_template_id.name == 'Gold Bullion'
            )

            if has_gold_bullion:
                continue

            rounded_total = ceil(order.amount_total / 100.0) * 100
            order.amount_total = rounded_total