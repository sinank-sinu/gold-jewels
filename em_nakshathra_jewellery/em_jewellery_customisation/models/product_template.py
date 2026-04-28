from odoo import models, fields, api, _
import math
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'


    def get_variant_info_for_label(self):
        self.ensure_one()
        variants = self.product_variant_ids

        return {
            'count': len(variants),
            'product_id': variants[0].id if len(variants) == 1 else False
        }

    def action_open_variant_wizard(self):
        self.ensure_one()
        label_id = self.env.context.get('label_id')  
        print(label_id, "LABEL ID RECEIVED")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Select Variant',
            'res_model': 'product.variant.wizard',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_product_tmpl_id': self.id,
                'default_label_id': label_id,
            }
        }