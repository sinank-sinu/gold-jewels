from odoo import models, _
from odoo.exceptions import UserError


class StockBackorderConfirmation(models.TransientModel):
    _inherit = 'stock.backorder.confirmation'

    def process(self):
        if not self.env.user.has_group('em_jewellery_management.group_allow_backorder_creation') and not self.env.is_superuser():
            raise UserError(_(
                "You are not authorized to create backorders. "
                "Only authorized supervisors/managers can create backorders. "
                "Please choose 'No Backorder' or contact your manager."
            ))
        return super().process()
