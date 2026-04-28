from odoo import models, fields, api

class ProductLabelConfigurator(models.TransientModel):
    _name = 'product.label.configurator'
    _description = 'Jewelry Variant Selector'

    label_id = fields.Many2one('product.label', string="Source Label")
    product_tmpl_id = fields.Many2one('product.template', string="Jewelry Template")
    
    # This field will show the list of variants in the popup
    product_id = fields.Many2one(
        'product.product', 
        string="Select Variant", 
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        required=True
    )
    
    def action_confirm(self):
        self.ensure_one()
        # When confirmed, it updates the original record with the chosen variant
        if self.label_id:
            self.label_id.write({
                'product_id': self.product_id.id
            })
        return {'type': 'ir.actions.act_window_close'}
    
   