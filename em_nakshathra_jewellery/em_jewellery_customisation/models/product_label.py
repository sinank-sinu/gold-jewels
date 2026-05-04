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
    partner_id = fields.Many2one('res.partner')
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
    
    @api.onchange('purchase_id')
    def _onchange_purchase_id(self):
        if self.purchase_id:
            first_line = self.purchase_id.order_line[:1]  # safely take first line
            if first_line and first_line.purity_id:
                self.purity_id = first_line.purity_id.id
                
    @api.onchange('product_template_id')
    def _onchange_product_template(self):
        if self.product_template_id:
            self.product_id = False
          

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