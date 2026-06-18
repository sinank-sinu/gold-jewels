from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductLabel(models.Model):
    _inherit = 'product.label'


    @api.model
    def create(self, vals):
        if vals.get('name', "New") == "New" or vals.get('name', _('New')) == _('New'):
            branch_id = vals.get('branch_id')
            branch = self.env['res.branch'].browse(branch_id) if branch_id else self.env.user.branch_id
            
            if not branch or not branch.branch_code:
                raise ValidationError("Branch code is missing for this Product Label!")
            
            standard_sequence = self.env['ir.sequence'].next_by_code('product.label') or "New"
            vals['name'] = f"{branch.branch_code}/{standard_sequence}"
            
        return super().create(vals)
