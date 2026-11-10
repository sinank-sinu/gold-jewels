# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    purity_id = fields.Many2one(
        'gold.purity',
        string="Purity",
        related='product_id.purity_id',
        store=True,
        readonly=True,
        index=True,
    )

    def action_open_cutpiece_transfer_wizard(self):
        """Action invoked from the 'Transfer' menu in the Actions dropdown on Cutpiece Location Stock."""
        if not self:
            raise UserError(_("Please select at least one record to transfer."))

        valid_quants = self.filtered(lambda q: q.quantity > 0)
        if not valid_quants:
            raise UserError(_("None of the selected records have available stock to transfer."))

        locations = valid_quants.mapped('location_id')
        if len(locations) > 1:
            raise UserError(_("All selected cut pieces must belong to the same source location."))

        return {
            'name': _('Cutpiece Stock Transfer'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.cutpiece.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': dict(
                self.env.context,
                active_ids=valid_quants.ids,
                active_model='stock.quant',
            ),
        }

