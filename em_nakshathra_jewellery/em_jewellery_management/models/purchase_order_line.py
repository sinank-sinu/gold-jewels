from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    product_template_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='po_line_ptav_rel',
        string="Product Attribute Values",
        ondelete='restrict'
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='po_line_no_variant_ptav_rel',
        string="Extra Product Attribute Values",
        ondelete='restrict'
    )
    product_custom_attribute_value_ids = fields.Many2many(
        comodel_name='product.attribute.custom.value',
        relation='po_line_custom_ptav_rel',
        string="Custom Product Attribute Values"
    )
    is_configurable_product = fields.Boolean(
        string="Is the product configurable?",
        related='product_template_id.has_configurable_attributes'
    )
    product_type = fields.Selection(
        related='product_id.detailed_type'
    )
    pricelist_id = fields.Many2one(
        related='order_id.pricelist_id',
        string='Pricelist',
        readonly=True
    )
    product_uom_qty = fields.Float(
        related='product_qty',
        string="Product Quantity",
        readonly=False,
        digits=(16, 3),
    )
    product_qty = fields.Float(digits=(16, 3))

    sale_return_line_id = fields.Many2one('sale.return.line', string="Sale Return Line", ondelete='set null')
    is_diamond_og = fields.Boolean(related='order_id.is_diamond_og', string="Is Diamond OG")
    is_old_gold = fields.Boolean(related='order_id.is_old_gold', string="Is OG")
    purity_id = fields.Many2one('gold.purity', string="Purity")
    fine_weight = fields.Float(string="Fine Weight  (g)",compute="_compute_fine_weight",digits=(16, 3))
    metal_amount = fields.Float(string="Metal Amount",compute="_compute_metal_amount", digits=(16, 3))
    mc_fine = fields.Float(string="MC Fine Wt", compute="_compute_purchase_mc_fine",digits=(16, 3))
    gold_rate =fields.Float(string="Rate(g)", digits=(16, 3))
    mc_percent = fields.Float(string="MC%", digits=(16, 3))
    net_weight = fields.Float(string="Net Weight (g)",compute="_compute_net_weight",digits=(16, 3))
    stone_weight = fields.Float(string="Stone Weight (g)",digits=(16, 3))
    diamond_weight_gm = fields.Float(
        string="Diamond Weight (g)",
        digits=(16, 3)
    )
    diamond_weight_ct = fields.Float(
        string="Diamond Weight (ct)",
        digits=(16, 3)
    )
    mc_amount = fields.Float(
        string="MC Amount",
        compute="_compute_purchase_mc_amount",
        digits=(16, 3),
        store=True
    )
    stone_rate = fields.Float(string="Stone Amount", digits=(16, 3))
    diamond_rate = fields.Float(string="Diamond Amount", digits=(16, 3))
    gross_weight = fields.Float(string="Gross Weight (g)",digits=(16, 3))
    price_unit = fields.Float(
        string='Unit Price', required=True, digits=(16, 3),
        compute="_compute_price_unit", readonly=False, store=True)
    price_subtotal = fields.Monetary(compute='_compute_subtotal', string='Subtotal', store=True)

    @api.depends('product_qty', 'price_unit', 'taxes_id', 'discount', 'sale_return_line_id', 'sale_return_line_id.amount', 'price_subtotal')
    def _compute_amount(self):
        super()._compute_amount()
        for line in self:
            if line.sale_return_line_id:
                line.price_subtotal = line.sale_return_line_id.amount
            line.price_total = line.price_subtotal + line.price_tax



    purchase_price_per_gram = fields.Float(string="Purchase fine Rate / gram",digits=(16, 3))
    purchase_making_charge_amount = fields.Float(
        string="MC Amount",
        digits=(16, 3)
    )
    purchase_making_charge_value = fields.Float(string="Amount(mc)", digits=(16, 3))

    purchase_making_charge_type = fields.Selection([
        ('percent', 'Percentage'),
        ('amount', 'Amount'),
        ('rate_per_gram', 'Rate Per Gram')

    ], string="MC Type", default='percent')
    total_fine = fields.Float(string="Total Fine", compute="_compute_total_fine",digits=(16, 3))

    rate_value = fields.Float(string="Rate Value", digits=(16, 3))




    @api.depends(
        'product_qty',
        'stone_weight',
        'diamond_weight_gm',
    )
    def _compute_net_weight(self):
        for rec in self:
            rec.net_weight = (
                    rec.product_qty
                    - rec.stone_weight
                    - rec.diamond_weight_gm
            )

    @api.depends('net_weight', 'purity_id')
    def _compute_fine_weight(self):
        for rec in self:
            rec.fine_weight = rec.net_weight * (rec.purity_id.percentage)/100

    @api.depends('gold_rate', 'fine_weight', 'net_weight', 'order_id.is_sale_return_shop', 'order_id.is_sale_return_po')
    def _compute_metal_amount(self):
        for rec in self:
            gold_rate = rec.gold_rate or 0.0
            if rec.order_id and (rec.order_id.is_sale_return_shop or rec.order_id.is_sale_return_po):
                rec.metal_amount = gold_rate * (rec.net_weight or 0.0)
            else:
                rec.metal_amount = gold_rate * (rec.fine_weight or 0.0)

    @api.depends('net_weight','mc_percent','purchase_making_charge_type')
    def _compute_purchase_mc_fine(self):
        for rec in self:
            if rec.purchase_making_charge_type == 'percent':
                rec.mc_fine = rec.net_weight * (rec.mc_percent/ 100)
            else:
                rec.mc_fine = 0.0

    @api.depends(
        'mc_fine', 'gold_rate', 'purchase_making_charge_type', 'rate_value', 'purchase_making_charge_value'
    )
    def _compute_purchase_mc_amount(self):
        for rec in self:
            if rec.purchase_making_charge_type == 'percent':
                rec.mc_amount = rec.mc_fine * rec.gold_rate
            elif rec.purchase_making_charge_type == 'amount':
                rec.mc_amount = rec.purchase_making_charge_value
            # from jafar side
            elif rec.purchase_making_charge_type == 'rate_per_gram':
                rec.mc_amount = rec.net_weight * rec.rate_value
            else:
                rec.mc_amount = rec.net_weight * rec.gold_rate

    def _uses_jewellery_pricing(self):
        self.ensure_one()
        return bool(
            self.sale_return_line_id
            or self.metal_amount
            or self.mc_amount
            or self.stone_rate
            or self.diamond_rate
        )

    @api.depends('metal_amount', 'mc_amount', 'diamond_rate', 'stone_rate', 'sale_return_line_id', 'sale_return_line_id.amount', 'price_unit', 'product_qty', 'price_tax')
    def _compute_subtotal(self):
        jewellery_lines = self.filtered(lambda line: line._uses_jewellery_pricing())
        standard_lines = self - jewellery_lines
        if standard_lines:
            super(PurchaseOrderLine, standard_lines)._compute_amount()

        for rec in jewellery_lines:
            if rec.sale_return_line_id:
                rec.price_subtotal = rec.sale_return_line_id.amount
            else:
                rec.price_subtotal = rec.metal_amount + rec.mc_amount + rec.stone_rate + rec.diamond_rate
            rec.price_total = rec.price_subtotal + (rec.price_tax or 0.0)

    @api.depends('price_subtotal', 'product_qty', 'product_uom_qty', 'order_id.is_purchase_expense')
    def _compute_price_unit(self):
        for rec in self:
            if rec._uses_jewellery_pricing():
                rec.price_unit = (rec.price_subtotal / rec.product_qty) if rec.product_qty else 0.0

    @api.onchange('product_qty', 'price_unit')
    def _onchange_expense_price_or_qty(self):
        if self.order_id and self.order_id.is_purchase_expense:
            self.price_subtotal = (self.price_unit or 0.0) * (self.product_qty or 0.0)

    def _prepare_stock_moves(self, picking):
        moves = super()._prepare_stock_moves(picking)

        for values in moves:
            values['purity_id'] = self.purity_id.id if self.purity_id else False

        return moves

    @api.depends('mc_fine', 'fine_weight')
    def _compute_total_fine(self):
        for rec in self:
            rec.total_fine = rec.mc_fine + rec.fine_weight

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('product_template_id') and not vals.get('product_id'):
                tmpl = self.env['product.template'].browse(vals['product_template_id'])
                variant = tmpl.product_variant_id or tmpl.product_variant_ids[:1]
                if variant:
                    vals['product_id'] = variant.id
                    if 'product_uom' not in vals:
                        vals['product_uom'] = (variant.uom_po_id or variant.uom_id).id
                    if 'name' not in vals:
                        vals['name'] = variant.display_name
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('product_template_id') and not vals.get('product_id'):
            tmpl = self.env['product.template'].browse(vals['product_template_id'])
            variant = tmpl.product_variant_id or tmpl.product_variant_ids[:1]
            if variant:
                vals['product_id'] = variant.id
        return super().write(vals)

    @api.onchange('diamond_weight_ct')
    def _onchange_diamond_weight_ct(self):
        for line in self:
            line.diamond_weight_gm = line.diamond_weight_ct * 0.2

    @api.onchange('product_template_id')
    def _onchange_product_template_id(self):
        if self.product_template_id and (not self.product_id or self.product_id.product_tmpl_id != self.product_template_id):
            variant = self.product_template_id.product_variant_id or self.product_template_id.product_variant_ids[:1]
            if variant:
                self.product_id = variant
                self.product_uom = variant.uom_po_id or variant.uom_id
                self.name = variant.display_name
                if not self.price_unit:
                    self.price_unit = variant.standard_price or 0.0
                if not self.product_qty:
                    self.product_qty = 1.0
                if self.order_id and self.order_id.is_purchase_expense:
                    self.price_subtotal = (self.price_unit or 0.0) * (self.product_qty or 1.0)

        if self.product_template_id:
            none_values = self.product_template_id.valid_product_template_attribute_line_ids.mapped(
                'product_template_value_ids'
            ).filtered(
                lambda ptav: ptav.ptav_active
                and (ptav.name or '').strip().casefold() == 'none'
            )
            self.product_template_attribute_value_ids = none_values.filtered(
                lambda ptav: ptav.attribute_id.create_variant != 'no_variant'
            )
            self.product_no_variant_attribute_value_ids = none_values.filtered(
                lambda ptav: ptav.attribute_id.create_variant == 'no_variant'
            )

    @api.onchange('product_id')
    def _onchange_purchase_product_id(self):
        if self.product_id:
            if self.product_id.purity_id:
                if self.order_id.is_diamond_og and not self.product_id.purity_id.is_diamond_og:
                    self.purity_id = False
                elif self.order_id.is_old_gold and self.product_id.purity_id.is_diamond_og:
                    self.purity_id = False
                else:
                    self.purity_id = self.product_id.purity_id.id
            else:
                self.purity_id = False
            if not self.product_uom:
                self.product_uom = self.product_id.uom_po_id or self.product_id.uom_id
            if not self.name:
                self.name = self.product_id.display_name
            if not self.price_unit and self.product_id.standard_price:
                self.price_unit = self.product_id.standard_price
            if self.order_id.is_old_gold or self.order_id.is_diamond_og:
                self.purchase_making_charge_type = 'rate_per_gram'

        for line in self:
            if not line.order_id or not line.product_id:
                continue
            is_og = line.product_id.is_old_gold or (line.product_template_id and line.product_template_id.is_old_gold)
            is_dog = line.product_id.is_diamond_og or (line.product_template_id and line.product_template_id.is_diamond_og)
            is_exp = line.product_id.detailed_type in ('consu', 'service')

            # 1. Purchase Expense mode: Only Consumable and Service products allowed
            if line.order_id.is_purchase_expense:
                if not is_exp:
                    line.product_id = False
                    return {
                        'warning': {
                            'title': _('Invalid Product Selection'),
                            'message': _('Only Consumable and Service products can be selected when Purchase Expense is enabled!')
                        }
                    }

            # 2. Old Gold mode: Only Old Gold products allowed
            elif line.order_id.is_old_gold:
                if not is_og or is_dog:
                    line.product_id = False
                    return {
                        'warning': {
                            'title': _('Invalid Product Selection'),
                            'message': _('You can only select Old Gold products when the OG toggle is turned on!')
                        }
                    }

            # 3. Diamond OG mode: Only Diamond OG products allowed
            elif line.order_id.is_diamond_og:
                if not is_dog or is_og:
                    line.product_id = False
                    return {
                        'warning': {
                            'title': _('Invalid Product Selection'),
                            'message': _('You can only select Diamond OG products when the Diamond OG toggle is turned on!')
                        }
                    }

            # 4. Standard mode: No Old Gold, No Diamond OG
            else:
                if is_og:
                    line.product_id = False
                    return {
                        'warning': {
                            'title': _('Invalid Product Selection'),
                            'message': _('You cannot select Old Gold products in a standard Purchase Order!')
                        }
                    }
                if is_dog:
                    line.product_id = False
                    return {
                        'warning': {
                            'title': _('Invalid Product Selection'),
                            'message': _('You cannot select Diamond OG products in a standard Purchase Order!')
                        }
                    }

    @api.constrains('product_id')
    def _check_product_type_and_og(self):
        for line in self:
            if not line.order_id or not line.product_id:
                continue
            is_og = line.product_id.is_old_gold or (line.product_template_id and line.product_template_id.is_old_gold)
            is_dog = line.product_id.is_diamond_og or (line.product_template_id and line.product_template_id.is_diamond_og)
            is_exp = line.product_id.detailed_type in ('consu', 'service')

            if line.order_id.is_purchase_expense:
                if not is_exp:
                    raise ValidationError(_('In Purchase Expense mode, only Consumable and Service products are allowed.'))
            elif line.order_id.is_old_gold:
                if not is_og or is_dog:
                    raise ValidationError(_('In Old Gold mode, only Old Gold products are allowed.'))
            elif line.order_id.is_diamond_og:
                if not is_dog or is_og:
                    raise ValidationError(_('In Diamond OG mode, only Diamond OG products are allowed.'))
            else:
                if is_og:
                    raise ValidationError(_('Old Gold products cannot be purchased in a standard Purchase Order.'))
                if is_dog:
                    raise ValidationError(_('Diamond OG products cannot be purchased in a standard Purchase Order.'))

    @api.onchange('purity_id')
    def _onchange_purity_id_diamond_og(self):
        for line in self:
            if not line.purity_id or not line.order_id:
                continue
            if line.order_id.is_diamond_og and not line.purity_id.is_diamond_og:
                p_name = line.purity_id.name
                line.purity_id = False
                return {
                    'warning': {
                        'title': _('Invalid Purity Selection'),
                        'message': _('Purity "%s" is not a Diamond OG purity! Only Diamond OG purities can be selected when Diamond OG is enabled.') % p_name
                    }
                }
            elif line.order_id.is_old_gold and line.purity_id.is_diamond_og:
                p_name = line.purity_id.name
                line.purity_id = False
                return {
                    'warning': {
                        'title': _('Invalid Purity Selection'),
                        'message': _('Purity "%s" is a Diamond OG purity! It cannot be selected in a regular Old Gold (OG) Purchase Order.') % p_name
                    }
                }

    @api.constrains('purity_id', 'order_id')
    def _check_purity_diamond_og(self):
        for line in self:
            if not line.order_id or not line.purity_id:
                continue
            if line.order_id.is_diamond_og and not line.purity_id.is_diamond_og:
                raise ValidationError(_('In Diamond OG mode, only Diamond OG purities are allowed (purity: %s).') % line.purity_id.name)
            elif line.order_id.is_old_gold and line.purity_id.is_diamond_og:
                raise ValidationError(_('Diamond OG purities (such as %s) cannot be selected in a regular Old Gold (OG) Purchase Order.') % line.purity_id.name)
