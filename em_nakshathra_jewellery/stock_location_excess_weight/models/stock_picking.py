# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.tools.float_utils import float_compare


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _auto_allocate_available_stock(self):
        """Ensure jewellery labels in internal transfers always allocate their full gross weight,
        guaranteeing zero weight loss across all location transfers."""
        super()._auto_allocate_available_stock()
        for picking in self:
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel') and m.label_id):
                target_weight = (
                    move.label_id.purchase_gross_weight
                    or move.label_id.sale_gross_weight
                    or move.label_id.tag_weight
                    or move.product_uom_qty
                )
                if not target_weight:
                    continue

                move.product_uom_qty = target_weight
                move.quantity = target_weight
                move.picked = True

                if move.move_line_ids:
                    for ml in move.move_line_ids:
                        ml.quantity = target_weight
                        ml.picked = True
                else:
                    self.env['stock.move.line'].create({
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'quantity': target_weight,
                        'label_id': move.label_id.id,
                        'picked': True,
                    })

    def action_assign(self):
        res = super().action_assign()
        self._auto_allocate_available_stock()
        return res


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.onchange('label_id')
    def _onchange_label_id_full_weight(self):
        if self.label_id:
            weight = (
                self.label_id.purchase_gross_weight
                or self.label_id.sale_gross_weight
                or self.label_id.tag_weight
            )
            if weight:
                self.product_uom_qty = weight
                self.quantity = weight
