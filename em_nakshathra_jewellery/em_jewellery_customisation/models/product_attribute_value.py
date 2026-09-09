from odoo import models

class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'
    _order = 'attribute_id, name, id'

class ProductTemplateAttributeLine(models.Model):
    _inherit = 'product.template.attribute.line'

    def read(self, fields=None, load='_classic_read'):
        res = super().read(fields, load)
        if not fields or 'value_ids' in fields:
            for record in res:
                if record.get('value_ids'):
                    values = self.env['product.attribute.value'].browse(record['value_ids'])
                    record['value_ids'] = values.sorted(key=lambda v: (v.name or "").strip().lower()).ids
        return res
