from odoo import fields, models,api


class StockLocation(models.Model):
    _name = "stock.location"
    _inherit = ["stock.location", "mail.thread", "mail.activity.mixin"]

    name = fields.Char(tracking=True)
    location_id = fields.Many2one(tracking=True)
    usage = fields.Selection(tracking=True)
    company_id = fields.Many2one(tracking=True)
    active = fields.Boolean(tracking=True)
    scrap_location = fields.Boolean(tracking=True)
    return_location = fields.Boolean(tracking=True)
    replenish_location = fields.Boolean(tracking=True)

    branch_id = fields.Many2one("res.branch", string='Branch', store=True,
                                help='Leave this field empty if this product is'
                                     ' shared between all branches',default=lambda self: self.env.user.branch_id.id,
                                tracking=True)
    allowed_branch_ids = fields.Many2many('res.branch', store=True,
                                          string="Allowed Branches",
                                          tracking=True)

