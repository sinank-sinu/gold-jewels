from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    allow_backorder_creation = fields.Boolean(
        string="Allow Backorder Creation",
        compute='_compute_allow_backorder_creation',
        inverse='_inverse_allow_backorder_creation',
        help="Check this if the user is authorized to create backorders."
    )

    def _compute_allow_backorder_creation(self):
        group = self.env.ref('em_jewellery_management.group_allow_backorder_creation', raise_if_not_found=False)
        for user in self:
            user.allow_backorder_creation = bool(group and group in user.groups_id)

    def _inverse_allow_backorder_creation(self):
        group = self.env.ref('em_jewellery_management.group_allow_backorder_creation', raise_if_not_found=False)
        if not group:
            return
        for user in self:
            if user.allow_backorder_creation:
                user.groups_id = [(4, group.id)]
            else:
                user.groups_id = [(3, group.id)]
