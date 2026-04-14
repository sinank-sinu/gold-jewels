# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class SaleOrderBranchTransferWizard(models.TransientModel):
    _name = 'sale.order.branch.transfer.wizard'
    _description = 'Sale Order Branch Transfer'

    branch_id = fields.Many2one(
        'res.branch',
        string='Target Branch',
        required=True,
        default=lambda self: self.env.user.branch_id.id
    )

    def action_transfer_branch(self):
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')

        if not active_model or not active_ids:
            raise UserError(_("No records selected."))

        records = self.env[active_model].browse(active_ids)

        # Safety: ensure model has branch_id
        if 'branch_id' not in records._fields:
            raise UserError(_(
                "Model %s does not support branches."
            ) % active_model)

        records.write({'branch_id': self.branch_id.id})

        return {'type': 'ir.actions.act_window_close'}
