# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockLocationProductLoadWizard(models.TransientModel):
    _name = 'stock.location.product.load.wizard'
    _description = 'Load Products for Excess Weight Verification'

    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        default=lambda self: getattr(self.env.user, 'branch_id', False)
    )
    all_locations = fields.Boolean(
        string='All Internal Locations in Branch',
        default=True
    )
    location_ids = fields.Many2many(
        'stock.location',
        string='Specific Locations',
        domain="[('usage', '=', 'internal')]"
    )
    all_products = fields.Boolean(
        string='All Product Variants',
        default=True
    )
    product_ids = fields.Many2many(
        'product.product',
        string='Product Variants',
        domain="[('type', '=', 'product')]"
    )

    @api.onchange('branch_id', 'all_locations')
    def _onchange_branch(self):
        if self.branch_id and not self.all_locations:
            return {'domain': {'location_ids': [('usage', '=', 'internal'), ('branch_id', '=', self.branch_id.id)]}}
        return {'domain': {'location_ids': [('usage', '=', 'internal')]}}

    def action_load_products(self):
        self.ensure_one()
        domain = [('usage', '=', 'internal')]
        if self.branch_id:
            domain.append(('branch_id', '=', self.branch_id.id))
        if not self.all_locations and self.location_ids:
            domain = [('id', 'in', self.location_ids.ids)]

        locations = self.env['stock.location'].search(domain)
        if not locations:
            raise UserError(_("No internal stock locations found for the selected criteria."))

        total_created = 0
        total_refreshed = 0

        target_product_ids = self.product_ids.ids if not self.all_products and self.product_ids else None

        for loc in locations:
            if target_product_ids:
                self.env.cr.execute("""
                    SELECT DISTINCT product_id FROM product_label 
                    WHERE branch_location_id = %s AND active = TRUE AND product_id IN %s
                    UNION
                    SELECT DISTINCT product_id FROM stock_quant
                    WHERE location_id = %s AND quantity > 0 AND product_id IN %s
                """, (loc.id, tuple(target_product_ids), loc.id, tuple(target_product_ids)))
                product_ids = [r[0] for r in self.env.cr.fetchall()]
                for tpid in target_product_ids:
                    if tpid not in product_ids:
                        product_ids.append(tpid)
            else:
                self.env.cr.execute("""
                    SELECT DISTINCT product_id FROM product_label 
                    WHERE branch_location_id = %s AND active = TRUE AND product_id IS NOT NULL
                    UNION
                    SELECT DISTINCT product_id FROM stock_quant
                    WHERE location_id = %s AND quantity > 0 AND product_id IS NOT NULL
                """, (loc.id, loc.id))
                product_ids = [r[0] for r in self.env.cr.fetchall()]

            existing_recs = self.env['stock.location.product.excess.weight'].search([
                ('location_id', '=', loc.id)
            ])
            existing_prod_ids = set(existing_recs.mapped('product_id.id'))

            new_recs = []
            for pid in product_ids:
                if pid not in existing_prod_ids:
                    new_recs.append({
                        'location_id': loc.id,
                        'product_id': pid,
                        'system_weight_basis': loc.system_weight_basis or 'quant',
                    })
            if new_recs:
                self.env['stock.location.product.excess.weight'].create(new_recs)
                total_created += len(new_recs)

            if target_product_ids:
                all_lines = self.env['stock.location.product.excess.weight'].search([
                    ('location_id', '=', loc.id),
                    ('product_id', 'in', target_product_ids)
                ])
            else:
                all_lines = self.env['stock.location.product.excess.weight'].search([('location_id', '=', loc.id)])

            all_lines._compute_system_weights()
            all_lines._compute_physical_weight()
            all_lines._compute_difference()
            total_refreshed += len(all_lines)

        action_domain = [('location_id', 'in', locations.ids)]
        if target_product_ids:
            action_domain.append(('product_id', 'in', target_product_ids))

        return {
            'name': _('Excess Weight by Product Variant'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.location.product.excess.weight',
            'view_mode': 'tree',
            'domain': action_domain,
            'context': {'search_default_group_location': 1},
        }
