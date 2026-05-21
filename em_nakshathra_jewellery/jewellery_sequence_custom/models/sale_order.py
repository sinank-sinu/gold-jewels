from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Check if it's a new draft order getting a sequence
            if vals.get('name', _('New')) == _('New'):
                # Fetch branch based on vals or fallback to current user's branch
                branch_id = vals.get('branch_id')
                branch = self.env['res.branch'].browse(branch_id) if branch_id else self.env.user.branch_id
                
                if not branch or not branch.branch_code:
                    raise ValidationError("Branch code is missing for this Sale Order!")
                
                # Let Odoo generate the standard sequence (e.g., 'S00229')
                standard_sequence = self.env['ir.sequence'].next_by_code('sale.order') or _('New')
                
                # Combine them to get 'KNR/S00229'
                vals['name'] = f"{branch.branch_code}/{standard_sequence}"
                
        return super(SaleOrder, self).create(vals_list)