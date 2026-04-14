# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2022-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################

from odoo import models, fields, api


class StockPicking(models.Model):
    """inherited stock.picking"""
    _inherit = "stock.picking"

    branch_id = fields.Many2one("res.branch", string='Branch',
                                default=lambda self: self.env.user.branch_id.id,)



class StockPickingTypes(models.Model):
    """inherited stock picking type"""
    _inherit = "stock.picking.type"

    branch_id = fields.Many2one('res.branch', string='Branch', store=True,
                                related='warehouse_id.branch_id')

class StockMove(models.Model):
    _inherit = 'stock.move'

    def _get_new_picking_values(self):
        vals = super(StockMove, self)._get_new_picking_values()
        branch_id = False
        
        # Try to get branch from sale order via group
        groups = self.mapped('group_id')
        if groups and hasattr(groups, 'sale_id'):
            sale = groups.mapped('sale_id')
            if sale and sale[0].branch_id:
                branch_id = sale[0].branch_id.id

        if not branch_id:
            branch_id = self.env.user.branch_id.id
            
        if branch_id:
            vals['branch_id'] = branch_id
            
        return vals
