from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _get_branch_domain(self):
        """methode to get branch domain"""
        company = self.env.company
        branch_ids = self.env.user.branch_ids
        branch = branch_ids.filtered(
            lambda branch: branch.company_id == company)
        return [('id', 'in', branch.ids)]

    branch_id = fields.Many2one('res.branch', string='Branch', store=True,
                                domain=_get_branch_domain,
                                default=lambda self: self.env.user.branch_id.id)
    purity_id = fields.Many2one('gold.purity', string="Purity")
    total_grams = fields.Float(string="Total Grams", digits=(16, 3))
    product_template_id = fields.Many2one('product.template', string="Product")

    product_template_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        'mrp_prod_ptav_rel',
        string="Product Attribute Values"
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        'mrp_prod_no_variant_ptav_rel',
        string="Extra Attribute Values"
    )
    product_custom_attribute_value_ids = fields.One2many(
        'product.attribute.custom.value',
        'mrp_production_id',
        string="Custom Values"
    )
    is_configurable_product = fields.Boolean(
        related='product_template_id.has_configurable_attributes'
    )

    # Dummy fields REQUIRED by sol_product_many2one widget
    product_uom = fields.Many2one('uom.uom', related='product_id.uom_id', readonly=True)
    product_uom_qty = fields.Float(related='product_qty', readonly=False)
    pricelist_id = fields.Many2one('product.pricelist')
    partner_id = fields.Many2one('res.partner')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    date_order = fields.Datetime(default=fields.Datetime.now)
    order_id = fields.Many2one('mrp.production', string="Dummy Order")
    order_line = fields.One2many('mrp.production', 'id', string="Dummy Order Line")

    @api.onchange('product_template_id')
    def _onchange_product_template_id(self):
        if self.product_template_id:
            if self.product_id and self.product_id.product_tmpl_id != self.product_template_id:
                self.product_id = False


class ProductAttributeCustomValue(models.Model):
    _inherit = 'product.attribute.custom.value'

    mrp_production_id = fields.Many2one(
        'mrp.production',
        string="Mrp Production",
        ondelete='cascade'
    )
