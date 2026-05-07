from odoo import models, fields, api, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def action_scan_barcode(self, order_id, barcode):
        """
        Called via RPC when a barcode is scanned on the Stock Picking form.
        """
        barcode = (barcode or '').strip()
        if not barcode:
            return {'error': _('Empty barcode received.')}

        label = self.env['product.label'].search([('barcode', '=', barcode)], limit=1)
        if label:
            product = label.product_id
            source_label = label.name
            qty = label.purchase_gross_weight or 1.0
        else:
            product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
            if not product:
                return {'error': _('No product label or product found for barcode: %s') % barcode}
            source_label = product.display_name
            qty = 1.0

        picking = self.browse(order_id)
        if not picking.exists():
            return {'error': _('Stock Picking not found.')}

        create_vals = {
            'picking_id': picking.id,
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': picking.company_id.id,
        }
        
        if label:
            create_vals['label_id'] = label.id
            if label.purity_id:
                create_vals['purity_id'] = label.purity_id.id

        self.env['stock.move'].create(create_vals)

        return {
            'success': True,
            'label': source_label,
            'product': product.display_name,
        }
