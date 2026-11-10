# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    allow_intercompany_transfers = fields.Boolean(
        string="Allow Inter-Company Transfers",
        compute='_compute_allow_intercompany_transfers',
        inverse='_inverse_allow_intercompany_transfers',
        help="Check this if the user is authorized to access and manage the Inter-Company Transfer application."
    )

    def _compute_allow_intercompany_transfers(self):
        group_user = self.env.ref('product_label_intercompany_transfer.group_intercompany_transfer_user', raise_if_not_found=False)
        group_manager = self.env.ref('product_label_intercompany_transfer.group_intercompany_transfer_manager', raise_if_not_found=False)
        for user in self:
            has_user = bool(group_user and group_user in user.groups_id)
            has_mgr = bool(group_manager and group_manager in user.groups_id)
            user.allow_intercompany_transfers = has_user or has_mgr

    def _inverse_allow_intercompany_transfers(self):
        group_user = self.env.ref('product_label_intercompany_transfer.group_intercompany_transfer_user', raise_if_not_found=False)
        group_manager = self.env.ref('product_label_intercompany_transfer.group_intercompany_transfer_manager', raise_if_not_found=False)
        for user in self:
            if user.allow_intercompany_transfers:
                cmds = []
                if group_user:
                    cmds.append((4, group_user.id))
                if group_manager:
                    cmds.append((4, group_manager.id))
                if cmds:
                    user.groups_id = cmds
            else:
                cmds = []
                if group_user:
                    cmds.append((3, group_user.id))
                if group_manager:
                    cmds.append((3, group_manager.id))
                if cmds:
                    user.groups_id = cmds

