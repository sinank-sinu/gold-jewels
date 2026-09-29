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
        order = self.browse(order_id)
        if not order.exists():
            return {'error': _('Sale Order not found.')}

        company_id = order.company_id.id if hasattr(order, 'company_id') and order.company_id else False

        label = False
        if company_id:
            label = self.env['product.label'].search(
                [('barcode', '=', barcode), ('company_id', '=', company_id), ('active', '=', True)], limit=1
            )
        if not label:
            label = self.env['product.label'].search(
                [('barcode', '=', barcode), ('active', '=', True)], limit=1
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

        # Check if barcode / label has already been scanned in this order
        if label:
            already_scanned = order.order_line.filtered(
                lambda l: l.label_id == label or (l.label_id and l.label_id.barcode == barcode)
            )
        else:
            already_scanned = order.order_line.filtered(
                lambda l: not l.label_id and (l.product_id == product or (l.product_id and l.product_id.barcode == barcode))
            )

        if already_scanned:
            return {'error': _('Barcode "%s" has already been scanned.') % barcode}

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
    def action_scan_barcode_sale_return(self, order_id, barcode):
        """
        Called via RPC when a barcode is scanned on the Sale Return section.
        Looks up product.label (including inactive/non-active labels) by barcode, name, or label_number.
        If found, creates a new sale.return.line.
        Falls back to product.product by barcode or default_code if no label is found.
        """
        barcode = (barcode or '').strip()
        if not barcode:
            return {'error': _('Empty barcode received.')}

        # ── 1. Try product.label search with active_test=False (supports non-active labels)
        order = self.browse(order_id)
        if not order.exists():
            return {'error': _('Sale Order not found.')}

        company_id = order.company_id.id if hasattr(order, 'company_id') and order.company_id else False

        label = False
        domain = ['|', '|', ('barcode', '=', barcode), ('name', '=', barcode), ('label_number', '=', barcode)]
        if company_id:
            label = self.env['product.label'].with_context(active_test=False).search(
                domain + [('company_id', '=', company_id)], limit=1
            )
        if not label:
            label = self.env['product.label'].with_context(active_test=False).search(
                domain, limit=1
            )

        if label:
            product = label.product_id or (label.product_tmpl_id.product_variant_ids and label.product_tmpl_id.product_variant_ids[0])
            source_label = label.name or label.barcode or barcode
        else:
            # ── 2. Fallback: product.product barcode or default_code ──────────
            product = self.env['product.product'].search(
                ['|', ('barcode', '=', barcode), ('default_code', '=', barcode)], limit=1
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

        # Check if barcode / label has already been scanned in sale return
        if label:
            already_scanned = order.sale_return_line_ids.filtered(
                lambda l: (hasattr(l, 'label_id') and l.label_id == label) or (l.product_id and l.product_id.barcode == barcode)
            )
        else:
            already_scanned = order.sale_return_line_ids.filtered(
                lambda l: l.product_id == product or (l.product_id and l.product_id.barcode == barcode)
            )

        if already_scanned:
            return {'error': _('Barcode "%s" has already been scanned.') % barcode}

        # Ensure Sale Return is enabled on the order
        if not order.is_sale_return:
            order.write({'is_sale_return': True})

        # Fetch Gold Rate for return line
        purity = False
        if label:
            purity = label.purity_id or label.sale_purity_id
        if not purity and hasattr(product, 'purity_id'):
            purity = product.purity_id

        rate = 0.0
        if purity:
            today = fields.Date.today()
            gold_rate_rec = self.env['gold.rate.master'].search([
                ('purity_id', '=', purity.id),
                ('date', '<=', today),
                ('active', '=', True),
                ('rate_type', '=', 'old_gold')
            ], order='date desc', limit=1)
            if not gold_rate_rec:
                gold_rate_rec = self.env['gold.rate.master'].search([
                    ('purity_id', '=', purity.id),
                    ('date', '<=', today),
                    ('active', '=', True),
                    ('rate_type', '=', 'sale')
                ], order='date desc', limit=1)
            if gold_rate_rec:
                rate = gold_rate_rec.board_rate or gold_rate_rec.rate_per_gram

        create_vals = {
            'sale_id': order.id,
            'product_id': product.id,
            'product_template_id': product.product_tmpl_id.id,
            'name': label.name if label else (product.display_name or product.name),
            'product_uom': product.uom_id.id if product.uom_id else False,
            'rate': rate,
        }

        if purity:
            create_vals['purity_id'] = purity.id

        if product.taxes_id and order.company_id:
            taxes = product.taxes_id.filtered(lambda t: t.company_id == order.company_id)
            if taxes:
                create_vals['tax_id'] = [(6, 0, taxes.ids)]

        if label:
            gross_wt = label.sale_gross_weight or 0.0
            st_wt = label.sale_stone_weight or 0.0
            create_vals.update({
                'label_id': label.id,
                'gross_weight': gross_wt,
                'stone_weight': st_wt,
                'sale_stone_weight': st_wt,
                'sale_stone_weight_ct': label.sale_stone_weight_ct or 0.0,
                'sale_diamond_weight_gm': label.sale_diamond_weight_gm or 0.0,
                'sale_diamond_weight_ct': label.sale_diamond_weight_ct or 0.0,
                'sale_stone_rate': label.sale_stone_rate or 0.0,
                'sale_diamond_rate': label.sale_diamond_rate or 0.0,
                'mc_percent': label.sale_making_charge_value or 0.0,
                'mc_percent_actual': label.sale_making_charge_value or 0.0,
            })
            if hasattr(label, 'other_weight_g'):
                create_vals['other_weight_g'] = label.other_weight_g or 0.0
            if hasattr(label, 'other_weight_amount'):
                create_vals['other_weight_amount'] = label.other_weight_amount or 0.0

        self.env['sale.return.line'].create(create_vals)

        return {
            'success': True,
            'label': source_label,
            'product': product.display_name,
        }
