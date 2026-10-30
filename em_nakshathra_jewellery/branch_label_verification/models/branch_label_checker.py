# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class BranchLabelChecker(models.TransientModel):
    _name = 'branch.label.checker'
    _description = 'Branch Label Count & Overview Tool'

    def _get_default_branch(self):
        return self.env.user.branch_id.id if hasattr(self.env.user, 'branch_id') and self.env.user.branch_id else False

    branch_id = fields.Many2one(
        'res.branch',
        string='Selected Branch',
        default=_get_default_branch,
        required=True,
    )
    total_labels_count = fields.Integer(
        string='Total Labels in Branch',
        compute='_compute_branch_label_stats',
    )
    active_labels_count = fields.Integer(
        string='Active Labels (In Stock)',
        compute='_compute_branch_label_stats',
    )
    inactive_labels_count = fields.Integer(
        string='Inactive / Sold Labels',
        compute='_compute_branch_label_stats',
    )
    total_gross_weight = fields.Float(
        string='Total Gross Weight (g)',
        compute='_compute_branch_label_stats',
        digits=(16, 3),
    )
    total_net_weight = fields.Float(
        string='Total Net Weight (g)',
        compute='_compute_branch_label_stats',
        digits=(16, 3),
    )
    active_gross_weight = fields.Float(
        string='Active Gross Weight (g)',
        compute='_compute_branch_label_stats',
        digits=(16, 3),
    )

    location_summary_ids = fields.One2many(
        'branch.label.checker.location.line',
        'checker_id',
        string='Location Breakdown',
        compute='_compute_breakdowns',
    )
    category_summary_ids = fields.One2many(
        'branch.label.checker.category.line',
        'checker_id',
        string='Category Breakdown',
        compute='_compute_breakdowns',
    )

    @api.depends('branch_id')
    def _compute_branch_label_stats(self):
        cr = self.env.cr
        for rec in self:
            if not rec.branch_id:
                rec.total_labels_count = 0
                rec.active_labels_count = 0
                rec.inactive_labels_count = 0
                rec.total_gross_weight = 0.0
                rec.total_net_weight = 0.0
                rec.active_gross_weight = 0.0
                continue

            b_id = rec.branch_id.id
            cr.execute("""
                SELECT 
                    COUNT(*) AS total_count,
                    COUNT(*) FILTER (WHERE active = true) AS active_count,
                    COUNT(*) FILTER (WHERE active = false) AS inactive_count,
                    COALESCE(SUM(sale_gross_weight), 0.0) AS total_gross,
                    COALESCE(SUM(sale_net_weight), 0.0) AS total_net,
                    COALESCE(SUM(sale_gross_weight) FILTER (WHERE active = true), 0.0) AS active_gross
                FROM product_label
                WHERE branch_id = %s
            """, (b_id,))
            res = cr.dictfetchone() or {}
            rec.total_labels_count = res.get('total_count', 0)
            rec.active_labels_count = res.get('active_count', 0)
            rec.inactive_labels_count = res.get('inactive_count', 0)
            rec.total_gross_weight = res.get('total_gross', 0.0)
            rec.total_net_weight = res.get('total_net', 0.0)
            rec.active_gross_weight = res.get('active_gross', 0.0)

    @api.depends('branch_id')
    def _compute_breakdowns(self):
        cr = self.env.cr
        for rec in self:
            loc_lines = []
            cat_lines = []
            if rec.branch_id:
                b_id = rec.branch_id.id
                # 1. Location breakdown
                cr.execute("""
                    SELECT 
                        l.branch_location_id AS location_id,
                        COUNT(*) AS total_count,
                        COUNT(*) FILTER (WHERE l.active = true) AS active_count,
                        COUNT(*) FILTER (WHERE l.active = false) AS inactive_count,
                        COALESCE(SUM(l.sale_gross_weight), 0.0) AS total_gross
                    FROM product_label l
                    WHERE l.branch_id = %s
                    GROUP BY l.branch_location_id
                    ORDER BY total_count DESC
                """, (b_id,))
                for row in cr.dictfetchall():
                    loc_lines.append((0, 0, {
                        'location_id': row.get('location_id'),
                        'total_count': row.get('total_count', 0),
                        'active_count': row.get('active_count', 0),
                        'inactive_count': row.get('inactive_count', 0),
                        'total_weight': row.get('total_gross', 0.0),
                    }))

                # 2. Category breakdown
                cr.execute("""
                    SELECT 
                        pt.categ_id AS categ_id,
                        COUNT(*) AS total_count,
                        COUNT(*) FILTER (WHERE l.active = true) AS active_count,
                        COUNT(*) FILTER (WHERE l.active = false) AS inactive_count,
                        COALESCE(SUM(l.sale_gross_weight), 0.0) AS total_gross
                    FROM product_label l
                    JOIN product_product pp ON pp.id = l.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE l.branch_id = %s
                    GROUP BY pt.categ_id
                    ORDER BY total_count DESC
                """, (b_id,))
                for row in cr.dictfetchall():
                    cat_lines.append((0, 0, {
                        'categ_id': row.get('categ_id'),
                        'total_count': row.get('total_count', 0),
                        'active_count': row.get('active_count', 0),
                        'inactive_count': row.get('inactive_count', 0),
                        'total_weight': row.get('total_gross', 0.0),
                    }))

            rec.location_summary_ids = loc_lines
            rec.category_summary_ids = cat_lines

    def action_start_verification(self):
        """Directly launch a new verification session for this branch."""
        self.ensure_one()
        audit = self.env['branch.label.verification'].create({
            'branch_id': self.branch_id.id,
            'label_filter': 'active',
            'date': fields.Date.today(),
            'user_id': self.env.user.id,
        })
        audit.action_load_branch_labels()
        return {
            'name': _("Branch Label Verification"),
            'type': 'ir.actions.act_window',
            'res_model': 'branch.label.verification',
            'res_id': audit.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_all_labels(self):
        """Open the product labels for this branch."""
        self.ensure_one()
        return {
            'name': _("Labels in %s") % (self.branch_id.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [('branch_id', '=', self.branch_id.id)],
            'context': {'active_test': False},
            'target': 'current',
        }

    def action_view_active_labels(self):
        """Open active in-stock labels for this branch."""
        self.ensure_one()
        return {
            'name': _("Active Labels in %s") % (self.branch_id.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [('branch_id', '=', self.branch_id.id), ('active', '=', True)],
            'target': 'current',
        }


class BranchLabelCheckerLocationLine(models.TransientModel):
    _name = 'branch.label.checker.location.line'
    _description = 'Branch Label Checker Location Line'

    checker_id = fields.Many2one('branch.label.checker', ondelete='cascade')
    location_id = fields.Many2one('stock.location', string='Location', readonly=True)
    total_count = fields.Integer(string='Total Labels', readonly=True)
    active_count = fields.Integer(string='Active (In Stock)', readonly=True)
    inactive_count = fields.Integer(string='Inactive / Sold', readonly=True)
    total_weight = fields.Float(string='Total Weight (g)', digits=(16, 3), readonly=True)


class BranchLabelCheckerCategoryLine(models.TransientModel):
    _name = 'branch.label.checker.category.line'
    _description = 'Branch Label Checker Category Line'

    checker_id = fields.Many2one('branch.label.checker', ondelete='cascade')
    categ_id = fields.Many2one('product.category', string='Category', readonly=True)
    total_count = fields.Integer(string='Total Labels', readonly=True)
    active_count = fields.Integer(string='Active (In Stock)', readonly=True)
    inactive_count = fields.Integer(string='Inactive / Sold', readonly=True)
    total_weight = fields.Float(string='Total Weight (g)', digits=(16, 3), readonly=True)
