from odoo import models, fields, api


class JewelleryBranchDetailLine(models.TransientModel):
    _name = 'jewellery.branch.detail.line'
    _description = 'Jewellery Branch Detail Line'

    wizard_id = fields.Many2one('jewellery.branch.detail.wizard', string="Wizard", ondelete='cascade')
    branch_id = fields.Many2one('res.branch', string="Branch")
    product_id = fields.Many2one('product.product', string="Product Variant")
    date = fields.Datetime(string="Transfer Date/Time")
    
    transfer_type = fields.Selection([
        ('po', 'Purchase (PO)'),
        ('so', 'Sale (SO)'),
        ('internal', 'Internal Transfer')
    ], string="Type")
    
    particulars = fields.Char(string="Particulars")
    
    location_id = fields.Many2one('stock.location', string="Source Location")
    location_dest_id = fields.Many2one('stock.location', string="Destination Location")
    
    label_ids = fields.Many2many('product.label', string="Transferred Labels")
    label_count = fields.Integer(string="Labels Count")
    inward_gross_weight = fields.Float(string="Inward Gross Wt", digits=(16, 3))
    inward_net_weight = fields.Float(string="Inward Net Wt", digits=(16, 3))
    inward_stone_weight = fields.Float(string="Inward Stone Wt", digits=(16, 3))
    inward_diamond_weight = fields.Float(string="Inward Diamond Wt", digits=(16, 3))
    outward_gross_weight = fields.Float(string="Outward Gross Wt", digits=(16, 3))
    outward_net_weight = fields.Float(string="Outward Net Wt", digits=(16, 3))
    outward_stone_weight = fields.Float(string="Outward Stone Wt", digits=(16, 3))
    outward_diamond_weight = fields.Float(string="Outward Diamond Wt", digits=(16, 3))
    outward_other_weight = fields.Float(string="Outward Other Wt", digits=(16, 3))
    closing_gross_weight = fields.Float(string="Closing Gross Wt", digits=(16, 3))
    closing_net_weight = fields.Float(string="Closing Net Wt", digits=(16, 3))

    def action_show_labels(self):
        self.ensure_one()
        return {
            'name': f"Transferred Labels: {self.product_id.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.label_ids.ids)],
            'context': {'active_test': False},
            'target': 'current',
        }
