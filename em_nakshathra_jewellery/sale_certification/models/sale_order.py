from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    certification_image = fields.Binary(string='Certification Image', attachment=True)
    certification_image_name = fields.Char(string='Certification Image Name')
    diamond_certification = fields.Text(string='Diamond Certification')




