from collections import defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    has_old_gold = fields.Boolean(string='Old Gold Purchase')
    unfix = fields.Boolean(string='Unfix', default=False)
    old_gold_line_ids = fields.One2many('sale.old.gold.line', 'sale_id')
    branch_location_id = fields.Many2one('stock.location',default=lambda self: self.env.user.branch_id.old_gold_location_id.id)
    # old_gold_po_ids = fields.One2many(
    #     'purchase.order',
    #     'sale_id',
    #     string='Old Gold Purchase Orders'
    # )
    #
    # old_gold_po_count = fields.Integer(
    #     compute='_compute_old_gold_po_count'
    # )
    apply_scheme = fields.Boolean(string="Apply Scheme")
    scheme_line_id = fields.Many2one(
        'sale.order.line',
        string="Scheme Line",
        readonly=True,
        copy=False
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Source Purchase Order',
        readonly=True
    )
    old_gold_bill_id = fields.Many2one(
        'account.move',
        string='Old Gold Vendor Bill',
        readonly=True,
        copy=False,
    )
    old_gold_bill_amount = fields.Monetary(
        related='old_gold_bill_id.amount_total',
        currency_field='currency_id',
        string='Bill Amount',
        readonly=True,
    )

    advance_payment_ids = fields.One2many('account.payment', 'sale_id', string='Advance Payments')
    advance_payment_count = fields.Integer(compute='_compute_advance_payment_count')

    def _compute_advance_payment_count(self):
        for order in self:
            order.advance_payment_count = len(order.advance_payment_ids)

    def action_view_advance_payments(self):
        self.ensure_one()
        return {
            'name': _('Advance Payments'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'tree,form',
            'domain': [('sale_id', '=', self.id)],
            'context': {
                'default_sale_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_payment_type': 'inbound',
            },
        }

    active_scheme_id = fields.Many2one(
        'jewellery.scheme.enrollment',
        string="Customer Scheme",
        readonly=True
    )

    @api.onchange('partner_id')
    def _onchange_partner_set_scheme(self):
        for rec in self:
            rec.apply_scheme = False
            rec.active_scheme_id = False

            if not rec.partner_id:
                continue

            # Search for active scheme with balance
            # scheme = self.env['jewellery.scheme.enrollment'].search([
            #     ('partner_id', '=', rec.partner_id.id),
            #     ('active', '=', True),
            #     ('balance_amount', '=', 0)
            # ], limit=1)
            scheme = self.env['jewellery.scheme.enrollment'].search([
                ('partner_id', '=', rec.partner_id.id),
                ('active', '=', True),
                ('state', '=', 'completed'),
                ('balance_amount', '=', 0)
            ], limit=1)

            if scheme:
                rec.apply_scheme = True
                rec.active_scheme_id = scheme

    def action_apply_old_gold(self):
        PurchaseOrder = self.env['purchase.order']
        PurchaseLine = self.env['purchase.order.line']
        AccountMove = self.env['account.move']

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
                'unfix': order.unfix,
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
                    'price_unit': rate,  # ✅ gold rate
                    'product_uom': product.uom_po_id.id,
                    'taxes_id': [(6, 0, [])],
                })
            # ------------------------------------------------
            # 4️⃣ CONFIRM PO
            # ------------------------------------------------
            po.button_confirm()
            self.purchase_order_id = po.id

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
            bill.is_old_gold_bill = True

            bill.action_post()
            self.old_gold_bill_id = bill.id

        return True

    def _get_customer_scheme_records(self):
        self.ensure_one()
        return self.env['jewellery.scheme.enrollment'].search([
            ('partner_id', '=', self.partner_id.id),
            ('active', '=', True),
            # ('state', '=', 'running'),
            ('balance_amount', '=', 0)
        ], limit=1)

    def _get_customer_scheme_amount(self):
        self.ensure_one()
        schemes = self._get_customer_scheme_records()
        return sum(schemes.mapped('remaining_amount'))

    def _get_scheme_product(self):
        product = self.env['product.product'].search(
            [('is_scheme_product', '=', True)],
            limit=1
        )
        if not product:
            raise UserError(_("Please configure a Scheme Product first."))
        return product

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
    # def action_apply_scheme(self):
    #     for order in self:
    #         if not order.partner_id:
    #             raise UserError(_("Select customer first."))

    #         # Check if customer has active scheme with balance
    #         schemes = order._get_customer_scheme_records()
    #         if not schemes:
    #             raise UserError(_("No active scheme available for this customer."))

    #         # 1️⃣ Calculate total MC amount from all lines
    #         total_mc = sum(order.order_line.mapped('mc_amount'))
    #         print(total_mc,'total_mc')

    #         if total_mc <= 0:
    #             raise UserError(_("No Making Charge found to apply scheme."))

    #         # 2️⃣ Get scheme product (for discount line)
    #         scheme_product = order._get_scheme_product()

    #         # 3️⃣ Create a negative sale order line to reduce MC
    #         line = self.env['sale.order.line'].create({
    #             'order_id': order.id,
    #             'product_id': scheme_product.id,
    #             'product_uom_qty': 1,
    #             'product_uom': scheme_product.uom_id.id,
    #             'price_unit': -total_mc,
    #             'name': f"{scheme_product.name} (MC Discount)",
    #         })

    #         # 4️⃣ Assign line to order for reference
    #         order.scheme_line_id = line
    #         schemes.write({
    #             'active': False
    #         })

    #         # 5️⃣ Optional: Zero out MC in order lines (so invoice reflects correct price)
    #         for ol in order.order_line:
    #             if hasattr(ol, 'mc_amount') and ol.mc_amount > 0:
    #                 ol.mc_amount = 0

    def action_remove_scheme(self):
        for order in self:

            if not order.scheme_line_id:
                continue

            consumed_amount = abs(order.scheme_line_id.price_unit)

            # 🔎 Get schemes even if inactive (because we disabled them on apply)
            schemes = self.env['jewellery.scheme.enrollment'].search([
                ('partner_id', '=', order.partner_id.id),
                ('active', '=', False),  # 👈 previously used schemes
            ], order='id desc')

            remaining = consumed_amount

            for scheme in schemes:
                if remaining <= 0:
                    break

                restoreable = scheme.scheme_amount - scheme.remaining_amount
                restore = min(restoreable, remaining)

                scheme.remaining_amount += restore
                remaining -= restore

                # ✅ Reactivate scheme
                scheme.active = True
                # OR if using state:
                # scheme.state = 'running'

            # 🧹 Remove discount line
            order.scheme_line_id.unlink()
            order.scheme_line_id = False

    def action_confirm(self):
        for order in self:
            order.picking_ids.write({'branch_id': order.branch_id.id})
            need_approval = any(
                line.mc_percent_actual < line.sale_making_charge_min
                for line in order.order_line
                if line.sale_making_charge_min
            )

            if need_approval and not self.env.user.has_group('em_jewellery_management.group_mc_approval_manager'):
                raise UserError(_("Manager approval required for low making charge."))

        res = super().action_confirm()
        for order in self:
            labels = order.order_line.mapped('label_id')
            labels.write({'active': False})
            for og in order.old_gold_line_ids:
                order._create_old_gold_stock(og)
        return res

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        for move in moves:
            # Find the sale order for this move
            sale_orders = move.line_ids.mapped('sale_line_ids.order_id')
            if not sale_orders:
                continue
            order = sale_orders[0]

            # if not order.unfix:
            #     continue

            po = order.purchase_order_id
            reduction_amount = 0.0
            ref_name = ""

            if po and order.unfix:
                # Journal is already set to Debtors via _prepare_invoice.
                # Vendor bill amount is displayed as a field on the invoice (vendor_bill_amount).
                pass

        return moves

    def _create_old_gold_stock(self, og):
        product = self.env.ref('em_jewellery_management.product_old_gold')
        picking_type = self.env.ref('stock.picking_type_internal')
        source_location = self.env.ref('em_jewellery_management.loc_branch_old_gold')
        uom = self.env.ref('uom.product_uom_gram')

        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': source_location.id,
            'location_dest_id': self.branch_location_id.id,
            'origin': self.name,
            'is_old_gold': True,  # ✅ NEW
            'sale_old_id': self.id,
            'branch_id': self.branch_id.id,
        })

        move = self.env['stock.move'].create({
            'product_id': product.id,
            'name': f'Old Gold ({og.purity_id.name})',
            'quantity': og.net_weight,
            'purity_id': og.purity_id.id,
            'product_uom': uom.id,
            'location_id': source_location.id,
            'location_dest_id': self.branch_location_id.id,
            'picking_id': picking.id,
        })

        picking.action_confirm()

        # 🔥 VERY IMPORTANT PART
        move.product_uom_qty = og.net_weight

        picking.button_validate()

        og.stock_move_id = move.id

        # Continue HO transfer

        # Continue to HO transfer

    # @api.model
    # def create(self, vals):
    #     sale = super().create(vals)
    #
    #     if sale.purchase_order_id and sale.state != 'draft':
    #         sale.purchase_order_id.sale_id = sale.id
    #
    #     return

    def action_open_old_gold_bill(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Old Gold Vendor Bill'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.old_gold_bill_id.id,
            'context': {'create': False, 'hide_payment_button': True},
        }

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals['old_gold_price'] = self.old_gold_bill_amount
        vals['unfix'] = self.unfix
        return vals

    def action_create_invoice_and_pay(self):
        for order in self:
            invoices = order._create_invoices()

            if not invoices:
                continue
            invoices.invoice_date = fields.Date.context_today(self)
            invoices.date = fields.Date.context_today(self)
            invoices.action_post()

        return True

    def action_advance_payment(self):
        self.ensure_one()
        return {
            'name': _('Advance Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payment_type': 'inbound',
                'default_partner_type': 'customer',
                'default_partner_id': self.partner_id.id,
                'default_amount': self.amount_total,
                'default_currency_id': self.currency_id.id,
                'default_sale_id': self.id,
            }
        }



