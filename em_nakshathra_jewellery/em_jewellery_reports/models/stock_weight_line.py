from odoo import models, fields


class JewelleryStockWeightLine(models.TransientModel):
    _name = 'jewellery.stock.weight.line'
    _description = 'Jewellery Stock Weight Line'

    wizard_id = fields.Many2one('jewellery.report.wizard', string="Wizard", ondelete='cascade')
    product_id = fields.Many2one('product.product', string="Product")
    category_id = fields.Many2one('product.category', related='product_id.categ_id', string="Category", store=True)
    purity_id = fields.Many2one('gold.purity', string="Purity")
    location_id = fields.Many2one('stock.location', string="Location")
    branch_id = fields.Many2one('res.branch', string="Branch")

    quantity = fields.Float(string="Qty in Stock", digits=(16, 0))
    gross_weight = fields.Float(string="Total Gross Wt (g)", digits=(16, 3))
    net_weight = fields.Float(string="Total Net Wt (g)", digits=(16, 3))
    diamond_weight = fields.Float(string="Total Diamond Wt (g)", digits=(16, 3))
    stone_weight = fields.Float(string="Total Stone Wt (g)", digits=(16, 3))
    other_weight = fields.Float(string="Total Other Wt (g)", digits=(16, 3))
