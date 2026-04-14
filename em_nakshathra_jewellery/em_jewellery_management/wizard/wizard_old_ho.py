from odoo import models, fields, _
from odoo.exceptions import ValidationError


class OldGoldHOTransferWizard(models.TransientModel):
    _name = 'old.gold.ho.transfer.wizard'
    _description = 'Old Gold HO Transfer Wizard'


    source_location_id = fields.Many2one(
        'stock.location',
        string="Source (Branch) Location",
        required=True,
        default = lambda self: self.env.user.branch_id.old_gold_location_id.id
    )

    ho_location_id = fields.Many2one(
        'stock.location',
        string="HO Location",
        required=True
    )

    def action_confirm_transfer(self):
        active_ids = self.env.context.get('active_ids', [])

        if not active_ids:
            raise ValidationError(_("No records selected."))

        purchases = self.env['old.gold.purchase'].browse(active_ids)

        for purchase in purchases:
            if purchase.state != 'draft':
                raise ValidationError(
                    _("HO transfer is allowed only in Draft state.\n"
                      "Invalid record: %s")
                )

            purchase.action_transfer_to_ho(
                self.source_location_id,
                self.ho_location_id
            )

        return {'type': 'ir.actions.act_window_close'}

