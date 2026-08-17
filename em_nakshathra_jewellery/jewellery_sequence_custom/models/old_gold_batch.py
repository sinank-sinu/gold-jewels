from odoo.exceptions import ValidationError

from odoo import models, fields,api,_

class OldGoldBatch(models.Model):
    _inherit = 'old.gold.batch'


    @api.model
    def create(self, vals):
        if vals.get('name', "New") == "New":
            branch = self.env['res.branch'].browse(vals.get('branch_id')) if vals.get('branch_id') else self.env.user.branch_id
            if not branch or not branch.branch_code:
                raise ValidationError("Branch code is missing!")
            seq = self.env['ir.sequence'].next_by_code('old.gold.batch')
            if not seq:
                seq_obj = self.env['ir.sequence'].sudo().search([('code', '=', 'old.gold.batch')], limit=1)
                if seq_obj:
                    seq = seq_obj.next_by_id()
                else:
                    raise ValidationError(f"Sequence { 'old.gold.batch' } is missing from the database!")
            vals['name'] = f"{branch.branch_code}/{seq}"
        res = super().create(vals)
        return res