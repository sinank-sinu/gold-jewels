# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProductLabel(models.Model):
    _inherit = 'product.label'

    is_weight_missing = fields.Boolean(
        string="Missing Weight",
        compute="_compute_is_weight_missing",
        search="_search_is_weight_missing",
        help="Indicates whether this label has zero or missing weight."
    )

    @api.depends('sale_gross_weight', 'purchase_gross_weight', 'sale_net_weight', 'purchase_net_weight')
    def _compute_is_weight_missing(self):
        for record in self:
            record.is_weight_missing = (
                not record.sale_gross_weight or record.sale_gross_weight <= 0 or
                not record.purchase_gross_weight or record.purchase_gross_weight <= 0
            )

    def _search_is_weight_missing(self, operator, value):
        if (operator in ('=', '==') and value) or (operator in ('!=', '<>') and not value):
            return [
                '|', '|',
                ('sale_gross_weight', '=', False),
                ('sale_gross_weight', '<=', 0),
                ('purchase_gross_weight', '<=', 0)
            ]
        else:
            return [
                ('sale_gross_weight', '>', 0),
                ('purchase_gross_weight', '>', 0)
            ]
