from odoo import models, fields, api, _

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model
    def action_scan_barcode(self, order_id, barcode):
        """
        Called via RPC when a barcode is scanned on the Purchase Order form.
        """
        barcode = (barcode or '').strip()
        if not barcode:
            return {'error': _('Empty barcode received.')}

        order = self.browse(order_id)
        if not order.exists():
            return {'error': _('Purchase Order not found.')}

        company_id = order.company_id.id if hasattr(order, 'company_id') and order.company_id else False

        label = False
        barcode_domain = ['|', ('barcode', '=', barcode), ('barcode2', '=', barcode)]
        if company_id:
            label = self.env['product.label'].search(
                barcode_domain + [('company_id', '=', company_id), ('active', '=', True)], limit=1
            )
        if not label:
            label = self.env['product.label'].search(barcode_domain + [('active', '=', True)], limit=1)

        if label:
            product = label.product_id
            source_label = label.name
            qty = label.sale_gross_weight or 1.0
        else:
            product = self.env['product.product'].search([('barcode', '=', barcode)], limit=1)
            if not product:
                return {'error': _('No product label or product found for barcode: %s') % barcode}
            source_label = product.display_name
            qty = 1.0

        # Check if barcode / label has already been scanned in this purchase order
        if label:
            already_scanned = order.order_line.filtered(
                lambda l: (hasattr(l, 'label_id') and l.label_id == label) or (l.product_id and (l.product_id.barcode == barcode))
            )
        else:
            already_scanned = order.order_line.filtered(
                lambda l: l.product_id == product or (l.product_id and l.product_id.barcode == barcode)
            )

        if already_scanned:
            return {'error': _('Barcode "%s" has already been scanned.') % barcode}

        create_vals = {
            'order_id': order.id,
            'product_id': product.id,
            'name': product.display_name,
            'product_qty': qty,
            'product_uom': product.uom_po_id.id,
            'price_unit': product.standard_price,
            'date_planned': order.date_planned or fields.Datetime.now(),
        }

        self.env['purchase.order.line'].create(create_vals)

        return {
            'success': True,
            'label': source_label,
            'product': product.display_name,
        }
