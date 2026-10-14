from odoo import models, fields, _, api
from odoo.exceptions import ValidationError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    sale_id = fields.Many2one(
        'sale.order',
        string='Related Sale Order'
    )
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', help="Pricelist for current order.")

    is_old_gold = fields.Boolean(
        string='Old Gold Purchase',
        default=False
    )
    is_sale_return_po = fields.Boolean(
        string='Sale Return',
        default=False
    )
    is_sale_return_shop = fields.Boolean(
        string='Sale Return Shop',
        default=False
    )
    unfix = fields.Boolean(
        string='Unfix',
        default=False
    )
    is_diamond_og = fields.Boolean(
        string='Diamond OG',
        default=False
    )
    is_purchase_expense = fields.Boolean(
        string='Purchase Expense',
        default=False
    )
    total_weight = fields.Float(
        string="Total Weight",
        compute="_compute_totals",
        digits=(16, 3),
        store=True
    )

    total_labelled = fields.Float(
        string="Total Labelled",
        compute="_compute_total_labelled",
        digits=(16, 3),
        store=True,
        compute_sudo=True,
    )

    total_unlabelled = fields.Float(
        string="Total Unlabelled",
        compute="_compute_unlabelled_totals",
        digits=(16, 3),
        store=True,
        compute_sudo=True,
    )
    label_ids = fields.One2many(
        'product.label',
        'purchase_id',
        string="Labels"
    )

    @api.onchange('is_old_gold')
    def _onchange_is_old_gold(self):
        if self.order_line:
            self.is_old_gold = not self.is_old_gold
            return {
                'warning': {
                    'title': _('Validation Error'),
                    'message': _('You cannot change the order type while order lines exist. Please remove existing lines first.')
                }
            }
        if self.is_old_gold:
            self.is_diamond_og = False
            self.is_purchase_expense = False
            self.unfix = False
            self.is_sale_return_shop = False
            
            # This will pop up an error if the product is completely missing from the database
            old_gold_product = self.env.ref('em_jewellery_management.product_old_gold')
            if old_gold_product and not any(line.product_id.id == old_gold_product.id for line in self.order_line):
                self.order_line = [(0, 0, {
                    'product_id': old_gold_product.id,
                    'product_template_id': old_gold_product.product_tmpl_id.id,
                    'name': old_gold_product.display_name,
                    'product_qty': 1.0,
                    'product_uom': old_gold_product.uom_po_id.id or old_gold_product.uom_id.id,
                    'price_unit': old_gold_product.standard_price or 0.0,
                })]

    @api.onchange('unfix')
    def _onchange_unfix(self):
        if self.order_line:
            self.unfix = not self.unfix
            return {
                'warning': {
                    'title': _('Validation Error'),
                    'message': _('You cannot change the order type while order lines exist. Please remove existing lines first.')
                }
            }
        if self.unfix:
            self.is_old_gold = False
            self.is_diamond_og = False
            self.is_purchase_expense = False
            self.is_sale_return_shop = False

    @api.onchange('is_sale_return_po')
    def _onchange_is_sale_return_po(self):
        if self.is_sale_return_po:
            self.is_old_gold = False
            self.is_diamond_og = False
            self.is_purchase_expense = False
            self.unfix = False
            self.is_sale_return_shop = False

    @api.onchange('is_sale_return_shop')
    def _onchange_is_sale_return_shop(self):
        if self.is_sale_return_shop:
            self.is_old_gold = False
            self.is_diamond_og = False
            self.is_purchase_expense = False
            self.unfix = False

    @api.onchange('is_diamond_og')
    def _onchange_is_diamond_og(self):
        if self.order_line:
            self.is_diamond_og = not self.is_diamond_og
            return {
                'warning': {
                    'title': _('Validation Error'),
                    'message': _('You cannot change the order type while order lines exist. Please remove existing lines first.')
                }
            }
        if self.is_diamond_og:
            self.is_old_gold = False
            self.is_purchase_expense = False
            self.unfix = False
            self.is_sale_return_shop = False

    @api.onchange('is_purchase_expense')
    def _onchange_is_purchase_expense(self):
        if self.order_line:
            self.is_purchase_expense = not self.is_purchase_expense
            return {
                'warning': {
                    'title': _('Validation Error'),
                    'message': _('You cannot change the order type while order lines exist. Please remove existing lines first.')
                }
            }
        if self.is_purchase_expense:
            self.is_old_gold = False
            self.is_diamond_og = False
            self.unfix = False
            self.is_sale_return_shop = False

    @api.constrains('order_line', 'is_old_gold', 'is_diamond_og', 'is_purchase_expense')
    def _check_order_lines_consistency(self):
        for order in self:
            if not order.order_line:
                continue
            if order.is_old_gold:
                invalid_lines = order.order_line.filtered(
                    lambda l: not (l.product_id.is_old_gold or (l.product_template_id and l.product_template_id.is_old_gold)) or
                              (l.product_id.is_diamond_og or (l.product_template_id and l.product_template_id.is_diamond_og)) or
                              l.product_id.detailed_type in ('consu', 'service')
                )
                if invalid_lines:
                    names = ', '.join((invalid_lines.mapped('product_id.display_name') or invalid_lines.mapped('product_template_id.name')))
                    raise ValidationError(_('This order is set to OG (Old Gold), but contains non-Old Gold products (%s). Please remove them before saving.') % names)
            elif order.is_diamond_og:
                invalid_lines = order.order_line.filtered(
                    lambda l: not (l.product_id.is_diamond_og or (l.product_template_id and l.product_template_id.is_diamond_og)) or
                              (l.product_id.is_old_gold or (l.product_template_id and l.product_template_id.is_old_gold)) or
                              l.product_id.detailed_type in ('consu', 'service')
                )
                if invalid_lines:
                    names = ', '.join((invalid_lines.mapped('product_id.display_name') or invalid_lines.mapped('product_template_id.name')))
                    raise ValidationError(_('This order is set to Diamond OG, but contains non-Diamond OG products (%s). Please remove them before saving.') % names)
            elif order.is_purchase_expense:
                invalid_lines = order.order_line.filtered(lambda l: l.product_id and l.product_id.detailed_type not in ('consu', 'service'))
                if invalid_lines:
                    names = ', '.join((invalid_lines.mapped('product_id.display_name') or invalid_lines.mapped('product_template_id.name')))
                    raise ValidationError(_('This order is set to Purchase Expense, but contains non-Expense products (%s). Please remove them before saving.') % names)
            else:
                invalid_lines = order.order_line.filtered(
                    lambda l: (l.product_id.is_old_gold or (l.product_template_id and l.product_template_id.is_old_gold)) or
                              (l.product_id.is_diamond_og or (l.product_template_id and l.product_template_id.is_diamond_og)) or
                              l.product_id.detailed_type in ('consu', 'service')
                )
                if invalid_lines:
                    names = ', '.join((invalid_lines.mapped('product_id.display_name') or invalid_lines.mapped('product_template_id.name')))
                    raise ValidationError(_('This standard Purchase Order contains Old Gold, Diamond OG, or Expense products (%s). Please remove them before saving.') % names)

    @api.constrains('is_old_gold', 'is_diamond_og', 'is_purchase_expense', 'unfix')
    def _check_mutually_exclusive_types(self):
        for order in self:
            flags = [order.is_old_gold, order.is_diamond_og, order.is_purchase_expense, order.unfix]
            if sum(bool(f) for f in flags) > 1:
                raise ValidationError(_('A Purchase Order cannot have multiple order types selected simultaneously (OG, Diamond OG, Purchase Expense, Unfix). Please select only one.'))

    @api.model
    def _clean_exclusive_type_flags(self, vals):
        type_flags = ['is_old_gold', 'is_diamond_og', 'is_purchase_expense', 'unfix']
        active_flags = [f for f in type_flags if vals.get(f)]
        if len(active_flags) > 1:
            raise ValidationError(_('You cannot enable multiple order types at the same time (%s).') % ', '.join(active_flags))
        if active_flags:
            chosen = active_flags[0]
            for other in type_flags:
                if other != chosen:
                    vals[other] = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._clean_exclusive_type_flags(vals)
        return super(PurchaseOrder, self).create(vals_list)

    def write(self, vals):
        self._clean_exclusive_type_flags(vals)
        type_flags = {
            'is_old_gold': 'OG',
            'is_diamond_og': 'Diamond OG',
            'is_purchase_expense': 'Purchase Expense',
            'unfix': 'Unfix',
        }
        for flag, label in type_flags.items():
            if flag in vals:
                for order in self:
                    if order.order_line and getattr(order, flag) != vals[flag]:
                        raise ValidationError(_('You cannot change the %s flag while order lines exist. Please remove existing lines first.') % label)
        return super(PurchaseOrder, self).write(vals)


    def action_create_sale_order(self):
        self.ensure_one()

        SaleOrder = self.env['sale.order']

        # 🔹 Check if already created
        existing_so = SaleOrder.search([
            ('purchase_order_id', '=', self.id)
        ], limit=1)

        if existing_so:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Sale Order',
                'res_model': 'sale.order',
                'res_id': existing_so.id,
                'view_mode': 'form',
                'target': 'current',
            }

        # 🔹 Prepare order line
        product = self.env.ref('em_jewellery_management.product_bullion_gold')

        total_weight = sum(
            self.order_line.mapped('qty_received')
        )
        total_fine = sum(
            self.order_line.mapped('total_fine')
        )
        

        order_lines = [(0, 0, {
            'product_id': product.id,
            # 'product_uom_qty': total_fine,
            'fine_weight': total_fine,
            'name': product.display_name,
            'price_unit': product.list_price or 0.0,
        })]

        # 🔹 Create Sale Order
        sale_order = SaleOrder.create({
            'purchase_order_id': self.id,
            'origin': self.name,
            'partner_id': self.partner_id.id,
            'order_line': order_lines,
            'unfix': self.unfix,
        })
        self.sale_id = sale_order.id

        # 🔹 Open created order
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sale Order',
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.depends(
        'order_line.qty_received',
    )
    def _compute_totals(self):
        for order in self:
            order.total_weight = sum(
                order.order_line.mapped('qty_received')
            )

    @api.depends('label_ids.sale_gross_weight')
    def _compute_total_labelled(self):
        for order in self:
            order.total_labelled = sum(
                order.label_ids.mapped('sale_gross_weight')
            )

    @api.depends(
        'total_labelled',
        'total_weight'
    )
    def _compute_unlabelled_totals(self):
        for order in self:

            order.total_unlabelled = order.total_weight - order.total_labelled

    def button_confirm(self):
        for order in self:
            if order.is_old_gold:
                invalid_lines = order.order_line.filtered(
                    lambda l: not (l.product_id.is_old_gold or (l.product_template_id and l.product_template_id.is_old_gold)) or
                              (l.product_id.is_diamond_og or (l.product_template_id and l.product_template_id.is_diamond_og)) or
                              l.product_id.detailed_type in ('consu', 'service')
                )
                if invalid_lines:
                    names = ', '.join((invalid_lines.mapped('product_id.display_name') or invalid_lines.mapped('product_template_id.name')))
                    raise ValidationError(_('Cannot confirm order: This is an Old Gold purchase, but contains non-Old Gold products (%s). Please remove them first.') % names)
            elif order.is_diamond_og:
                invalid_lines = order.order_line.filtered(
                    lambda l: not (l.product_id.is_diamond_og or (l.product_template_id and l.product_template_id.is_diamond_og)) or
                              (l.product_id.is_old_gold or (l.product_template_id and l.product_template_id.is_old_gold)) or
                              l.product_id.detailed_type in ('consu', 'service')
                )
                if invalid_lines:
                    names = ', '.join((invalid_lines.mapped('product_id.display_name') or invalid_lines.mapped('product_template_id.name')))
                    raise ValidationError(_('Cannot confirm order: This is a Diamond OG purchase, but contains non-Diamond OG products (%s). Please remove them first.') % names)
            elif order.is_purchase_expense:
                invalid_lines = order.order_line.filtered(lambda l: l.product_id and l.product_id.detailed_type not in ('consu', 'service'))
                if invalid_lines:
                    names = ', '.join((invalid_lines.mapped('product_id.display_name') or invalid_lines.mapped('product_template_id.name')))
                    raise ValidationError(_('Cannot confirm order: This is a Purchase Expense order, but contains non-Expense products (%s). Please remove them first.') % names)
            else:
                invalid_lines = order.order_line.filtered(
                    lambda l: (l.product_id.is_old_gold or (l.product_template_id and l.product_template_id.is_old_gold)) or
                              (l.product_id.is_diamond_og or (l.product_template_id and l.product_template_id.is_diamond_og)) or
                              l.product_id.detailed_type in ('consu', 'service')
                )
                if invalid_lines:
                    names = ', '.join((invalid_lines.mapped('product_id.display_name') or invalid_lines.mapped('product_template_id.name')))
                    raise ValidationError(_('Cannot confirm order: Standard purchase order contains Old Gold, Diamond OG, or Expense products (%s). Please remove them first.') % names)
        res = super(PurchaseOrder, self).button_confirm()
        for order in self:
            if order.is_old_gold:
                dest_loc_id = order._get_destination_location()
                location_id = dest_loc_id if dest_loc_id else (order.branch_id.old_gold_location_id.id or self.env.user.branch_id.old_gold_location_id.id)

                # Ensure each line has a purity before creating old.gold.purchase
                missing_purity = order.order_line.filtered(lambda l: not l.purity_id and not l.product_id.purity_id)
                if missing_purity:
                    names = ', '.join(missing_purity.mapped('product_id.display_name'))
                    raise ValidationError(_('Please select Purity for Old Gold lines (%s) before confirming.') % names)

            # ------------------------------------------------
            # 1️⃣ CREATE OLD GOLD PURCHASE (LOGICAL RECORD)
            # ------------------------------------------------
                self.env['old.gold.purchase'].with_context(skip_old_gold_amount_compute=True).create({
                    'partner_id': order.partner_id.id,
                    'date': fields.Date.today(),
                    'branch_location_id': location_id,
                    'purchase_order_id': order.id,
                    'branch_id': order.branch_id.id or self.env.user.branch_id.id,
                    'old_gold_line_ids': [
                        (0, 0, {
                            'purity_id': (l.purity_id or l.product_id.purity_id).id,
                            'gross_weight': l.product_qty,
                            'stone_weight': l.stone_weight,
                            'amount': l.price_subtotal,
                            'rate': l.price_unit,
                        }) for l in order.order_line
                    ],
                })
        return res

    def _get_destination_location(self):
        self.ensure_one()
        if self.is_old_gold and self.branch_id.old_gold_location_id:
            return self.branch_id.old_gold_location_id.id
        if self.is_diamond_og and self.branch_id.diamond_og_location_id:
            return self.branch_id.diamond_og_location_id.id
        if self.is_sale_return_po and self.branch_id.sr_location_id:
            return self.branch_id.sr_location_id.id
        return super()._get_destination_location()
    def _prepare_picking(self):
        vals = super()._prepare_picking()
        vals['branch_id'] = self.branch_id.id
        
        if self.is_old_gold and self.branch_id.old_gold_location_id:
            vals['location_dest_id'] = self.branch_id.old_gold_location_id.id
        elif self.is_diamond_og and self.branch_id.diamond_og_location_id:
            vals['location_dest_id'] = self.branch_id.diamond_og_location_id.id
        elif self.is_sale_return_po and self.branch_id.sr_location_id:
            vals['location_dest_id'] = self.branch_id.sr_location_id.id
            
        return vals

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals['unfix'] = self.unfix
        return vals

    def action_create_bill_and_pay(self):
        for order in self:

            # 1️⃣ Create Vendor Bill
            action = order.action_create_invoice()

            # Get created bill
            bill = order.invoice_ids.filtered(lambda m: m.state == 'draft')


            if not bill:
                continue
            bill.invoice_date = fields.Date.context_today(self)
            bill.date = fields.Date.context_today(self)
            # 2️⃣ Post Bill
            bill.action_post()

        return True
