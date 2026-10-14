# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class StockLocationProductExcessWeight(models.Model):
    _name = 'stock.location.product.excess.weight'
    _description = 'Location Excess Weight by Product Variant'
    _order = 'location_id, product_id'
    _rec_name = 'product_id'

    location_id = fields.Many2one(
        'stock.location',
        string='Stock Location',
        required=True,
        ondelete='cascade',
        index=True
    )
    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        related='location_id.branch_id',
        store=True,
        readonly=True,
        index=True
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        required=True,
        ondelete='cascade',
        index=True
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        related='product_id.product_tmpl_id',
        store=True,
        readonly=True
    )
    categ_id = fields.Many2one(
        'product.category',
        string='Product Category',
        related='product_id.categ_id',
        store=True,
        readonly=True
    )
    default_code = fields.Char(
        string='Internal Reference',
        related='product_id.default_code',
        readonly=True
    )

    system_label_count = fields.Integer(
        string='Active Labels Count',
        compute='_compute_system_weights',
        store=True,
        help='Count of active product labels for this variant in this location.'
    )
    system_label_weight = fields.Float(
        string='Labels Gross Weight (g)',
        digits=(16, 3),
        compute='_compute_system_weights',
        store=True,
        help='Total gross weight (grams) of active labels for this variant in this location.'
    )
    system_quant_weight = fields.Float(
        string='Stock Quant Weight (g)',
        digits=(16, 3),
        compute='_compute_system_weights',
        store=True,
        help='On-hand ledger stock in stock.quant for this product in this location.'
    )
    system_weight_basis = fields.Selection([
        ('quant', 'Stock Quant Weight'),
        ('label', 'Active Labels Weight'),
    ], string='Basis', default='quant', required=True)

    system_weight = fields.Float(
        string='System Weight (g)',
        digits=(16, 3),
        compute='_compute_system_weights',
        store=True,
        help='System registered weight according to selected basis.'
    )

    is_physical_weight_set = fields.Boolean(
        string='Physical Weight Set',
        default=False,
        copy=False
    )
    physical_weight = fields.Float(
        string='Physical Weight (g)',
        digits=(16, 3),
        compute='_compute_physical_weight',
        store=True,
        readonly=False,
        copy=False,
        help='Scale weight measured physically for this product variant in this location.'
    )
    weight_tolerance = fields.Float(
        string='Tolerance (±g)',
        digits=(16, 3),
        default=0.0,
        help='Allowed tolerance before marking as excess or shortage.'
    )

    difference_weight = fields.Float(
        string='Difference Weight (g)',
        digits=(16, 3),
        compute='_compute_difference',
        store=True,
        help='Physical Weight minus System Weight. Positive = Excess, Negative = Shortage.'
    )
    excess_weight = fields.Float(
        string='Excess Weight (g)',
        digits=(16, 3),
        compute='_compute_difference',
        store=True,
        help='Physical weight exceeding system weight.'
    )
    shortage_weight = fields.Float(
        string='Shortage Weight (g)',
        digits=(16, 3),
        compute='_compute_difference',
        store=True,
        help='Physical weight missing compared to system weight.'
    )
    weight_status = fields.Selection([
        ('unverified', 'Unverified'),
        ('balanced', 'Balanced (Matched)'),
        ('excess', 'Excess Weight (Surplus)'),
        ('shortage', 'Shortage Weight (Deficit)'),
    ], string='Status', compute='_compute_difference', store=True, default='unverified')

    last_weight_check_date = fields.Datetime(
        string='Last Weighed Date'
    )
    last_weight_check_user_id = fields.Many2one(
        'res.users',
        string='Last Weighed By'
    )
    notes = fields.Char(string='Remarks / Tray')

    _sql_constraints = [
        ('location_product_uniq', 'unique(location_id, product_id)',
         'A weight record for this location and product variant already exists!')
    ]

    @api.depends('location_id', 'product_id', 'system_weight_basis')
    def _compute_system_weights(self):
        loc_prod_pairs = [(r.location_id.id, r.product_id.id) for r in self if r.location_id and r.product_id]
        if not loc_prod_pairs:
            for rec in self:
                rec.system_label_count = 0
                rec.system_label_weight = 0.0
                rec.system_quant_weight = 0.0
                rec.system_weight = 0.0
            return

        loc_ids = tuple({p[0] for p in loc_prod_pairs})
        prod_ids = tuple({p[1] for p in loc_prod_pairs})

        # Batch query labels
        self.env.cr.execute("""
            SELECT branch_location_id, product_id, COUNT(*) AS cnt, COALESCE(SUM(sale_gross_weight), 0.0) AS total_wt
            FROM product_label
            WHERE branch_location_id IN %s AND product_id IN %s AND active = TRUE
            GROUP BY branch_location_id, product_id
        """, (loc_ids, prod_ids))
        label_data = {(r[0], r[1]): (r[2], float(r[3])) for r in self.env.cr.fetchall()}

        # Batch query quants
        self.env.cr.execute("""
            SELECT location_id, product_id, COALESCE(SUM(quantity), 0.0) AS total_wt
            FROM stock_quant
            WHERE location_id IN %s AND product_id IN %s AND quantity > 0
            GROUP BY location_id, product_id
        """, (loc_ids, prod_ids))
        quant_data = {(r[0], r[1]): float(r[2]) for r in self.env.cr.fetchall()}

        for rec in self:
            pair = (rec.location_id.id, rec.product_id.id)
            cnt, lbl_wt = label_data.get(pair, (0, 0.0))
            q_wt = quant_data.get(pair, 0.0)

            rec.system_label_count = cnt
            rec.system_label_weight = round(lbl_wt, 3)
            rec.system_quant_weight = round(q_wt, 3)

            if rec.system_weight_basis == 'label':
                rec.system_weight = rec.system_label_weight if (cnt > 0 or lbl_wt > 0) else rec.system_quant_weight
            else:
                rec.system_weight = rec.system_quant_weight

    @api.depends('system_label_weight', 'system_label_count', 'system_quant_weight', 'system_weight_basis', 'location_id.system_label_count')
    def _compute_physical_weight(self):
        for rec in self:
            if not rec.is_physical_weight_set:
                if rec.location_id.system_label_count > 0:
                    rec.physical_weight = rec.system_label_weight
                else:
                    rec.physical_weight = rec.system_quant_weight

    def action_auto_fill_physical_weight(self):
        """Auto-fill physical weight from active labels weight (or quant weight if unlabelled)."""
        for rec in self:
            val = rec.system_label_weight if rec.location_id.system_label_count > 0 else rec.system_quant_weight
            rec.with_context(skip_weight_set_flag=True).write({
                'physical_weight': val,
                'is_physical_weight_set': False,
            })
        return True

    @api.depends('system_quant_weight', 'physical_weight', 'system_label_weight', 'weight_tolerance', 'last_weight_check_date')
    def _compute_difference(self):
        for rec in self:
            eff_phys = rec.physical_weight if rec.is_physical_weight_set else rec.system_label_weight
            diff = round((rec.system_quant_weight or 0.0) - (eff_phys or 0.0), 3)
            rec.difference_weight = diff

            if (rec.system_quant_weight or 0.0) == 0.0 and (eff_phys or 0.0) == 0.0 and not rec.last_weight_check_date:
                rec.excess_weight = 0.0
                rec.shortage_weight = 0.0
                rec.weight_status = 'unverified'
            else:
                tol = abs(rec.weight_tolerance or 0.0)
                if abs(diff) <= tol:
                    rec.excess_weight = 0.0
                    rec.shortage_weight = 0.0
                    rec.weight_status = 'balanced'
                elif diff > tol:
                    rec.excess_weight = round(diff, 3)
                    rec.shortage_weight = 0.0
                    rec.weight_status = 'excess'
                else:
                    rec.excess_weight = 0.0
                    rec.shortage_weight = round(abs(diff), 3)
                    rec.weight_status = 'shortage'

    def write(self, vals):
        if 'physical_weight' in vals and not self.env.context.get('skip_weight_set_flag'):
            now = fields.Datetime.now()
            user_id = self.env.uid
            vals.setdefault('last_weight_check_date', now)
            vals.setdefault('last_weight_check_user_id', user_id)
            vals.setdefault('is_physical_weight_set', True)
        return super().write(vals)

    def action_view_labels(self):
        self.ensure_one()
        return {
            'name': _('Active Labels: %s in %s') % (self.product_id.display_name, self.location_id.display_name),
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [
                ('branch_location_id', '=', self.location_id.id),
                ('product_id', '=', self.product_id.id),
                ('active', '=', True),
            ],
            'context': {
                'default_branch_location_id': self.location_id.id,
                'default_product_id': self.product_id.id,
                'default_branch_id': self.branch_id.id if self.branch_id else False,
            }
        }

    def action_open_transfer_wizard(self):
        self.ensure_one()
        t_weight = self.excess_weight if self.excess_weight > 0 else (self.system_quant_weight if self.system_quant_weight > 0 else 0.0)
        return {
            'name': _('Transfer Excess Weight: %s') % self.product_id.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.location.product.excess.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'stock.location.product.excess.weight',
                'active_ids': self.ids,
                'active_id': self.id,
                'default_transfer_type': 'outbound',
                'default_location_id': self.location_id.id,
                'default_line_ids': [(0, 0, {
                    'excess_weight_id': self.id,
                    'product_id': self.product_id.id,
                    'system_quant_weight': self.system_quant_weight,
                    'physical_weight': self.physical_weight,
                    'excess_weight': self.excess_weight,
                    'shortage_weight': self.shortage_weight,
                    'transfer_weight': round(t_weight, 3),
                })],
            }
        }

    def action_open_shortage_wizard(self):
        self.ensure_one()
        t_weight = self.shortage_weight if self.shortage_weight > 0 else 0.0
        return {
            'name': _('Fulfill Shortage Weight: %s') % self.product_id.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.location.product.excess.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'stock.location.product.excess.weight',
                'active_ids': self.ids,
                'active_id': self.id,
                'default_transfer_type': 'inbound',
                'default_location_dest_id': self.location_id.id,
                'default_line_ids': [(0, 0, {
                    'excess_weight_id': self.id,
                    'product_id': self.product_id.id,
                    'system_quant_weight': self.system_quant_weight,
                    'physical_weight': self.physical_weight,
                    'excess_weight': self.excess_weight,
                    'shortage_weight': self.shortage_weight,
                    'transfer_weight': round(t_weight, 3),
                })],
            }
        }


