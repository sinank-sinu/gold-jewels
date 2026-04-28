from odoo import models, fields

class ProductVariantWizard(models.TransientModel):
    _name = 'product.variant.wizard'
    _description = 'Select Product Variant'

    product_tmpl_id = fields.Many2one('product.template')
    label_id = fields.Many2one('product.label') # Add this field to store the parent ID
    product_id = fields.Many2one(
        'product.product',
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        required=True
    )


    def action_confirm(self):
        print("Entering")
        self.ensure_one()
        # Update the parent label record directly
        if self.label_id:
            self.label_id.write({
                'product_id': self.product_id.id
            })
            self.label_id.write({
                'product_tmpl_id': self.product_id.product_tmpl_id.id
            })
            print(self.label_id, "LABEL")
        return {'type': 'ir.actions.act_window_close'}