from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class OldGoldHOTransferWizard(models.TransientModel):
    _name = 'old.gold.ho.transfer.wizard'
    _description = 'Old Gold HO Transfer Wizard'

    branch_id = fields.Many2one('res.branch', string="Branch", readonly=True)
    company_id = fields.Many2one('res.company', string="Company", readonly=True)
    source_location_id = fields.Many2one(
        'stock.location',
        string="Source (Branch) Location",
        required=True,
    )
    ho_location_id = fields.Many2one(
        'stock.location',
        string="HO Location",
        required=True,
    )
    line_ids = fields.Many2many(
        'sale.old.gold.line',
        'old_gold_ho_transfer_wizard_line_rel',
        'wizard_id',
        'line_id',
        string="Selected Pieces",
    )
    total_pieces = fields.Integer(string="Total Pieces", compute="_compute_totals")
    total_gross_weight = fields.Float(string="Total Gross Weight", digits=(16, 3), compute="_compute_totals")
    total_net_weight = fields.Float(string="Total Net Weight", digits=(16, 3), compute="_compute_totals")

    @api.depends('line_ids', 'line_ids.gross_weight', 'line_ids.net_weight')
    def _compute_totals(self):
        for wizard in self:
            wizard.total_pieces = len(wizard.line_ids)
            wizard.total_gross_weight = sum(wizard.line_ids.mapped('gross_weight'))
            wizard.total_net_weight = sum(wizard.line_ids.mapped('net_weight'))

    def _get_lines_from_context(self):
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or (
            [self.env.context['active_id']] if self.env.context.get('active_id') else []
        )
        if not active_ids:
            return self.env['sale.old.gold.line']

        if active_model == 'sale.old.gold.line':
            return self.env['sale.old.gold.line'].browse(active_ids).exists()

        purchases = self.env['old.gold.purchase'].browse(active_ids).exists()
        empty_purchases = purchases.filtered(lambda p: not p.old_gold_line_ids)
        if empty_purchases:
            raise ValidationError(_(
                "Selected Old Gold Purchase(s) have no pieces to transfer: %s"
            ) % ", ".join(empty_purchases.mapped('name')))
        return purchases.mapped('old_gold_line_ids')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        lines = self._get_lines_from_context()
        if not lines:
            return res

        lines._validate_ho_transfer_lines()

        branch = lines[0].branch_id
        company = lines[0].company_id or branch.company_id or self.env.company
        default_src_loc = lines[0]._get_effective_source_location()

        res.update({
            'branch_id': branch.id,
            'company_id': company.id,
            'line_ids': [(6, 0, lines.ids)],
            'source_location_id': default_src_loc.id if default_src_loc else False,
        })
        return res

    def action_confirm_transfer(self):
        self.ensure_one()
        lines = self.line_ids or self._get_lines_from_context()
        lines._validate_ho_transfer_lines()

        if self.source_location_id == self.ho_location_id:
            raise ValidationError(_("Source Location and HO Location cannot be the same."))

        purchases = lines.mapped('old_gold_purchase_id')
        branch = lines[0].branch_id
        company = lines[0].company_id or branch.company_id or self.source_location_id.company_id or self.env.company
        company_id = company.id

        picking_type = self.env['stock.picking.type'].sudo().search([
            ('code', '=', 'internal'),
            ('company_id', '=', company_id),
        ], limit=1)
        if not picking_type:
            picking_type = self.env.ref('stock.picking_type_internal').sudo()

        origin_names = ", ".join(dict.fromkeys(p.name for p in purchases if p.name))
        sale_ids = purchases.mapped('sale_id')

        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': picking_type.id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.ho_location_id.id,
            'origin': origin_names or False,
            'branch_id': branch.id if branch else False,
            'sale_old_id': sale_ids[0].id if len(sale_ids) == 1 else False,
            'is_old_gold': True,
            'company_id': company_id,
        })

        StockMove = self.env['stock.move'].sudo()
        for line in lines:
            purchase = line.old_gold_purchase_id
            product = purchase._get_old_gold_product(is_diamond_og=line.is_diamond_og)
            if not product:
                raise ValidationError(_(
                    "Old Gold product not configured for company %s."
                ) % company.name)

            StockMove.create({
                'product_id': product.id,
                'name': (
                    f"{purchase.name} - Old Gold ({line.purity_id.name})"
                    if purchase.name else f"Old Gold ({line.purity_id.name})"
                ),
                'purity_id': line.purity_id.id,
                'old_gold_line_id': line.id,
                'product_uom_qty': line.net_weight,
                'product_uom': product.uom_id.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'picking_id': picking.id,
                'company_id': company_id,
            })

        picking.sudo().action_confirm()

        lines.write({'ho_transfer_id': picking.id})
        for purchase in purchases:
            vals = {
                'branch_location_id': self.source_location_id.id,
                'ho_location_id': self.ho_location_id.id,
            }
            if all(l.ho_transfer_id for l in purchase.old_gold_line_ids):
                vals['state'] = 'ho_transfer'
            purchase.write(vals)

        return {
            'type': 'ir.actions.act_window',
            'name': _('HO Transfer'),
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }

