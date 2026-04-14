from odoo import fields, models,api


class StockLocation(models.Model):
    _inherit = "stock.location"

    branch_id = fields.Many2one("res.branch", string='Branch', store=True,
                                help='Leave this field empty if this product is'
                                     ' shared between all branches',default=lambda self: self.env.user.branch_id.id,
                                )
    allowed_branch_ids = fields.Many2many('res.branch', store=True,
                                          string="Allowed Branches",
                                          )

