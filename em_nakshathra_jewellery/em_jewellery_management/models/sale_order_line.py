from email.policy import default

from numpy.f2py.rules import defmod_rules

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare, float_round

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    label_id = fields.Many2one(
        'product.label',
        string="Label",
    )
    purity_id = fields.Many2one('gold.purity', string="Purity")
    net_weight = fields.Float(string="Net Weight  (g)",compute="_compute_net_weight",digits=(16, 3))
    sale_stone_weight = fields.Float(string="Stone Weight (g)",digits=(16, 3))
    sale_stone_weight_ct = fields.Float(
        string="Stone Weight (ct)",
        digits=(12, 3)
    )
    sale_diamond_weight_gm = fields.Float(
        string="Diamond Weight (g)",
        digits=(12, 3)
    )
    sale_diamond_weight_ct = fields.Float(
        string="Diamond Weight (ct)",
        digits=(12, 3)
    )
    gold_rate =fields.Float(string="Gold Rate(g)")

    mc_percent = fields.Float(string="Max mc")
    mc_amount = fields.Float(string="MC Amt", compute="_compute_mc_amount", store=True, readonly=False, precompute=True)
    metal_amount = fields.Float(string="Metal Amt", compute="_compute_metal_amounts",store=True, precompute=True)

    fine_weight = fields.Float(string="Fine Weight  (g)",digits=(16, 3))
    tag_weight = fields.Float(string="Tag Weight (g)")

    sale_stone_rate = fields.Float(string="Stone Amt")
    sale_diamond_rate = fields.Float(string="Diamond Amt")
    product_uom_qty = fields.Float(
        compute='_compute_product_uom_qty',
        digits='Product Unit of Measure',
        readonly=False, store=True, precompute=True,
    )
    sale_gross_weight = fields.Float(string="Gross Weight (g)", digits=(16, 3))
    price_unit = fields.Float(
        string='Unit Price', required=True, digits=(16, 3),
        compute="_compute_price_unit", readonly=False, store=True, precompute=True)
    price_subtotal = fields.Monetary(string='Subtotal', compute='_compute_subtotal', readonly=False, store=True, precompute=True)
    price_subtotal_actual = fields.Monetary(compute='_compute_subtotal', string='MRP', store=True, precompute=True)
    total_amount_round_off = fields.Monetary(
        string="Round off",
        compute="_compute_tax_included_amount",
        inverse="_inverse_total_amount_round_off",
    )
    mc_percent_actual = fields.Float(string="MC%", digits=(16, 6), readonly=False)
    mc_amount_actual = fields.Float(
        string="MC",
        compute="_compute_mc_amount_actual",
        inverse="_inverse_mc_amount_actual",
        store=True,
        readonly=False,
        precompute=True,
        digits=(16, 3),
    )
    mc_discount = fields.Float(string="Discount", compute="_compute_mc_discount")
    sale_making_charge_min = fields.Float(string="Sale Making Charge Min")
    sale_making_charge_fixed_amount_min = fields.Float(string="Sale Fixed Making Charge Min")
    other_weight_g = fields.Float(string="Other Weight (g)", digits=(16, 3))
    other_weight_amount = fields.Float(string="Other Weight Amount")

    @api.depends('price_total')
    def _compute_tax_included_amount(self):
        for line in self:
            line.total_amount_round_off = line.price_total

    @api.onchange('total_amount_round_off')
    def _onchange_total_amount_round_off(self):
        self._inverse_total_amount_round_off()

    def _inverse_total_amount_round_off(self):
        for line in self:
            if getattr(line, 'is_scheme_line', False):
                raise ValidationError(_("The tax-included amount cannot be changed on a scheme line."))
            if not line.product_uom_qty:
                raise ValidationError(_("Set a non-zero quantity before editing the tax-included amount."))

            quantity = line.product_uom_qty
            currency = line.currency_id
            target_total = line.total_amount_round_off

            def total_for_mc_amount(mc_amount):
                subtotal = (
                    line.metal_amount
                    + mc_amount
                    + line.sale_stone_rate
                    + line.sale_diamond_rate
                    + line.other_weight_amount
                )
                base_line = line.env['account.tax']._convert_to_tax_base_line_dict(
                    line,
                    partner=line.order_id.partner_id,
                    currency=line.order_id.currency_id,
                    product=line.product_id,
                    taxes=line.tax_id,
                    price_unit=float_round(subtotal / quantity, precision_digits=3),
                    quantity=quantity,
                    discount=line.discount,
                    price_subtotal=subtotal,
                )
                tax_results = line.env['account.tax'].with_company(line.company_id)._compute_taxes([base_line])
                totals = next(iter(tax_results['totals'].values()), {})
                return totals.get('amount_untaxed', 0.0) + totals.get('amount_tax', 0.0)

            has_actual_mc_amount = not currency.is_zero(line.mc_amount_actual)
            current_mc_amount = max((
                line.mc_amount_actual if has_actual_mc_amount else line.mc_amount
            ) or 0.0, 0.0)
            current_total = total_for_mc_amount(current_mc_amount)
            difference = current_total - target_total
            if float_compare(difference, 0.0, precision_rounding=currency.rounding) == 0:
                continue

            if difference > 0.0:
                low = 0.0
                high = current_mc_amount
                minimum_total = total_for_mc_amount(low)
                if float_compare(
                    target_total,
                    minimum_total,
                    precision_rounding=currency.rounding,
                ) < 0:
                    raise ValidationError(_(
                        "The tax-included amount cannot be lower than the line total with zero making charge."
                    ))
            else:
                low = current_mc_amount
                high = max(current_mc_amount + 1.0, 1.0)
                step = high - current_mc_amount
                for _attempt in range(64):
                    if float_compare(
                        total_for_mc_amount(high),
                        target_total,
                        precision_rounding=currency.rounding,
                    ) >= 0:
                        break
                    step *= 2.0
                    high = current_mc_amount + step
                else:
                    raise ValidationError(_("Unable to calculate a making charge for this tax-included amount."))

            for _attempt in range(64):
                middle = (low + high) / 2.0
                if float_compare(
                    total_for_mc_amount(middle),
                    target_total,
                    precision_rounding=currency.rounding,
                ) < 0:
                    low = middle
                else:
                    high = middle

            required_mc_amount = min(
                (low, high),
                key=lambda mc_amount: abs(total_for_mc_amount(mc_amount) - target_total),
            )
            if not currency.is_zero(required_mc_amount) and not line.metal_amount:
                raise ValidationError(_("A making charge cannot be set when the metal amount is zero."))

            if line.label_id and line.label_id.sale_making_charge_type == 'percent':
                line.mc_percent_actual = (
                    required_mc_amount / line.metal_amount * 100.0
                    if line.metal_amount else 0.0
                )
            else:
                line.mc_amount_actual = required_mc_amount
                line._inverse_mc_amount_actual()


    def _inverse_mc_amount_actual(self):
        for rec in self:
            if rec.metal_amount and rec.mc_amount_actual:
                rec.mc_percent_actual = (rec.mc_amount_actual / rec.metal_amount) * 100
            else:
                rec.mc_percent_actual = 0.0

    @api.depends('metal_amount', 'mc_percent_actual', 'label_id.sale_making_charge_type', 'label_id.sale_making_charge_fixed_amount_max')
    def _compute_mc_amount_actual(self):
        for rec in self:
            if rec.mc_percent_actual:
                rec.mc_amount_actual = rec.metal_amount * (rec.mc_percent_actual / 100.0)
            else:
                rec.mc_amount_actual=0.0


    @api.depends('price_subtotal', 'price_subtotal_actual')
    def _compute_mc_discount(self):
        for rec in self:
            if rec.price_subtotal:
               rec.mc_discount = rec.price_subtotal_actual - rec.price_subtotal
            else:
               rec.mc_discount = 0.0

    @api.depends('metal_amount', 'mc_percent', 'label_id.sale_making_charge_type', 'label_id.sale_making_charge_fixed_amount_max')
    def _compute_mc_amount(self):
        for rec in self:
            if rec.label_id and rec.label_id.sale_making_charge_type == 'amount':
                rec.mc_amount = rec.label_id.sale_making_charge_fixed_amount_max
            else:
                rec.mc_amount = rec.metal_amount * (rec.mc_percent / 100.0)

    @api.onchange('label_id','purity_id')
    def _onchange_label_id(self):
        if self.label_id :
            self.purity_id = self.label_id.purity_id.id
            self.mc_percent = self.label_id.sale_making_charge_value
            self.sale_making_charge_min = self.label_id.sale_making_charge_min
            self.mc_amount =self.label_id.sale_making_charge_fixed_amount_max
            self.product_uom_qty = self.label_id.sale_gross_weight
            self.sale_stone_weight = self.label_id.sale_stone_weight
            self.sale_stone_weight_ct = self.label_id.sale_stone_weight_ct
            self.sale_diamond_weight_gm = self.label_id.sale_diamond_weight_gm
            self.sale_diamond_weight_ct = self.label_id.sale_diamond_weight_ct
            self.sale_stone_rate = self.label_id.sale_stone_rate
            self.sale_diamond_rate = self.label_id.sale_diamond_rate
            self.other_weight_g = self.label_id.other_weight_g
            self.other_weight_amount = self.label_id.other_weight_amount

            gold_rate = 0.0
            today = fields.Date.today()
            gold_rate_rec = self.env['gold.rate.master'].search([
                ('purity_id', '=', self.purity_id.id),
                ('date', '<=', today),
                ('active', '=', True),
                ('rate_type', '=', 'sale')

            ], order='date desc', limit=1)
            gold_rate = gold_rate_rec.rate_per_gram
            self.gold_rate = gold_rate
            self.metal_amount = self.gold_rate * self.product_uom_qty

        if not self.label_id :
            today = fields.Date.today()
            gold_rate_rec = self.env['gold.rate.master'].search([
                ('purity_id', '=', self.purity_id.id),
                ('date', '<=', today),
                ('active', '=', True),
                ('rate_type', '=', 'sale')

            ], order='date desc', limit=1)
            gold_rate = gold_rate_rec.rate_per_gram
            self.gold_rate = gold_rate


    @api.depends('gold_rate', 'product_uom_qty')
    def _compute_metal_amount(self):
        for rec in self:
            if getattr(rec, 'is_scheme_line', False):
                rec.metal_amount = 0.0
                continue
            rec.metal_amount = rec.gold_rate * rec.product_uom_qty

    @api.depends(
        'product_uom_qty',
        'sale_stone_weight',
        'sale_diamond_weight_gm',
    )
    def _compute_net_weight(self):
        for rec in self:
            if getattr(rec, 'is_scheme_line', False):
                rec.net_weight = 0.0
                continue
            rec.net_weight = (
                    rec.product_uom_qty
                    - rec.sale_stone_weight
                    - rec.sale_diamond_weight_gm
            )

    @api.depends('gold_rate', 'net_weight')
    def _compute_metal_amounts(self):
        for rec in self:
            if getattr(rec, 'is_scheme_line', False):
                rec.metal_amount = 0.0
                continue
            rec.metal_amount = rec.gold_rate * rec.net_weight


    @api.depends('metal_amount', 'mc_amount', 'sale_diamond_rate', 'sale_stone_rate','mc_amount_actual', 'other_weight_amount')
    def _compute_subtotal(self):
        for rec in self:
            if getattr(rec, 'is_scheme_line', False):
                rec.price_subtotal_actual = rec.price_subtotal_actual or 0.0
                rec.price_subtotal = rec.price_subtotal or 0.0
                continue
            rec.price_subtotal_actual = rec.metal_amount + rec.mc_amount + rec.sale_stone_rate + rec.sale_diamond_rate + rec.other_weight_amount
            rec.price_subtotal = rec.metal_amount + rec.mc_amount_actual + rec.sale_stone_rate + rec.sale_diamond_rate + rec.other_weight_amount

    @api.depends('price_subtotal', 'product_uom_qty')
    def _compute_price_unit(self):
        for rec in self:
            if getattr(rec, 'is_scheme_line', False):
                rec.price_unit = rec.price_unit or 0.0
                continue
            rec.price_unit = (rec.price_subtotal / rec.product_uom_qty) if rec.product_uom_qty else 0.0

    @api.depends('gold_rate', 'fine_weight')
    def _compute_metal_amount(self):
        for rec in self:
            if getattr(rec, 'is_scheme_line', False):
                rec.metal_amount = 0.0
                continue
            rec.metal_amount = rec.gold_rate * rec.fine_weight

    @api.depends('fine_weight', 'purity_id', 'order_id.purchase_order_id')
    def _compute_product_uom_qty(self):
        for rec in self:
            if getattr(rec, 'is_scheme_line', False):
                rec.product_uom_qty = rec.product_uom_qty or 1.0
                continue
            if (
                rec.order_id.purchase_order_id
                and rec.purity_id
                and rec.purity_id.percentage
                and rec.fine_weight
            ):
                # Only recompute from fine_weight when fine_weight is explicitly set
                # (e.g. Unfix scenario). Skip for regular lines where the user has
                # manually entered a gross weight — those should not be wiped out
                # simply because a purchase_order_id was linked via apply_old_gold.
                rec.product_uom_qty = rec.fine_weight / (rec.purity_id.percentage / 100.0)
            elif not rec.product_uom_qty:
                rec.product_uom_qty = 0.0

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        res['label_id'] = self.label_id.id if self.label_id else False
        res['purity_id'] = self.purity_id.id if self.purity_id else False

        return res

    @api.depends('product_id', 'company_id')
    def _compute_tax_id(self):
        super(SaleOrderLine, self)._compute_tax_id()
        for line in self:
            if getattr(line, 'is_scheme_line', False):
                line.tax_id = False

    def _prepare_procurement_values(self,group_id=False):
        values = super()._prepare_procurement_values(group_id)
        values['label_id'] = self.label_id.id if self.label_id else False
        values['purity_id'] = self.purity_id.id if self.purity_id else False

        return values

    def write(self, values):
        if self.filtered(lambda l: l.order_id.is_editing_main_so):
            self = self.with_context(mail_notrack=True, disable_so_chatter_track=True)
            
        # Intercept quantity reductions when editing the main order to safely reverse pickings 
        # BEFORE Odoo's native sale_stock validation triggers a UserError.
        if 'product_uom_qty' in values:
            for line in self:
                if line.order_id.is_editing_main_so:
                    new_qty = values['product_uom_qty']
                    if new_qty != line.product_uom_qty:
                        moves = line.move_ids.filtered(lambda m: m.state == 'done')
                        for move in moves:
                            old_qty = move.quantity
                            if old_qty == 0:
                                continue
                            
                            qty_diff = new_qty - old_qty
                            
                            # 1. Update move lines silently
                            for ml in move.move_line_ids:
                                self.env.cr.execute(
                                    "UPDATE stock_move_line SET quantity = %s WHERE id = %s",
                                    (new_qty, ml.id)
                                )
                            
                            # 2. Update move silently
                            self.env.cr.execute(
                                "UPDATE stock_move SET product_uom_qty = %s, quantity = %s WHERE id = %s",
                                (new_qty, new_qty, move.id)
                            )
                            
                            # 3. Update valuation silently
                            svls = move.stock_valuation_layer_ids
                            for svl in svls:
                                if svl.quantity != 0:
                                    ratio = new_qty / old_qty
                                    new_svl_qty = -new_qty if svl.quantity < 0 else new_qty
                                    new_svl_value = svl.value * ratio
                                    
                                    self.env.cr.execute(
                                        "UPDATE stock_valuation_layer SET quantity = %s, value = %s WHERE id = %s",
                                        (new_svl_qty, new_svl_value, svl.id)
                                    )
                                    
                                    if svl.account_move_id:
                                        self.env.cr.execute(
                                            "UPDATE account_move_line SET debit = debit * %s, credit = credit * %s, balance = balance * %s WHERE move_id = %s",
                                            (ratio, ratio, ratio, svl.account_move_id.id)
                                        )
                                        self.env.cr.execute(
                                            "UPDATE account_move SET amount_total = amount_total * %s, amount_total_signed = amount_total_signed * %s, amount_total_in_currency_signed = amount_total_in_currency_signed * %s WHERE id = %s",
                                            (ratio, ratio, ratio, svl.account_move_id.id)
                                        )
                            
                            # 4. Adjust Quants
                            self.env['stock.quant'].sudo()._update_available_quantity(
                                move.product_id,
                                move.location_id,
                                -qty_diff,
                            )
                            self.env['stock.quant'].sudo()._update_available_quantity(
                                move.product_id,
                                move.location_dest_id,
                                qty_diff,
                            )
                            
                        # Force flush and invalidation so Odoo's native checks see the new qty_delivered from DB
                        self.env.flush_all()
                        self.env.invalidate_all()
                        
                        import logging
                        _logger = logging.getLogger(__name__)
                        _logger.warning("==== SILENT SQL UPDATE DONE ====")
                        for m in line.move_ids:
                            _logger.warning(f"Move {m.id} qty: {m.quantity} state: {m.state}")
                        _logger.warning(f"Line {line.id} qty_delivered: {line.qty_delivered} product_uom_qty: {line.product_uom_qty} new_qty: {new_qty}")

        return super(SaleOrderLine, self).write(values)

    def _update_line_quantity(self, values):
        # Bypass the native sale_stock UserError check if editing the order
        if self.filtered(lambda l: l.order_id.is_editing_main_so):
            # Call the base sale module's method directly, bypassing sale_stock
            # sale_stock's override raises the UserError, but sale just posts a chatter message (which is disabled anyway).
            # To be safe, we just skip it entirely if we don't want chatter, 
            # or we can call super but catch the exception, but that's ugly.
            # Instead, we just do nothing since chatter is suppressed and we don't want tracking messages.
            return True
            
        return super(SaleOrderLine, self)._update_line_quantity(values)
