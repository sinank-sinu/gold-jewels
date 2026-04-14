from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _get_branch_domain(self):
        """methode to get branch domain"""
        company = self.env.company
        branch_ids = self.env.user.branch_ids
        branch = branch_ids.filtered(
            lambda branch: branch.company_id == company)
        return [('id', 'in', branch.ids)]

    branch_id = fields.Many2one('res.branch', string='Branch', store=True,
                                domain=_get_branch_domain,
                                default=lambda self: self.env.user.branch_id.id)
    purity_id = fields.Many2one('gold.purity', string="Purity")
    total_grams = fields.Float(string="Total Grams", digits=(16, 3))
