from odoo import models, api, _


class JewelleryIssueVoucher(models.Model):
    _inherit = 'jewellery.issue.voucher'

    @api.model
    def action_scan_barcode(self, voucher_id, barcode):
        """
        Called via RPC when a barcode is scanned on the Issue Voucher form.
        Looks up the product.label by barcode, then creates a new issue voucher line.
        Falls back to product.product barcode if no label is found.
        Returns a dict with either 'success' or 'error' key.
        """
        barcode = (barcode or '').strip()
        if not barcode:
            return {'error': _('Empty barcode received.')}

        # ── 1. Try product.label barcode first ──────────────────────────────
        voucher = self.browse(voucher_id)
        if not voucher.exists():
            return {'error': _('Issue Voucher not found.')}

        company_id = voucher.company_id.id if hasattr(voucher, 'company_id') and voucher.company_id else False

        label = False
        barcode_domain = ['|', ('barcode', '=', barcode), ('barcode2', '=', barcode)]
        if company_id:
            label = self.env['product.label'].search(
                barcode_domain + [('company_id', '=', company_id), ('active', '=', True)], limit=1
            )
        if not label:
            label = self.env['product.label'].search(
                barcode_domain + [('active', '=', True)], limit=1
            )

        if label:
            product = label.product_id
            purity_id = label.purity_id.id if label.purity_id else False
            gross_weight = label.purchase_gross_weight or 0.0
            stone_weight = label.purchase_stone_weight or 0.0
            product_tmpl_id = label.product_tmpl_id.id if label.product_tmpl_id else (
                product.product_tmpl_id.id if product else False
            )
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
            purity_id = False
            gross_weight = 0.0
            stone_weight = 0.0
            product_tmpl_id = product.product_tmpl_id.id
            source_label = product.display_name

        if not product:
            return {'error': _('Product not found for barcode: %s') % barcode}

        # Check if barcode / label has already been scanned in this issue voucher
        if label:
            already_scanned = voucher.line_ids.filtered(
                lambda l: (hasattr(l, 'label_id') and l.label_id == label) or (l.product_id and l.product_id.barcode == barcode)
            )
        else:
            already_scanned = voucher.line_ids.filtered(
                lambda l: l.product_id == product or (l.product_id and l.product_id.barcode == barcode)
            )

        if already_scanned:
            return {'error': _('Barcode "%s" has already been scanned.') % barcode}

        uom_id = product.uom_id.id if product.uom_id else False

        self.env['jewellery.issue.voucher.line'].create({
            'voucher_id': voucher_id,
            'product_id': product.id,
            'product_template_id': product_tmpl_id,
            'purity_id': purity_id,
            'gross_weight': gross_weight,
            'stone_weight': stone_weight,
            'qty': gross_weight - stone_weight,
            'uom_id': uom_id,
        })

        return {
            'success': True,
            'label': source_label,
            'product': product.display_name,
        }
