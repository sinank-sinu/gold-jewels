from odoo import fields, models, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_branch_id = fields.Many2one(
        related='pos_config_id.pos_branch_id', 
        readonly=False, 
        string="POS Branch"
    )

    @api.onchange('pos_config_id')
    def _onchange_pos_config_id(self):
        for rec in self:
            if rec.pos_config_id and not rec.pos_config_id.pos_branch_id:
                rec.pos_branch_id = self.env.user.branch_id