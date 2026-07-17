from odoo import models, fields


class JewelleryItemDetailLine(models.TransientModel):
    _name = 'jewellery.item.detail.line'
    _description = 'Jewellery Item Detail Line'

    wizard_id = fields.Many2one('jewellery.report.wizard', string="Wizard", ondelete='cascade')
    product_id = fields.Many2one('product.product', string="Product Item")
    date = fields.Date(string="Date")
    ref = fields.Char(string="Ref")
    inward_gross_weight = fields.Float(string="Inward Gross Wt", digits=(16, 3))
    inward_net_weight = fields.Float(string="Inward Net Wt", digits=(16, 3))
    inward_diamond_weight = fields.Float(string="Inward Diamond Wt", digits=(16, 3))
    outward_gross_weight = fields.Float(string="Outward Gross Wt", digits=(16, 3))
    outward_net_weight = fields.Float(string="Outward Net Wt", digits=(16, 3))
    outward_diamond_weight = fields.Float(string="Outward Diamond Wt", digits=(16, 3))
    outward_other_weight = fields.Float(string="Outward Other Wt", digits=(16, 3))
    closing_gross_weight = fields.Float(string="Closing Gross Wt", digits=(16, 3))
    closing_net_weight = fields.Float(string="Closing Net Wt", digits=(16, 3))
