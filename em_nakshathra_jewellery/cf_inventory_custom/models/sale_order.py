from collections import defaultdict

from odoo import models, fields,api,_
from odoo.exceptions import UserError, ValidationError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _prepare_procurement_values(self, group_id=False):
        values = super()._prepare_procurement_values(group_id)
        values['label_id'] = self.label_id.id
        return values