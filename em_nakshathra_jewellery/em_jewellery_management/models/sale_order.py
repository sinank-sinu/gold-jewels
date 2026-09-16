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
    is_sale_return = fields.Boolean(string='Sale Return', default=False)
    sale_return_line_ids = fields.One2many('sale.return.line', 'sale_id')
    sale_return_po_id = fields.Many2one('purchase.order', string='Sale Return PO', readonly=True, copy=False)
    sale_return_bill_id = fields.Many2one('account.move', string='Sale Return Vendor Bill', readonly=True, copy=False)
    sale_return_bill_amount = fields.Monetary(
        related='sale_return_bill_id.amount_total',
        currency_field='currency_id',
        string='Return Bill Amount',
        readonly=True,
    )
    sale_return_branch_location_id = fields.Many2one(
        'stock.location',
        string='Sale Return Branch Location',
        default=lambda self: self.env.user.branch_id.old_gold_location_id.id
    )

    # Editing flags – unlock line tables when True
    is_editing_main_so = fields.Boolean(string='Editing Main Order', default=False, copy=False)

    def write(self, vals):
        if self.filtered('is_editing_main_so') or vals.get('is_editing_main_so') or self.filtered('is_editing_old_gold') or vals.get('is_editing_old_gold') or self.filtered('is_editing_sale_return') or vals.get('is_editing_sale_return'):
            self = self.with_context(mail_notrack=True, tracking_disable=True, disable_so_chatter_track=True)
            res = super(SaleOrder, self).write(vals)
            self.env.flush_all()
            return res
        return super(SaleOrder, self).write(vals)

    def message_post_with_source(self, source, render_values=None, subtype_xmlid=None, **kwargs):
        if self.env.context.get('disable_so_chatter_track'):
            return self.env['mail.message']
        return super(SaleOrder, self).message_post_with_source(source, render_values=render_values, subtype_xmlid=subtype_xmlid, **kwargs)

    def message_post(self, **kwargs):
        if self.env.context.get('disable_so_chatter_track'):
            return self.env['mail.message']
        return super(SaleOrder, self).message_post(**kwargs)

    def _track_prepare(self, fields_iter):
        track_self = self.filtered(lambda r: not r.is_editing_main_so)
        if not track_self:
            return
        return super(SaleOrder, track_self)._track_prepare(fields_iter)
    is_editing_old_gold = fields.Boolean(string='Editing Old Gold', default=False, copy=False)
    is_editing_sale_return = fields.Boolean(string='Editing Sale Return', default=False, copy=False)

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

    phone = fields.Char(string="Phone Number", copy=False, tracking=True)
    active_scheme_id = fields.Many2one(
        'jewellery.scheme.enrollment',
        string="Customer Scheme",
        readonly=True
    )

    @api.onchange('phone')
    def _onchange_phone_set_partner_and_scheme(self):
        for rec in self:
            if not rec.phone:
                continue

            phone_input = rec.phone.strip()
            digits = ''.join(filter(str.isdigit, phone_input))
            search_digits = digits[-10:] if len(digits) >= 10 else digits

            if not search_digits:
                continue

            # 1. Search in jewellery.scheme.enrollment by normalized phone
            self.env.cr.execute("""
                SELECT id FROM jewellery_scheme_enrollment 
                WHERE (regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g') LIKE %s
                    OR regexp_replace(COALESCE(whatsapp_number, ''), '[^0-9]', '', 'g') LIKE %s)
                ORDER BY (state IN ('running', 'completed') AND NOT is_redeemed) DESC, active DESC, id DESC
                LIMIT 10
            """, (f"%{search_digits}%", f"%{search_digits}%"))
            matched_ids = [r[0] for r in self.env.cr.fetchall()]

            if matched_ids:
                schemes = self.env['jewellery.scheme.enrollment'].browse(matched_ids)
                target_scheme = schemes.filtered(
                    lambda s: s.state in ('running', 'completed') and not s.is_redeemed
                )[:1] or schemes[:1]

                rec.partner_id = target_scheme.partner_id.id
                rec.active_scheme_id = target_scheme.id
                rec.apply_scheme = True
                if target_scheme.phone:
                    rec.phone = target_scheme.phone
                continue

            # 2. Fallback: Search res.partner if no scheme matched
            self.env.cr.execute("""
                SELECT id FROM res_partner 
                WHERE (regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g') LIKE %s
                    OR regexp_replace(COALESCE(mobile, ''), '[^0-9]', '', 'g') LIKE %s)
                ORDER BY customer_rank DESC, id DESC
                LIMIT 1
            """, (f"%{search_digits}%", f"%{search_digits}%"))
            partner_res = self.env.cr.fetchone()

            if partner_res:
                partner = self.env['res.partner'].browse(partner_res[0])
                rec.partner_id = partner.id
                scheme = self.env['jewellery.scheme.enrollment'].search([
                    ('partner_id', '=', partner.id),
                    ('state', 'in', ('running', 'completed')),
                    ('is_redeemed', '=', False),
                ], order='active desc, id desc', limit=1)
                if scheme:
                    rec.active_scheme_id = scheme.id
                    rec.apply_scheme = True
                else:
                    rec.active_scheme_id = False
                    rec.apply_scheme = False
            else:
                return {
                    'warning': {
                        'title': _("No Match Found"),
                        'message': _("No customer or scheme enrollment found matching phone number: %s") % rec.phone
                    }
                }

    @api.onchange('partner_id')
    def _onchange_partner_set_scheme(self):
        for rec in self:
            rec.apply_scheme = False
            rec.active_scheme_id = False

            if not rec.partner_id:
                rec.phone = False
                continue

            if not rec.phone:
                rec.phone = rec.partner_id.phone or rec.partner_id.mobile or False

            scheme = self.env['jewellery.scheme.enrollment'].search([
                ('partner_id', '=', rec.partner_id.id),
                ('active', '=', True),
                ('state', 'in', ('running', 'completed')),
            ], limit=1)

            if scheme:
                rec.apply_scheme = True
                rec.active_scheme_id = scheme
                if not rec.phone and scheme.phone:
                    rec.phone = scheme.phone

    def action_apply_old_gold(self):
        PurchaseOrder = self.env['purchase.order']
        PurchaseLine = self.env['purchase.order.line']
        AccountMove = self.env['account.move']

        journal = self.env['account.journal'].search(
            [('type', 'in', ('cash', 'bank')),
             ('company_id', '=', self.env.company.id)],
            limit=1
        )
        if not journal:
            raise ValidationError(_("Cash/Bank journal not found."))

        for order in self:

            # FIX: Add sudo() to avoid OLD GOLD product access error
            product = self.env.ref(
                'em_jewellery_management.product_old_gold',
                raise_if_not_found=False
            ).sudo()

            company_id = order.company_id.id or self.env.company.id

            if product and product.company_id and product.company_id.id != company_id:
                product = self.env['product.product'].sudo().search([
                    ('name', '=ilike', 'Old Gold'),
                    ('company_id', 'in', [company_id, False])
                ], limit=1)

                if not product:
                    product = self.env['product.product'].sudo().search([
                        ('is_old_gold', '=', True),
                        ('name', 'not ilike', 'Scrap'),
                        ('company_id', 'in', [company_id, False])
                    ], limit=1)

            if not product:
                raise ValidationError(_("Old Gold product not configured for company."))

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

                rate = total_amount / total_weight

                PurchaseLine.create({
                    'order_id': po.id,
                    'product_id': product.id,
                    'name': f'Old Gold Purchase ({purity.name})',

                    # ADDED: Purity in Purchase Order Line
                    'purity_id': purity.id,

                    'product_qty': total_weight,
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
                picking.location_dest_id = order.branch_location_id.id
                for move in picking.move_ids:
                    move.location_dest_id = order.branch_location_id.id

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

            for bill_line in bill.invoice_line_ids:
                purchase_line = bill_line.purchase_line_id

                if purchase_line and purchase_line.purity_id:
                    bill_line.purity_id = purchase_line.purity_id.id

            target_date = self.env.context.get('old_gold_invoice_date')
            if not target_date:
                target_date = fields.Date.context_today(self)

            bill.with_context(check_move_validity=False).write({
                'name': '/',
                'invoice_date': target_date,
                'date': target_date,
                'is_old_gold_bill': True
            })

            bill.action_post()
            self.old_gold_bill_id = bill.id

        return True

    def _get_customer_scheme_records(self):
        self.ensure_one()
        return self.env['jewellery.scheme.enrollment'].search([
            ('partner_id', '=', self.partner_id.id),
            ('active', '=', True),
            ('state', 'in', ('running', 'completed')),
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

    # def action_apply_scheme(self):
    #     print('apply scheme')
    #     for order in self:
    #         if not order.partner_id:
    #             raise UserError(_("Select customer first."))
    #
    #         # Prevent duplicate apply
    #         if order.scheme_line_id:
    #             raise UserError(_("Scheme already applied."))
    #
    #         completed_schemes = order._get_customer_scheme_records().filtered(
    #             lambda s: s.state in ('running', 'completed') and not s.is_redeemed
    #         )
    #         print(completed_schemes,'completed_schemes')
    #
    #         if order.apply_scheme and completed_schemes:
    #
    #             # pick lowest priority
    #             completed_schemes = order._get_customer_scheme_records().filtered(
    #                 lambda s: s.state in ('running', 'completed') and not s.is_redeemed
    #             ).sorted(key=lambda s: (s.priority, s.create_date))
    #
    #             if not completed_schemes:
    #                 raise UserError(_("No active scheme available for this customer."))
    #
    #             # Take latest / first scheme
    #             scheme = completed_schemes[0]
    #
    #             scheme_amount = scheme.total_paid
    #
    #             if scheme_amount <= 0:
    #                 raise UserError(_("Invalid scheme amount."))
    #
    #             quotation_total = order.amount_total
    #
    #             if quotation_total <= 0:
    #                 raise UserError(_("Quotation total is zero."))
    #
    #             if quotation_total < scheme_amount:
    #                 raise UserError(_("Cannot apply scheme. The purchase amount (%.2f) must be equal to or greater than the scheme amount (%.2f).") % (quotation_total, scheme_amount))
    #
    #             redeem_amount = min(quotation_total, scheme_amount)
    #
    #             product_code = f"SCHEME-{scheme.id}"
    #
    #             product = self.env['product.product'].search([
    #                 ('default_code', '=', product_code)
    #             ], limit=1)
    #
    #             if not product:
    #                 product = self.env['product.product'].create({
    #                     'name': f"{scheme.name} - {order.partner_id.name}",
    #                     'default_code': product_code,
    #                     'type': 'service',
    #                     'list_price': 0.0,
    #                     'taxes_id': [(5, 0, 0)],
    #                     'supplier_taxes_id': [(5, 0, 0)],
    #                 })
    #             else:
    #                 product.write({
    #                     'taxes_id': [(5, 0, 0)],
    #                     'supplier_taxes_id': [(5, 0, 0)],
    #                 })
    #
    #             line = self.env['sale.order.line'].create({
    #                 'order_id': order.id,
    #                 'product_id': product.id,
    #                 'product_uom_qty': 1,
    #                 'product_uom': product.uom_id.id,
    #                 'name': f"{product.name} (Scheme Redemption)",
    #                 'is_scheme_line': True,
    #                 'price_unit': -redeem_amount,
    #                 'tax_id': [(5, 0, 0)],
    #             })
    #             line.write({'tax_id': [(5, 0, 0)]})
    #             order.scheme_line_id = line
    #             scheme.write({
    #                 'state': 'redeemed',
    #                 'is_redeemed': True,
    #             })
    #             self.env['scheme.redemption'].create({
    #                 'scheme_id': scheme.id,
    #                 'sale_order_id': order.id,
    #                 'amount': redeem_amount,
    #             })
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

            # 🔎 Find scheme redemptions linked to this sale order
            redemptions = self.env['scheme.redemption'].search([
                ('sale_order_id', '=', order.id)
            ])

            for redemption in redemptions:
                scheme = redemption.scheme_id
                # Restore the scheme's state
                scheme.write({
                    'is_redeemed': False,
                })
                scheme._compute_totals()
                # Delete the redemption record
                redemption.unlink()

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
            # for og in order.old_gold_line_ids:
            #     order._create_old_gold_stock(og)
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

    # ── Edit / Save – Old Gold ───────────────────────────────────────────────

    def action_edit_old_gold(self):
        """Unlock the Old Gold table for editing."""
        self.ensure_one()
        self.is_editing_old_gold = True

    def action_save_old_gold(self):
        """Persist edits: reverse old stock, create new moves, update vendor bill."""
        self.ensure_one()
        self._update_old_gold_stock_and_bill()
        self.is_editing_old_gold = False
        self.with_context(mail_notrack=True, tracking_disable=True).env.flush_all()

    def _safe_reverse_or_cancel_picking(self, picking):
        """Reverse a picking via return-wizard if it has done moves; otherwise cancel it."""
        has_done_moves = any(m.state == 'done' for m in picking.move_ids)
        if has_done_moves or picking.state == 'done':
            try:
                return_wizard = self.env['stock.return.picking'].with_context(
                    active_id=picking.id, active_model='stock.picking'
                ).create({'picking_id': picking.id})
                return_action = return_wizard.create_returns()
                return_pick_id = return_action.get('res_id')
                if return_pick_id:
                    return_pick = self.env['stock.picking'].browse(return_pick_id)
                    return_pick.action_confirm()
                    return_pick.action_assign()
                    for move in return_pick.move_ids:
                        move.quantity = move.product_uom_qty
                        move.picked = True
                    return_pick.with_context(skip_sms=True, skip_backorder=True, cancel_backorder=True).button_validate()
                    self.env.flush_all()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Error validating return picking: %s", str(e))
                pass
        else:
            try:
                picking.action_cancel()
            except Exception:
                pass

    # ────────────────────────────────────────────────────────────────────────────
    # UPDATE OLD GOLD – stock + bill
    # Strategy:
    #   • Stock  → reverse the original picking (return transfer) then create a
    #             new picking with the updated weights.
    #             The PO is left untouched to avoid done-move cancellation errors.
    #   • Bill   → reset to draft, wipe lines, rebuild from current lines, re-post.
    # ────────────────────────────────────────────────────────────────────────────

    def _update_old_gold_stock_and_bill(self):
        """Reverse old-gold pickings, update PO lines in-place, rebuild vendor bill preserving PO links."""
        self = self.with_context(mail_notrack=True, tracking_disable=True, disable_po_chatter_track=True, disable_so_chatter_track=True)
        if not self.old_gold_line_ids:
            raise ValidationError(_("No Old Gold lines to update."))

        po = self.purchase_order_id

        product = self.env.ref('em_jewellery_management.product_old_gold', raise_if_not_found=False)
        if not product:
            raise ValidationError(_("Old Gold product not configured."))

        # ─ 1. Group current Old Gold lines by Purity ───────────────────────────────
        purity_map = {}
        for line in self.old_gold_line_ids:
            purity = line.purity_id
            if purity not in purity_map:
                purity_map[purity] = {'weight': 0.0, 'amount': 0.0}
            purity_map[purity]['weight'] += line.net_weight
            purity_map[purity]['amount'] += line.amount

        # ─ 2. Update PO lines in-place via write() ─────────────────────────────────
        if po:
            # Enable silent SQL update mode for the PO
            po.is_editing_main_po = True
            
            existing_po_lines = list(po.order_line)
            purity_list = list(purity_map.items())

            for i, (purity, vals) in enumerate(purity_list):
                qty = vals['weight']
                rate = vals['amount'] / qty if qty else 0.0
                
                if i < len(existing_po_lines):
                    # Update existing PO line (triggers our SQL logic in PurchaseOrderLine.write)
                    existing_po_lines[i].write({
                        'product_id': product.id,
                        'name': f'Old Gold Purchase ({purity.name})',
                        'product_qty': qty,
                        'price_unit': rate,
                        'gold_rate': rate,
                    })
                    existing_po_lines[i].qty_received = qty
                else:
                    # Create new PO line
                    new_line = self.env['purchase.order.line'].create({
                        'order_id': po.id,
                        'product_id': product.id,
                        'name': f'Old Gold Purchase ({purity.name})',
                        'product_qty': qty,
                        'price_unit': rate,
                        'gold_rate': rate,
                        'product_uom': product.uom_po_id.id,
                        'taxes_id': [(6, 0, [])],
                    })
                    new_line.qty_received = qty

            # ─ 3. Create fresh pickings for any NEW PO lines ─────────
            # Temporarily disable edit mode so _create_picking functions normally
            po.is_editing_main_po = False
            po._create_picking()
            
            # For any pickings that are still waiting (newly created), validate them
            for picking in po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                picking.write({
                    'is_old_gold': True,
                    'sale_old_id': self.id,
                    'branch_id': self.branch_id.id,
                    'location_dest_id': self.branch_location_id.id,
                })
                for move in picking.move_ids:
                    move.location_dest_id = self.branch_location_id.id
                    
                picking.action_confirm()
                picking.action_assign()
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                try:
                    picking.button_validate()
                except Exception:
                    pass

        # ─ 5. Update vendor bill lines in-place (preserve purchase_line_id / PO link)
        bill = self.old_gold_bill_id
        if bill:
            if bill.state == 'posted':
                bill.button_draft()

            # Build a map: product_id → PO line (assuming one product for all, we map by index/sequence)
            po_lines = list(po.order_line) if po else []

            existing_bill_lines = bill.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
            existing_list = list(existing_bill_lines)
            purity_list = list(purity_map.items())

            for i, (purity, vals) in enumerate(purity_list):
                qty = vals['weight']
                rate = vals['amount'] / qty if qty else 0.0
                po_line = po_lines[i] if i < len(po_lines) else False

                if i < len(existing_list):
                    # Update existing bill line
                    write_vals = {
                        'product_id': product.id,
                        'name': f'Old Gold ({purity.name})',
                        'quantity': qty,
                        'price_unit': rate,
                        'tax_ids': [(5, 0, 0)],
                    }
                    if po_line:
                        write_vals['purchase_line_id'] = po_line.id
                    existing_list[i].with_context(check_move_validity=False).write(write_vals)
                else:
                    # Create new bill line
                    create_vals = {
                        'move_id': bill.id,
                        'product_id': product.id,
                        'name': f'Old Gold ({purity.name})',
                        'quantity': qty,
                        'price_unit': rate,
                        'tax_ids': [(5, 0, 0)],
                    }
                    if po_line:
                        create_vals['purchase_line_id'] = po_line.id
                    self.env['account.move.line'].with_context(check_move_validity=False).create(create_vals)

            # Remove surplus old bill lines
            if len(existing_list) > len(purity_list):
                surplus = existing_list[len(purity_list):]
                for old_line in surplus:
                    old_line.with_context(check_move_validity=False).unlink()

            bill.invoice_date = fields.Date.context_today(self)
            bill.is_old_gold_bill = True
            bill.action_post()

    # ────────────────────────────────────────────────────────────────────────────
    # EDIT / SAVE – Main Order buttons
    # ────────────────────────────────────────────────────────────────────────────

    def action_edit_main_order(self):
        """Unlock the Main Order table for editing."""
        self.ensure_one()
        self.is_editing_main_so = True

    def action_save_main_order(self):
        """Persist edits: trigger new procurement, update invoice."""
        self.ensure_one()
        # Sync updated line values back to their connected labels
        for line in self.order_line:
            if line.label_id:
                label_vals = {
                    'sale_purity_id': line.purity_id.id if line.purity_id else False,
                    'sale_making_charge_value': line.mc_percent,
                    'sale_making_charge_min': line.sale_making_charge_min,
                    'sale_gross_weight': line.product_uom_qty,
                    'sale_stone_weight': line.sale_stone_weight,
                    'sale_stone_weight_ct': line.sale_stone_weight_ct,
                    'sale_diamond_weight_gm': line.sale_diamond_weight_gm,
                    'sale_diamond_weight_ct': line.sale_diamond_weight_ct,
                    'sale_stone_rate': line.sale_stone_rate,
                    'sale_diamond_rate': line.sale_diamond_rate,
                    
                    # Sync to purchase fields to mimic label's onchange
                    'purchase_gross_weight': line.product_uom_qty,
                    'purchase_stone_weight': line.sale_stone_weight,
                    'purchase_stone_weight_ct': line.sale_stone_weight_ct,
                    'purchase_diamond_weight_gm': line.sale_diamond_weight_gm,
                    'purchase_diamond_weight_ct': line.sale_diamond_weight_ct,
                }
                line.label_id.write(label_vals)
                
        self._update_main_so_stock_and_bill()
        self.is_editing_main_so = False
        self.with_context(mail_notrack=True, tracking_disable=True).env.flush_all()

    def _update_main_so_stock_and_bill(self):
        """Trigger new procurement and update invoices."""
        self = self.with_context(mail_notrack=True, tracking_disable=True, disable_po_chatter_track=True, disable_so_chatter_track=True)
        # 2. Trigger procurement to generate new deliveries for the updated quantities
        if self.order_line:
            # Sync label_id to existing moves
            for line in self.order_line:
                for move in line.move_ids.filtered(lambda m: m.state != 'cancel'):
                    if not line.label_id and move.label_id:
                        move.label_id = False
                    elif line.label_id and move.label_id != line.label_id:
                        move.label_id = line.label_id.id
        # No new pickings should be created; sale_order_line.py handles the direct updates.
        # 3. Update customer invoices in-place
        invoices = self.invoice_ids.filtered(
            lambda inv: inv.state != 'cancel' and inv.move_type == 'out_invoice'
        ).with_context(mail_notrack=True, tracking_disable=True)
        for invoice in invoices:
            if invoice.state == 'posted':
                invoice.button_draft()
            
            # Sync the invoice lines from the corresponding SO lines
            for inv_line in invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                so_line = inv_line.sale_line_ids and inv_line.sale_line_ids[0] or False
                if so_line:
                    inv_line.with_context(check_move_validity=False).write({
                        'quantity': so_line.product_uom_qty,
                        'price_unit': so_line.price_unit,
                    })
            
            # Recompute tax totals since we bypassed validity checks
            invoice.with_context(check_move_validity=False)._compute_tax_totals()
            invoice.action_post()

    # ────────────────────────────────────────────────────────────────────────────
    # EDIT / SAVE – Sale Return buttons
    # ────────────────────────────────────────────────────────────────────────────

    def action_edit_sale_return(self):
        """Unlock the Sale Return table for editing."""
        self.ensure_one()
        self.is_editing_sale_return = True

    def action_save_sale_return(self):
        """Persist edits: reverse old stock, create new picking, rebuild vendor bill."""
        self.ensure_one()
        self._update_sale_return_stock_and_bill()
        self.is_editing_sale_return = False
        self.with_context(mail_notrack=True, tracking_disable=True).env.flush_all()

    # ────────────────────────────────────────────────────────────────────────────
    # UPDATE SALE RETURN – stock + bill
    # Strategy:
    #   • Stock  → use _safe_reverse_or_cancel_picking for the PO's pickings,
    #             then create NEW direct pickings (not via PO) to avoid
    #             done-move errors from po.order_line.unlink().
    #             The original PO is left as-is.
    #   • Bill   → reset to draft, wipe lines, rebuild from current lines, re-post.
    # ────────────────────────────────────────────────────────────────────────────

    def _update_sale_return_stock_and_bill(self):
        """Reverse existing sale-return pickings, create new direct ones, rebuild vendor bill."""
        self = self.with_context(mail_notrack=True, tracking_disable=True, disable_po_chatter_track=True, disable_so_chatter_track=True)
        if not self.sale_return_line_ids:
            raise ValidationError(_("No Sale Return lines to update."))

        po = self.sale_return_po_id

        # ─ 1. Update PO lines in-place via write() – safe with done stock moves ─
        #      write() only updates the line record, and our custom PurchaseOrderLine.write 
        #      SQL interceptor will handle the stock and valuation updates silently.
        if po:
            # Enable silent SQL update mode for the PO if em_purchase_edit is installed
            if hasattr(po, 'is_editing_main_po'):
                po.is_editing_main_po = True
            
            existing_po_lines = list(po.order_line)
            sale_return_lines = list(self.sale_return_line_ids)

            for i, sr_line in enumerate(sale_return_lines):
                gross_wt = sr_line.gross_weight or 1.0
                unit_price = round(sr_line.amount / gross_wt, 4) if gross_wt else sr_line.rate
                mc_pct = sr_line.mc_percent_actual or sr_line.mc_percent or 0.0
                mc_amt = sr_line.mc_amount_actual or sr_line.mc_amount or 0.0
                line_vals = {
                    'product_id': sr_line.product_id.id,
                    'name': f'Sale Return ({sr_line.product_id.name})',
                    'sale_return_line_id': sr_line.id,
                    'product_qty': gross_wt,
                    'gross_weight': gross_wt,
                    'stone_weight': sr_line.sale_stone_weight or sr_line.stone_weight or 0.0,
                    'diamond_weight_gm': sr_line.sale_diamond_weight_gm or 0.0,
                    'purity_id': sr_line.purity_id.id if sr_line.purity_id else False,
                    'gold_rate': sr_line.rate,
                    'purchase_making_charge_type': 'percent' if mc_pct else 'amount',
                    'mc_percent': mc_pct,
                    'purchase_making_charge_value': mc_amt,
                    'stone_rate': sr_line.sale_stone_rate or 0.0,
                    'diamond_rate': sr_line.sale_diamond_rate or 0.0,
                    'price_unit': unit_price,
                    'price_subtotal': sr_line.amount,
                }
                if i < len(existing_po_lines):
                    # Update the existing PO line in place (triggers our SQL logic)
                    existing_po_lines[i].write(line_vals)
                    existing_po_lines[i].qty_received = gross_wt
                else:
                    # More sale return lines than original PO lines → create new
                    line_vals.update({
                        'order_id': po.id,
                        'product_uom': sr_line.product_id.uom_po_id.id if sr_line.product_id.uom_po_id else (sr_line.product_uom.id if sr_line.product_uom else False),
                        'taxes_id': [(6, 0, [])],
                    })
                    new_line = self.env['purchase.order.line'].create(line_vals)
                    new_line.qty_received = gross_wt

        # ─ 2. Create fresh pickings from updated PO to link stock properly ──────
        if po:
            # Temporarily disable edit mode so _create_picking functions normally
            if hasattr(po, 'is_editing_main_po'):
                po.is_editing_main_po = False
            # Trigger PO to create new pickings for any NEW lines
            po._create_picking()
            
            # Confirm and validate the newly created pickings
            for picking in po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                if self.sale_return_branch_location_id:
                    picking.write({
                        'is_old_gold': True,
                        'sale_old_id': self.id,
                        'branch_id': self.branch_id.id,
                        'location_dest_id': self.sale_return_branch_location_id.id,
                    })
                    for move in picking.move_ids:
                        move.location_dest_id = self.sale_return_branch_location_id.id
                
                picking.action_confirm()
                picking.action_assign()
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                try:
                    picking.button_validate()
                except Exception:
                    pass

        # ─ 4. Update vendor bill lines in-place (preserve purchase_line_id / PO link) ─
        # Do NOT unlink() all lines — that breaks the bill→PO relationship.
        # Instead: update existing lines via write(), create new ones if needed,
        # and only unlink lines that have no matching sale return entry.
        bill = self.sale_return_bill_id
        if bill:
            if bill.state == 'posted':
                bill.button_draft()

            # Build a map: product_id → PO line (to preserve purchase_line_id)
            po_line_map = {}
            if po:
                for po_line in po.order_line:
                    po_line_map.setdefault(po_line.product_id.id, po_line)

            # Only consider product lines (skip tax/section lines)
            existing_bill_lines = bill.invoice_line_ids.filtered(
                lambda l: l.display_type == 'product'
            )
            existing_list = list(existing_bill_lines)
            sale_return_lines = list(self.sale_return_line_ids)

            for i, sr_line in enumerate(sale_return_lines):
                gross_wt = sr_line.gross_weight or 1.0
                unit_price = round(sr_line.amount / gross_wt, 4) if gross_wt else sr_line.rate
                po_line = po_line_map.get(sr_line.product_id.id)
                if i < len(existing_list):
                    # Update the existing bill line in-place (keeps purchase_line_id)
                    write_vals = {
                        'product_id': sr_line.product_id.id,
                        'name': f'Sale Return ({sr_line.product_id.name})',
                        'quantity': gross_wt,
                        'price_unit': unit_price,
                        'tax_ids': [(5, 0, 0)],
                    }
                    if po_line:
                        write_vals['purchase_line_id'] = po_line.id
                        if po_line.purity_id:
                            write_vals['purity_id'] = po_line.purity_id.id
                    existing_list[i].with_context(check_move_validity=False).write(write_vals)
                else:
                    # More sale return lines than existing bill lines → create new
                    create_vals = {
                        'move_id': bill.id,
                        'product_id': sr_line.product_id.id,
                        'name': f'Sale Return ({sr_line.product_id.name})',
                        'quantity': gross_wt,
                        'price_unit': unit_price,
                        'tax_ids': [(5, 0, 0)],
                    }
                    if po_line:
                        create_vals['purchase_line_id'] = po_line.id
                        if po_line.purity_id:
                            create_vals['purity_id'] = po_line.purity_id.id
                    self.env['account.move.line'].with_context(check_move_validity=False).create(create_vals)

            # Remove surplus old bill lines beyond the count of sale return lines
            if len(existing_list) > len(sale_return_lines):
                surplus = existing_list[len(sale_return_lines):]
                for old_line in surplus:
                    old_line.with_context(check_move_validity=False).unlink()

            bill.invoice_date = fields.Date.context_today(self)
            bill.is_sale_return = True
            bill.action_post()

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals['old_gold_price'] = self.old_gold_bill_amount
        vals['unfix'] = self.unfix
        vals['sale_return_price'] = self.sale_return_bill_amount
        vals['is_sale_return'] = self.is_sale_return
        return vals

    def action_open_sale_return_bill(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Sale Return Vendor Bill'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.sale_return_bill_id.id,
            'context': {'create': False, 'hide_payment_button': True},
        }

    def action_apply_sale_return(self):
        PurchaseOrder = self.env['purchase.order']
        PurchaseLine = self.env['purchase.order.line']
        AccountMove = self.env['account.move']

        for order in self:
            if not order.sale_return_line_ids:
                raise ValidationError(_("No Sale Return lines found."))

            po = PurchaseOrder.create({
                'partner_id': order.partner_id.id,
                'company_id': order.company_id.id,
                'date_order': fields.Date.today(),
                'origin': order.name,
                'branch_id': order.branch_id.id,
                'sale_id': order.id,
                'is_sale_return_po': True,
            })

            for line in order.sale_return_line_ids:
                gross_wt = line.gross_weight or 1.0
                unit_price = round(line.amount / gross_wt, 4) if gross_wt else line.rate
                mc_pct = line.mc_percent_actual or line.mc_percent or 0.0
                mc_amt = line.mc_amount_actual or line.mc_amount or 0.0

                PurchaseLine.create({
                    'order_id': po.id,
                    'product_id': line.product_id.id,
                    'name': f'Sale Return ({line.product_id.name})',
                    'sale_return_line_id': line.id,
                    'product_qty': gross_wt,
                    'gross_weight': gross_wt,
                    'stone_weight': line.sale_stone_weight or line.stone_weight or 0.0,
                    'diamond_weight_gm': line.sale_diamond_weight_gm or 0.0,
                    'purity_id': line.purity_id.id if line.purity_id else False,
                    'gold_rate': line.rate,
                    'purchase_making_charge_type': 'percent' if mc_pct else 'amount',
                    'mc_percent': mc_pct,
                    'purchase_making_charge_value': mc_amt,
                    'stone_rate': line.sale_stone_rate or 0.0,
                    'diamond_rate': line.sale_diamond_rate or 0.0,
                    'price_unit': unit_price,
                    'price_subtotal': line.amount,
                    'product_uom': line.product_id.uom_po_id.id if line.product_id.uom_po_id else (line.product_uom.id if line.product_uom else False),
                })

            # Confirm PO
            po.button_confirm()
            order.sale_return_po_id = po.id

            for line in po.order_line:
                line.qty_received = line.product_qty

            for picking in po.picking_ids:
                if order.sale_return_branch_location_id:
                    picking.write({
                        'is_old_gold': True,
                        'sale_old_id': order.id,
                        'branch_id': order.branch_id.id,
                        'location_dest_id': order.sale_return_branch_location_id.id,
                    })
                    for move in picking.move_ids:
                        move.location_dest_id = order.sale_return_branch_location_id.id

                picking.action_confirm()
                picking.action_assign()

                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True

                try:
                    picking.button_validate()
                except Exception:
                    pass

            # Create & Post Vendor Bill
            bill_action = po.action_create_invoice()
            bill = AccountMove.browse(bill_action['res_id'])
            for bill_line in bill.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                po_line = bill_line.purchase_line_id
                if po_line:
                    bill_line.purity_id = po_line.purity_id.id if po_line.purity_id else False
                    gw = po_line.gross_weight or bill_line.quantity or 1.0
                    sr_amt = po_line.sale_return_line_id.amount if po_line.sale_return_line_id else po_line.price_subtotal
                    u_price = round(sr_amt / gw, 4) if gw else po_line.price_unit
                    bill_line.with_context(check_move_validity=False).write({
                        'quantity': gw,
                        'price_unit': u_price,
                    })
            bill.invoice_date = fields.Date.context_today(self)
            bill.action_post()
            order.sale_return_bill_id = bill.id

        return True

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
        journal = self.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash')),
            ('company_id', '=', self.env.company.id)
        ], limit=1)

        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': self.amount_total,
            'currency_id': self.currency_id.id,
            'sale_id': self.id,
            'journal_id': journal.id if journal else False,
        })
        
        return {
            'name': _('Advance Payment via Pine Labs'),
            'type': 'ir.actions.act_window',
            'res_model': 'pinelabs.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_amount': payment.amount,
                'default_payment_id': payment.id,
                'default_sale_order_id': self.id,
            }
        }




