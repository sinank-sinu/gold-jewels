from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_vault_item = fields.Boolean(string="Vault Item")
