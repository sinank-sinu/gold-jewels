from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class OldGoldSmithTransferWizard(models.TransientModel):
    _name = 'old.gold.smith.transfer.wizard'
    _description = 'Old Gold Smith Transfer Wizard'

    purchase_id = fields.Many2one('old.gold.purchase', string="Old Gold Purchase", readonly=True)
    # job_worker_id = fields.Many2one('res.partner', string="Job Worker", domain=[('is_job_worker', '=', True)], required=True)
    location_dest_id = fields.Many2one('stock.location', string="Destination Location", required=True)
    
    line_ids = fields.One2many('old.gold.smith.transfer.wizard.line', 'wizard_id', string="Transfer Lines")

    @api.model
    def default_get(self, fields):
        res = super(OldGoldSmithTransferWizard, self).default_get(fields)
        if self._context.get('active_id') and self._context.get('active_model') == 'old.gold.purchase':
            purchase = self.env['old.gold.purchase'].browse(self._context.get('active_id'))
            res['purchase_id'] = purchase.id
            lines = []
            for line in purchase.old_gold_line_ids:
                if line.remaining_weight > 0:
                    lines.append((0, 0, {
                        'purchase_line_id': line.id,
                        'transfer_weight': 0.0,
                    }))
            res['line_ids'] = lines
        return res

    # @api.onchange('job_worker_id')
    # def _onchange_job_worker_id(self):
    #     if self.job_worker_id:
    #         self.location_dest_id = self.job_worker_id.property_stock_supplier.id

    def action_transfer(self):
        self.ensure_one()
        if not self.line_ids.filtered(lambda l: l.transfer_weight > 0):
            raise ValidationError(_("Please enter weights to transfer."))

        picking_type = self.env.ref('stock.picking_type_internal')
        product = self.env.ref('em_jewellery_management.product_old_gold')
        uom = self.env.ref('uom.product_uom_gram')

        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': self.purchase_id.ho_location_id.id,
            'location_dest_id': self.location_dest_id.id,
            'origin': self.purchase_id.name,
            'is_old_gold': True,
            'sale_old_id': self.purchase_id.sale_id.id,
        })

        for line in self.line_ids:
            if line.transfer_weight <= 0:
                continue
            
            if line.transfer_weight > line.available_weight:
                raise ValidationError(_("Transfer weight for %s exceeds available weight.") % line.purity_id.name)

            self.env['stock.move'].create({
                'product_id': product.id,
                'name': f'Old Gold Transfer to Smith ({line.purity_id.name})',
                'purity_id': line.purity_id.id,
                'product_uom_qty': line.transfer_weight,
                'product_uom': uom.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'picking_id': picking.id,
            })
            
            # Update the purchase line
            line.purchase_line_id.transferred_weight += line.transfer_weight
            line.purchase_line_id.gross_weight -= line.transfer_weight
            line.purchase_line_id.verified_gross_weight -= line.transfer_weight

        self.purchase_id.smith_transferred = True
        picking.action_confirm()
        # Optional: picking.button_validate() if immediate transfer is desired. 
        # Usually, it's better to let the user validate the picking.

        return {'type': 'ir.actions.act_window_close'}


class OldGoldSmithTransferWizardLine(models.TransientModel):
    _name = 'old.gold.smith.transfer.wizard.line'
    _description = 'Old Gold Smith Transfer Wizard Line'

    wizard_id = fields.Many2one('old.gold.smith.transfer.wizard')
    purchase_line_id = fields.Many2one('sale.old.gold.line', string="Purchase Line")
    purity_id = fields.Many2one('gold.purity', related='purchase_line_id.verified_purity_id', string="Purity")
    available_weight = fields.Float(related='purchase_line_id.remaining_weight', string="Available Weight", digits=(16, 3))
    transfer_weight = fields.Float(string="Transfer Weight", digits=(16, 3))
