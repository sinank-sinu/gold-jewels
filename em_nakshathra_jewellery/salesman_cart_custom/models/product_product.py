from odoo import models, fields,  api

class ProductProduct(models.Model):
    _inherit = 'product.product'

    # The first parameter is the target model string ('product.label')
    # The second parameter MUST match the Many2one field name in your label model ('product_id')
    product_label_ids = fields.One2many(
        'product.label', 
        'product_id', 
        string='Product Labels'
    )

    # This field will automatically hold strings like 'HT/LBL/00048'
    active_label_name = fields.Char(
        string="Active Label Reference",
        compute="_compute_active_label_name",
        store=True,  # Storing it in the database makes it ultra-fast to search by
        help="Automatically grabs the name of the active label for this product variant."
    )

    @api.depends('product_label_ids', 'product_label_ids.active', 'product_label_ids.name')
    def _compute_active_label_name(self):
        """
        Scans all linked labels for a product. If a label has its active toggle 
        switched ON, its name (e.g., HT/LBL/00048) is passed directly to the product.
        """
        for product in self:
            # Look into the One2many collection for the label record marked active
            active_label = product.product_label_ids.filtered(lambda l: l.active)
            
            if active_label:
                # Set the field to the name of the first active label found
                product.active_label_name = active_label[0].name
            else:
                # Explicit fallback if no label is active
                product.active_label_name = False