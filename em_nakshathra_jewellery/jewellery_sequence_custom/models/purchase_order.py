from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                branch_id = vals.get('branch_id')
                branch = self.env['res.branch'].browse(branch_id) if branch_id else self.env.user.branch_id
                
                if not branch or not branch.branch_code:
                    raise ValidationError("Branch code is missing for this Purchase Order!")
                
                # Let Odoo generate the standard sequence (e.g., 'P00123')
                standard_sequence = self.env['ir.sequence'].next_by_code('purchase.order') or _('New')
                
                # Combine them to get 'KNR/P00123'
                vals['name'] = f"{branch.branch_code}/{standard_sequence}"
                
        return super(PurchaseOrder, self).create(vals_list)