from odoo import fields, models
from odoo import api


class ProductLabel(models.Model):
    _inherit = 'product.label'


    product_id = fields.Many2one(
        'product.product',
        ondelete='cascade', string="Product Variant", 
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string="Product", store=True
    )


    # @api.onchange('product_id')
    # def _onchange_product_id_set_template(self):
    #     for rec in self:
    #         if rec.product_id:
    #             rec.product_tmpl_id = rec.product_id.product_tmpl_id
    #         else:
    #             rec.product_tmpl_id = False

    # @api.onchange('product_tmpl_id')
    # def _onchange_product_tmpl_id_set_template(self):
    #     for rec in self:
    #         if rec.product_tmpl_id:
    #             rec.product_id = rec.product_tmpl_id
    #         else:
    #             rec.product_id = False


