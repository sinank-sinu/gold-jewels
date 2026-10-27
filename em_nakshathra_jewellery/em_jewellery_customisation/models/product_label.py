from odoo import fields, models
from odoo import api


class ProductLabel(models.Model):
    _inherit = 'product.label'


    product_id = fields.Many2one(
        'product.product',
        ondelete='cascade', string="Product Variant", 
    )
    product_template_id = fields.Many2one(
        'product.template',
        string="Product"
    )
    purchase_id = fields.Many2one(
        'purchase.order',
        string="Purchase Order",
        domain="[('state', '=', 'purchase'), ('order_line.product_template_id', '=', product_template_id)]"
    )
    fine_rate_id = fields.Many2one('fine.rate.master')
    product_template_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        'product_label_ptav_rel',
        string="Product Attribute Values"
    )

    product_no_variant_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        'product_label_no_variant_ptav_rel',
        string="Extra Attribute Values"
    )

    product_custom_attribute_value_ids = fields.One2many(
        'product.attribute.custom.value',
        'product_label_id',   # 👈 we will add this
        string="Custom Values"
    )

    is_configurable_product = fields.Boolean(
        related='product_template_id.has_configurable_attributes'
    )

    # REQUIRED by widget
    product_uom_qty = fields.Float(
        string="Quantity",
        default=1
    )
    product_uom = fields.Many2one(
        'uom.uom',
        related='product_id.uom_id',
        string="Unit of Measure",
        readonly=True
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company
    )

    pricelist_id = fields.Many2one('product.pricelist')
    partner_id = fields.Many2one(
        'res.partner',
        string="Vendor",
        compute='_compute_partner_id',
        store=True,
        readonly=False,
        precompute=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id'
    )

    date_order = fields.Datetime(default=fields.Datetime.now)

    order_id = fields.Many2one(
        'product.label',
        string="Order"
    )
    order_line = fields.One2many(
        'product.label',
        'id',
        string="Dummy Order Line"
    )
    product_custom_attribute_value_ids = fields.One2many(
        'product.attribute.custom.value',
        'product_label_id',   
        string="Custom Values"
    )

    @api.onchange('job_work_id')
    def _onchange_job_work_id(self):
        if self.job_work_id:
            first_line = self.job_work_id.job_work_line_ids[:1]  # safely take first line
            if first_line and first_line.purity_id:
                self.purity_id = first_line.purity_id.id
            
            # Fetch making charge from the related receive voucher
            receive_vouchers = self.job_work_id.receive_voucher_ids.filtered(lambda r: r.state != 'done')
            if not receive_vouchers:
                receive_vouchers = self.job_work_id.receive_voucher_ids
                
            if receive_vouchers:
                rv = receive_vouchers[-1] # Take the latest one
                self.purchase_making_charge_type = rv.making_charge_type
                if rv.making_charge_type == 'percent':
                    self.purchase_making_charge_value = rv.mc_percent
                elif rv.making_charge_type == 'amount':
                    self.purchase_making_charge_value = rv.making_charge_value
                elif rv.making_charge_type == 'rate_per_gram':
                    self.purchase_making_charge_value = rv.rate_value
    
    @api.depends('purchase_id.partner_id')
    def _compute_partner_id(self):
        for rec in self:
            if rec.purchase_id and rec.purchase_id.partner_id:
                rec.partner_id = rec.purchase_id.partner_id
            elif not rec.partner_id:
                rec.partner_id = False

    @api.onchange('purchase_id')
    def _onchange_purchase_id(self):
        if self.product_id:
            self.purity_id = self.product_id.purity_id
        if self.purchase_id and self.purchase_id.partner_id:
            self.partner_id = self.purchase_id.partner_id
        elif not self.purchase_id:
            self.partner_id = False

    @api.depends('product_template_id')
    def _compute_unlabelled_weight(self):
        super()._compute_unlabelled_weight()

    @api.constrains('product_template_id')
    def _check_unlabelled_weight_limit_template(self):
        self._check_unlabelled_weight_limit()

    @api.onchange('product_template_id')
    def _onchange_product_template(self):
        if self.product_template_id:
            self.product_id = False
            self.product_template_attribute_value_ids = (
                self.product_template_id.attribute_line_ids
                .mapped('product_template_value_ids')
                ._only_active()
                .filtered(lambda ptav: ptav.name.strip().casefold() == 'none')
            )
            if self.purchase_id and self.product_template_id not in self.purchase_id.order_line.product_template_id:
                self.purchase_id = False
        else:
            self.product_template_attribute_value_ids = False
        self._compute_unlabelled_weight()
        return self._onchange_check_unlabelled_weight_limit()
          

    @api.model
    def create(self, vals):
        label_date = fields.Date.context_today(self)

        fine_rate = self.env['fine.rate.master'].search([
            ('date', '=', label_date)
        ], limit=1)

        if fine_rate:
            vals['fine_rate_id'] = fine_rate.id
            vals['purchase_price_per_gram'] = fine_rate.fine_rate  

        return super().create(vals)



class ProductAttributeCustomValue(models.Model):
    _inherit = 'product.attribute.custom.value'

    product_label_id = fields.Many2one(
        'product.label',
        string="Product Label",
        ondelete='cascade'
    )