from odoo import models, fields, api, _


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def action_scan_barcode(self, order_id, barcode):
        """
        Called via RPC when a barcode is scanned on the Sale Order form.
        Looks up the product.label by barcode, then creates a new sale order line.
        Falls back to product.product barcode if no label is found.
        Returns a dict with either 'success' or 'error' key.
        """
        barcode = (barcode or '').strip()
        if not barcode:
            return {'error': _('Empty barcode received.')}

        # ── 1. Try product.label barcode first ──────────────────────────────
        label = self.env['product.label'].search(
            [('barcode', '=', barcode)], limit=1
        )

        if label:
            product = label.product_id
            source_label = label.name
        else:
            # ── 2. Fallback: product.product barcode ─────────────────────────
            product = self.env['product.product'].search(
                [('barcode', '=', barcode)], limit=1
            )
            if not product:
                return {
                    'error': _(
                        'No product label or product found for barcode: %s'
                    ) % barcode
                }
            source_label = product.display_name

        if not product:
            return {'error': _('Product not found for barcode: %s') % barcode}

        order = self.browse(order_id)
        if not order.exists():
            return {'error': _('Sale Order not found.')}

        create_vals = {
            'order_id': order.id,
            'product_id': product.id,
        }

        if label:
            create_vals.update({
                'label_id': label.id,
                'purity_id': label.purity_id.id if label.purity_id else False,
                'mc_percent': label.sale_making_charge_value,
                'sale_making_charge_min': label.sale_making_charge_min,
                'product_uom_qty': label.sale_gross_weight,
                'sale_stone_weight': label.sale_stone_weight,
                'sale_diamond_weight_gm': label.sale_diamond_weight_gm,
                'sale_stone_rate': label.sale_stone_rate,
                'sale_diamond_rate': label.sale_diamond_rate,
            })
            
            # Fetch Gold rate
            if label.purity_id:
                today = fields.Date.today()
                gold_rate_rec = self.env['gold.rate.master'].search([
                    ('purity_id', '=', label.purity_id.id),
                    ('date', '<=', today),
                    ('active', '=', True),
                    ('rate_type', '=', 'sale')
                ], order='date desc', limit=1)
                
                if gold_rate_rec:
                    create_vals['gold_rate'] = gold_rate_rec.rate_per_gram
        else:
            create_vals['product_uom_qty'] = 1.0

        self.env['sale.order.line'].create(create_vals)

        return {
            'success': True,
            'label': source_label,
            'product': product.display_name,
        }

    @api.model
    def action_scan_barcode_old_gold(self, order_id, barcode):
        pass
        """
        Called via RPC when a barcode is scanned on the Apply Old Gold section.
        # """
        # barcode = (barcode or '').strip()
        # if not barcode:
        #     return {'error': _('Empty barcode received.')}
        #
        # label = self.env['product.label'].search([('barcode', '=', barcode)], limit=1)
        # if label:
        #     product = label.product_id
        #     source_label = label.name
        #     purity_id = label.purity_id.id if label.purity_id else False
        #     gross_weight = label.sale_gross_weight or 1.0
        #     stone_weight = label.sale_stone_weight or 0.0
        # else:
        #     return {'error': _('Only labeled items with purity can be scanned as Old Gold. Barcode: %s') % barcode}
        #
        # if not purity_id:
        #     return {'error': _('Purity is required for old gold lines. Barcode %s does not have purity.') % barcode}
        #
        # order = self.browse(order_id)
        # if not order.exists():
        #     return {'error': _('Sale Order not found.')}
        #
        # # Fetch old gold rate
        # today = fields.Date.today()
        # gold_rate_rec = self.env['gold.rate.master'].search([
        #     ('purity_id', '=', purity_id),
        #     ('date', '<=', today),
        #     ('active', '=', True),
        #     ('rate_type', '=', 'old_gold')
        # ], order='date desc', limit=1)
        #
        # rate = gold_rate_rec.board_rate if gold_rate_rec else 0.0
        #
        # create_vals = {
        #     'sale_id': order.id,
        #     'purity_id': purity_id,
        #     'gross_weight': gross_weight,
        #     'stone_weight': stone_weight,
        #     'rate': rate,
        # }
        #
        # self.env['sale.old.gold.line'].create(create_vals)
        #
        # return {
        #     'success': True,
        #     'label': source_label,
        #     'product': product.display_name,
        # }
