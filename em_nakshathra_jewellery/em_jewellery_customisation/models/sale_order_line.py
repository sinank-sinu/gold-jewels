from email.policy import default

from numpy.f2py.rules import defmod_rules

from odoo import models, fields, api

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_scheme_line = fields.Boolean(default=False)