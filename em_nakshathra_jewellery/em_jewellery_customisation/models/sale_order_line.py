from email.policy import default

from numpy.f2py.rules import defmod_rules

from odoo import models, fields, api

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_scheme_line = fields.Boolean(default=False)

    def _prepare_procurement_values(self, group_id=False):
        vals = super()._prepare_procurement_values(group_id)

        if self.label_id and self.label_id.branch_location_id:
            vals['label_location_id'] = self.label_id.branch_location_id.id

        return vals