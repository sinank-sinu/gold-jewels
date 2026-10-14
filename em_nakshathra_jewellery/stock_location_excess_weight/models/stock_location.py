# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class StockLocation(models.Model):
    _inherit = 'stock.location'

    system_label_count = fields.Integer(
        string='Active Labels Count',
        compute='_compute_location_weights',
        store=True,
        help='Total number of active product labels currently located in this stock location.'
    )
    system_label_weight = fields.Float(
        string='Labels Gross Weight (g)',
        digits=(16, 3),
        compute='_compute_location_weights',
        store=True,
        help='Total gross weight (grams) of active labels in this location.'
    )
    system_quant_weight = fields.Float(
        string='Stock Quant Weight (g)',
        digits=(16, 3),
        compute='_compute_location_weights',
        store=True,
        help='Total on-hand stock quantity (grams) in stock.quant for this location.'
    )
    system_weight_basis = fields.Selection([
        ('quant', 'Stock Quant On-Hand Weight'),
        ('label', 'Active Labels Weight'),
    ], string='System Weight Basis', default='quant', required=True,
       help='Choose whether system weight is compared against stock.quant records or active product labels.')

    system_weight = fields.Float(
        string='System Weight (g)',
        digits=(16, 3),
        compute='_compute_location_weights',
        store=True,
        help='Effective system registered weight in grams according to selected basis.'
    )

    is_physical_weight_set = fields.Boolean(
        string='Physical Weight Manually Set',
        default=False,
        copy=False,
        help='Indicates whether physical weight was manually modified by a user.'
    )
    physical_weight = fields.Float(
        string='Physical Weight (g)',
        digits=(16, 3),
        compute='_compute_physical_weight',
        store=True,
        readonly=False,
        copy=False,
        help='Weight in grams measured physically on the scale for this location.'
    )
    weight_tolerance = fields.Float(
        string='Tolerance (±g)',
        digits=(16, 3),
        default=0.0,
        help='Acceptable variance tolerance in grams before flagging as excess or shortage.'
    )

    difference_weight = fields.Float(
        string='Difference Weight (g)',
        digits=(16, 3),
        compute='_compute_weight_difference',
        store=True,
        help='Physical Weight minus System Weight. Positive indicates excess/surplus, negative indicates shortage/deficit.'
    )
    excess_weight = fields.Float(
        string='Excess Weight (g)',
        digits=(16, 3),
        compute='_compute_weight_difference',
        store=True,
        help='Amount of physical weight exceeding the system registered weight.'
    )
    shortage_weight = fields.Float(
        string='Shortage Weight (g)',
        digits=(16, 3),
        compute='_compute_weight_difference',
        store=True,
        help='Amount of system weight missing from physical count.'
    )
    weight_status = fields.Selection([
        ('unverified', 'Unverified'),
        ('balanced', 'Balanced (Matched)'),
        ('excess', 'Excess Weight (Surplus)'),
        ('shortage', 'Shortage Weight (Deficit)'),
    ], string='Weight Status', compute='_compute_weight_difference', store=True, default='unverified',
       help='Current reconciliation status of the physical vs system weight.')

    last_weight_check_date = fields.Datetime(
        string='Last Weighed Date',
        help='Timestamp of the last physical inventory weight verification.'
    )
    last_weight_check_user_id = fields.Many2one(
        'res.users',
        string='Last Weighed By',
        help='User who recorded the last physical weight.'
    )

    weight_check_ids = fields.One2many(
        'stock.location.weight.check',
        'location_id',
        string='Weight Verification Audits'
    )
    weight_check_count = fields.Integer(
        string='Verification Count',
        compute='_compute_weight_check_count'
    )

    product_weight_ids = fields.One2many(
        'stock.location.product.excess.weight',
        'location_id',
        string='Product Variant Weights'
    )
    product_weight_count = fields.Integer(
        string='Products Count',
        compute='_compute_product_weight_count'
    )

    @api.depends('usage', 'system_weight_basis')
    def _compute_location_weights(self):
        loc_ids = [l.id for l in self if l.id]
        if not loc_ids:
            for loc in self:
                loc.system_label_count = 0
                loc.system_label_weight = 0.0
                loc.system_quant_weight = 0.0
                loc.system_weight = 0.0
            return

        # Single batch query for product.label
        self.env.cr.execute("""
            SELECT branch_location_id, COUNT(*) AS cnt, COALESCE(SUM(sale_gross_weight), 0.0) AS total_wt
            FROM product_label
            WHERE branch_location_id IN %s AND active = TRUE
            GROUP BY branch_location_id
        """, (tuple(loc_ids),))
        label_data = {r[0]: (r[1], float(r[2])) for r in self.env.cr.fetchall()}

        # Single batch query for stock.quant
        self.env.cr.execute("""
            SELECT location_id, COALESCE(SUM(quantity), 0.0) AS total_wt
            FROM stock_quant
            WHERE location_id IN %s AND quantity > 0
            GROUP BY location_id
        """, (tuple(loc_ids),))
        quant_data = {r[0]: float(r[1]) for r in self.env.cr.fetchall()}

        for loc in self:
            cnt, lbl_wt = label_data.get(loc.id, (0, 0.0))
            q_wt = quant_data.get(loc.id, 0.0)
            loc.system_label_count = cnt
            loc.system_label_weight = round(lbl_wt, 3)
            loc.system_quant_weight = round(q_wt, 3)

            if loc.system_weight_basis == 'label':
                loc.system_weight = loc.system_label_weight if (cnt > 0 or lbl_wt > 0) else loc.system_quant_weight
            else:
                loc.system_weight = loc.system_quant_weight

    @api.depends('system_label_weight', 'system_quant_weight', 'system_label_count', 'system_weight_basis')
    def _compute_physical_weight(self):
        for loc in self:
            if not loc.is_physical_weight_set:
                if loc.system_label_count > 0:
                    loc.physical_weight = loc.system_label_weight
                else:
                    loc.physical_weight = loc.system_quant_weight

    def action_auto_fill_physical_weight(self):
        """Auto-fill physical weight with active labels weight (or quant weight if unlabelled) for selected locations."""
        for loc in self:
            val = loc.system_label_weight if loc.system_label_count > 0 else loc.system_quant_weight
            loc.with_context(skip_weight_audit=True, skip_weight_set_flag=True).write({
                'physical_weight': val,
                'is_physical_weight_set': False,
            })
        return True

    @api.depends('system_quant_weight', 'physical_weight', 'system_label_weight', 'weight_tolerance', 'last_weight_check_date')
    def _compute_weight_difference(self):
        for loc in self:
            eff_phys = loc.physical_weight if loc.is_physical_weight_set else loc.system_label_weight
            diff = round((loc.system_quant_weight or 0.0) - (eff_phys or 0.0), 3)
            loc.difference_weight = diff

            if (loc.system_quant_weight or 0.0) == 0.0 and (eff_phys or 0.0) == 0.0 and not loc.last_weight_check_date:
                loc.excess_weight = 0.0
                loc.shortage_weight = 0.0
                loc.weight_status = 'unverified'
            else:
                tol = abs(loc.weight_tolerance or 0.0)
                if abs(diff) <= tol:
                    loc.excess_weight = 0.0
                    loc.shortage_weight = 0.0
                    loc.weight_status = 'balanced'
                elif diff > tol:
                    loc.excess_weight = round(diff, 3)
                    loc.shortage_weight = 0.0
                    loc.weight_status = 'excess'
                else:
                    loc.excess_weight = 0.0
                    loc.shortage_weight = round(abs(diff), 3)
                    loc.weight_status = 'shortage'

    def _compute_weight_check_count(self):
        loc_ids = [l.id for l in self if l.id]
        if not loc_ids:
            for loc in self:
                loc.weight_check_count = 0
            return
        data = self.env['stock.location.weight.check'].read_group(
            [('location_id', 'in', loc_ids)],
            ['location_id'],
            ['location_id']
        )
        count_map = {d['location_id'][0]: d['location_id_count'] for d in data if d.get('location_id')}
        for loc in self:
            loc.weight_check_count = count_map.get(loc.id, 0)

    def write(self, vals):
        if 'physical_weight' in vals and not self.env.context.get('skip_weight_audit') and not self.env.context.get('skip_weight_set_flag'):
            now = fields.Datetime.now()
            user_id = self.env.uid
            vals.setdefault('last_weight_check_date', now)
            vals.setdefault('last_weight_check_user_id', user_id)
            vals.setdefault('is_physical_weight_set', True)
            res = super().write(vals)

            # Auto create audit log if updated manually
            for loc in self:
                self.env['stock.location.weight.check'].create({
                    'location_id': loc.id,
                    'date': now,
                    'user_id': user_id,
                    'system_weight': loc.system_weight,
                    'physical_weight': loc.physical_weight,
                    'difference_weight': loc.difference_weight,
                    'excess_weight': loc.excess_weight,
                    'shortage_weight': loc.shortage_weight,
                    'status': loc.weight_status,
                    'notes': _('Recorded via direct location update.'),
                })
            return res
        return super().write(vals)

    def _compute_product_weight_count(self):
        for loc in self:
            loc.product_weight_count = len(loc.product_weight_ids)

    def action_load_or_refresh_products(self):
        """Scan active labels and quants in this location, create missing product variant weight lines, and update existing ones."""
        for loc in self:
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

            all_lines = self.env['stock.location.product.excess.weight'].search([('location_id', '=', loc.id)])
            all_lines._compute_system_weights()
            all_lines._compute_physical_weight()
            all_lines._compute_difference()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Product Variants Loaded'),
                'message': _('Product variant weight lines refreshed successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_refresh_location_weights(self):
        """Manually trigger recalculation of system weights."""
        self._compute_location_weights()
        self._compute_physical_weight()
        self._compute_weight_difference()
        for loc in self:
            if loc.product_weight_ids:
                loc.product_weight_ids._compute_system_weights()
                loc.product_weight_ids._compute_physical_weight()
                loc.product_weight_ids._compute_difference()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Weights Refreshed'),
                'message': _('System weights have been successfully refreshed for the selected location(s).'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_active_labels(self):
        self.ensure_one()
        return {
            'name': _('Active Labels: %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [('branch_location_id', '=', self.id), ('active', '=', True)],
            'context': {'default_branch_location_id': self.id, 'default_branch_id': self.branch_id.id if self.branch_id else False},
        }

    def action_view_weight_checks(self):
        self.ensure_one()
        return {
            'name': _('Weight Audits: %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.location.weight.check',
            'view_mode': 'tree,form',
            'domain': [('location_id', '=', self.id)],
            'context': {'default_location_id': self.id},
        }

    def action_open_weight_wizard(self):
        self.ensure_one()
        return {
            'name': _('Record Physical Weight - %s') % self.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.location.weight.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_location_id': self.id,
                'default_system_weight': self.system_weight,
                'default_physical_weight': self.physical_weight,
                'default_weight_tolerance': self.weight_tolerance,
            }
        }
