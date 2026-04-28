from odoo import fields, models, api

class PosConfig(models.Model):
    _inherit = 'pos.config'


    pos_branch_id = fields.Many2one(
        'res.branch', 
        string="Branch",
        default=lambda self: self.env.user.branch_id)
  
    def _get_available_product_domain(self):
        domain = super()._get_available_product_domain()
        branch_id = self.env.user.branch_id.id
        if branch_id:
            domain += [
                '|',
                ('branch_id', '=', branch_id),
                ('branch_id', '=', False)
            ]
        return domain