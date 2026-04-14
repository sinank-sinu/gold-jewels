from odoo import models, fields,api,_
from odoo.exceptions import ValidationError


class OldGoldBullionIssue(models.Model):
    _name = 'old.gold.bullion.issue'
    _description = 'Bullion Issue'


    branch_id = fields.Many2one('res.branch', string='Branch',
                                default=lambda self: self.env.user.branch_id.id)

    name = fields.Char(default='New', readonly=True)
    issue_id = fields.Many2one('old.gold.refinery.issue', required=True)
    purity_id = fields.Many2one('gold.purity', string="Expected Purity")
    issued_weight = fields.Float(required=True,digits=(16, 3))
    source_location_id = fields.Many2one('stock.location')
    received_location_id = fields.Many2one('stock.location')
    picking_id = fields.Many2one('stock.picking', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('receive', 'Receive'),
    ], default='draft')
    refinery_partner_id = fields.Many2one('res.partner')
    purchase_per_rate = fields.Float(string="Purchase/gram")
    product_id = fields.Many2one('product.product', string="Product", 
                                default=lambda self: self.env.ref('em_jewellery_management.product_bullion_gold'),
                                required=True)



    def action_receive(self):
        self.ensure_one()

        if self.state != 'draft':
            return
        Bullion = self.env['old.gold.bullion.receipt']

        # Prevent duplicate bullion creation
        # existing = Bullion.search([
        #     ('issue_id', '=', self.id),
        # ], limit=1)
        #
        # if existing:
        #     return {
        #         'type': 'ir.actions.act_window',
        #         'name': _('Bullion Receipt'),
        #         'res_model': 'old.gold.bullion.receipt',
        #         'res_id': existing.id,
        #         'view_mode': 'form',
        #         'target': 'current',
        #     }

        # Total melting output (sum of issue_weight)
        total_weight = self.issued_weight

        bullion = Bullion.create({
            'issue_id': self.issue_id.id,
            'receive_weight': total_weight,
            'source_location_id': self.source_location_id.id,
            'refinery_partner_id': self.refinery_partner_id.id,
            'purity_id': self.purity_id.id,
            'received_location_id': self.received_location_id.id,
            'purchase_per_rate': self.purchase_per_rate,
            'product_id': self.product_id.id,
        })

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_internal').id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.received_location_id.id,
            'origin': self.name,
            'is_old_gold': True,
        })

        self.env['stock.move'].create({
            'product_id': self.product_id.id,
            'product_uom_qty': total_weight,
            'name': 'Bullion Gold',
            'product_uom': self.env.ref('uom.product_uom_gram').id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'picking_id': picking.id,
            'purity_id': self.purity_id.id,
        })

        for move_line in picking.move_line_ids:
            move_line.qty_done = move_line.product_uom_qty


        picking.button_validate()

        self.picking_id = picking.id
        self.state = 'receive'
        #
        # return {
        #     'type': 'ir.actions.act_window',
        #     'name': _('Bullion Receipt'),
        #     'res_model': 'old.gold.bullion.receipt',
        #     'res_id': bullion.id,
        #     'view_mode': 'form',
        #     'target': 'current',
        # }

    def action_view_bullion_transfers(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Bullion Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [
                ('id', '=', self.picking_id.id),
            ],

        }

class OldGoldBullionReceipt(models.Model):
    _name = 'old.gold.bullion.receipt'
    _description = 'Bullion Receipt'


    branch_id = fields.Many2one('res.branch', string='Branch',
                                help='Leave this field empty if this account is'
                                     ' shared between all branches',
                                default=lambda self: self.env.user.branch_id.id, )

    name = fields.Char(default='New', readonly=True)
    issue_id = fields.Many2one('old.gold.refinery.issue', required=True)
    purity_id = fields.Many2one('gold.purity', string="Expected Purity")
    receive_weight = fields.Float(required=True,digits=(16, 3))
    source_location_id = fields.Many2one('stock.location')
    received_location_id = fields.Many2one('stock.location')
    picking_id = fields.Many2one('stock.picking', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('received', 'Received'),
    ], default='draft')
    refinery_partner_id = fields.Many2one('res.partner')
    purchase_per_rate = fields.Float(string="Purchase/gram")
    product_id = fields.Many2one('product.product', string="Product", readonly=True)

    def action_received(self):
        self.ensure_one()

        mo = self.issue_id.mo_id
        # if mo and mo.state in ('confirmed', 'progress'):
            # Update MO destination to the receive location
            # if self.received_location_id:
            #     mo.location_dest_id = self.received_location_id.id
            #
            # # Set the qty_producing to the actual received weight
            # mo.qty_producing = self.receive_weight
            #
            # # Mark all raw material (Old Gold) moves as done
            # for move in mo.move_raw_ids:
            #     move.quantity = move.product_uom_qty
            #
            # # Mark the finished move as done
            # for move in mo.move_finished_ids:
            #     move.quantity = self.receive_weight

            # Produce the MO — Old Gold OUT, Gold Bullion IN
        #     mo.button_mark_done()
        #
        #     self.state = 'received'
        #     self.issue_id.state = 'received'
        # else:
            # Fallback: manual stock picking if no MO linked
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_internal').id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.received_location_id.id,
            'origin': self.name,
            'is_old_gold': True,
        })

        self.env['stock.move'].create({
            'product_id': self.env.ref('em_jewellery_management.product_bullion_gold').id,
            'product_uom_qty': self.receive_weight,
            'name': 'Bullion Gold',
            'product_uom': self.env.ref('uom.product_uom_gram').id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'picking_id': picking.id,
            'purity_id': self.purity_id.id,
        })

        for move_line in picking.move_line_ids:
            move_line.qty_done = move_line.product_uom_qty

        picking.button_validate()

        self.picking_id = picking.id
        self.state = 'received'
        self.issue_id.state = 'received'

    def action_view_bullion_transfers(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Bullion Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [
                ('id', '=', self.picking_id.id),
            ],

        }