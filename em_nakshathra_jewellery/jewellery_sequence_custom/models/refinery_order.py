from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class OldGoldRefineryIssue(models.Model):
    _inherit = 'old.gold.refinery.issue'


    @api.model
    def create(self, vals):
        if vals.get('name', "New") == "New":
            branch = self.env['res.branch'].browse(vals.get('branch_id')) if vals.get('branch_id') else self.env.user.branch_id
            if not branch or not branch.branch_code:
                raise ValidationError("Branch code is missing!")
            seq = self.env['ir.sequence'].next_by_code('jewellery.refinery')
            if not seq:
                raise ValidationError("Sequence not working!")
            vals['name'] = f"{branch.branch_code}/{seq}"
        res = super().create(vals)
        return res