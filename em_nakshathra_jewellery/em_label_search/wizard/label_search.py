from odoo import api, fields, models, _


class ProductLabelSearch(models.TransientModel):
    _name = 'product.label.search'
    _description = 'Product Label Search'

    line_ids = fields.One2many(
        'product.label.search.line',
        'search_id',
        string='Scanned Labels',
    )

    @api.model
    def action_scan_barcode(self, search_id, barcode):
        barcode = (barcode or '').strip()
        if not barcode:
            return {'error': _('Please scan a barcode.')}

        search = self.browse(search_id).exists()
        if not search:
            return {'error': _('Label Search record not found.')}

        labels = self.env['product.label'].with_context(active_test=False).search([
            '&',
            '|',
            ('barcode', '=', barcode),
            ('barcode2', '=', barcode),
            '|',
            ('branch_id', '=', False),
            ('branch_id.company_id', 'in', self.env.companies.ids),
        ], limit=2)
        if not labels:
            return {'error': _('No label found for barcode "%s".') % barcode}
        if len(labels) > 1:
            return {'error': _('Barcode "%s" matches more than one label.') % barcode}

        label = labels[0]
        if search.line_ids.filtered(lambda line: line.label_id == label):
            return {'error': _('Label "%s" has already been scanned.') % label.display_name}

        self.env['product.label.search.line'].create({
            'search_id': search.id,
            'label_id': label.id,
        })
        return {'product': label.display_name}


class ProductLabelSearchLine(models.TransientModel):
    _name = 'product.label.search.line'
    _description = 'Product Label Search Line'
    _order = 'id'

    search_id = fields.Many2one(
        'product.label.search',
        required=True,
        ondelete='cascade',
    )
    label_id = fields.Many2one(
        'product.label',
        string='Label',
        required=True,
        readonly=True,
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        related='label_id.purchase_id',
        readonly=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        related='label_id.partner_id',
        readonly=True,
    )
    barcode = fields.Char(related='label_id.barcode', readonly=True)
    barcode2 = fields.Char(related='label_id.barcode2', readonly=True)
    branch_id = fields.Many2one(related='label_id.branch_id', readonly=True)
    destination_id = fields.Many2one(
        related='label_id.branch_location_id',
        string='Destination',
        readonly=True,
    )
    sale_gross_weight = fields.Float(related='label_id.sale_gross_weight', readonly=True)
    sale_net_weight = fields.Float(related='label_id.sale_net_weight', readonly=True)
    sale_stone_weight = fields.Float(related='label_id.sale_stone_weight', readonly=True)
    sale_stone_weight_ct = fields.Float(related='label_id.sale_stone_weight_ct', readonly=True)
    sale_diamond_weight_gm = fields.Float(related='label_id.sale_diamond_weight_gm', readonly=True)
    sale_diamond_weight_ct = fields.Float(related='label_id.sale_diamond_weight_ct', readonly=True)
    sale_making_charge_type = fields.Selection(
        related='label_id.sale_making_charge_type',
        readonly=True,
    )
    sale_making_charge_value = fields.Float(
        related='label_id.sale_making_charge_value',
        readonly=True,
    )
    sale_making_charge_amount = fields.Float(
        related='label_id.sale_making_charge_amount',
        readonly=True,
    )
    tag_weight = fields.Float(related='label_id.tag_weight', readonly=True)
    purchase_gross_weight = fields.Float(related='label_id.purchase_gross_weight', readonly=True)
    purchase_net_weight = fields.Float(related='label_id.purchase_net_weight', readonly=True)
    purchase_stone_weight = fields.Float(related='label_id.purchase_stone_weight', readonly=True)
    purchase_stone_weight_ct = fields.Float(related='label_id.purchase_stone_weight_ct', readonly=True)
    purchase_diamond_weight_gm = fields.Float(
        related='label_id.purchase_diamond_weight_gm',
        readonly=True,
    )
    purchase_diamond_weight_ct = fields.Float(
        related='label_id.purchase_diamond_weight_ct',
        readonly=True,
    )
    purchase_making_charge_type = fields.Selection(
        related='label_id.purchase_making_charge_type',
        readonly=True,
    )
    purchase_making_charge_value = fields.Float(
        related='label_id.purchase_making_charge_value',
        readonly=True,
    )
    purchase_making_charge_amount = fields.Float(
        related='label_id.purchase_making_charge_amount',
        readonly=True,
    )
    mc_fine = fields.Float(related='label_id.mc_fine', readonly=True)
