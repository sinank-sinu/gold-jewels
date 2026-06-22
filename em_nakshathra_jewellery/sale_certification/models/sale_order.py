from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    certification_image = fields.Binary(string='Certification Image', attachment=True)
    certification_image_name = fields.Char(string='Certification Image Name')
    diamond_certification = fields.Text(string='Diamond Certification')


class ProductLabel(models.Model):
    _inherit = 'product.label'

    other_weight_g = fields.Float(string="Other Weight (g)", digits=(16, 3))
    other_weight_amount = fields.Float(string="Other Weight Amount")


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    other_weight_g = fields.Float(string="Other Weight (g)", digits=(16, 3))
    other_weight_amount = fields.Float(string="Other Weight Amount")

    @api.onchange('label_id')
    def _onchange_label_id_other_weight(self):
        if self.label_id:
            self.other_weight_g = self.label_id.other_weight_g
            self.other_weight_amount = self.label_id.other_weight_amount
        else:
            self.other_weight_g = 0.0
            self.other_weight_amount = 0.0
