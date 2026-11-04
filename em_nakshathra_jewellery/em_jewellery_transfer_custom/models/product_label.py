# -*- coding: utf-8 -*-
from odoo import models, api

class ProductLabel(models.Model):
    _inherit = 'product.label'

    @api.constrains('sale_gross_weight', 'purchase_id', 'job_work_id', 'product_id', 'product_tmpl_id')
    def _check_unlabelled_weight_limit(self):
        """Bypass PO/JW unlabelled weight check when updating label gross weight during cut piece transfers."""
        if self.env.context.get('cutpiece_weight_update') or self.env.context.get('skip_unlabelled_weight_check'):
            return
        return super()._check_unlabelled_weight_limit()

