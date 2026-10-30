# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class PoLabelTracker(models.Model):
    _name = 'po.label.tracker'
    _description = 'Purchase Order Label Tracker'
    _order = 'po_date desc, id desc'
    _rec_name = 'purchase_id'

    purchase_id = fields.Many2one(
        'purchase.order',
        string="Purchase Order",
        required=True,
        ondelete='cascade',
        index=True,
        domain="[('state', 'in', ['purchase', 'done'])]",
    )
    product_template_id = fields.Many2one(
        'product.template',
        string="Product Template",
        domain="[('id', 'in', available_product_template_ids)]",
    )
    available_product_template_ids = fields.Many2many(
        'product.template',
        compute='_compute_available_product_templates',
        string="Available Product Templates",
    )
    name = fields.Char(
        string="PO Reference",
        related='purchase_id.name',
        store=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Vendor",
        related='purchase_id.partner_id',
        store=True,
        readonly=True,
    )
    po_date = fields.Datetime(
        string="PO Date",
        related='purchase_id.date_order',
        store=True,
    )
    po_state = fields.Selection(
        related='purchase_id.state',
        string="PO Status",
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string="Company",
        related='purchase_id.company_id',
        store=True,
    )
    total_weight = fields.Float(
        string="Total PO Weight (g)",
        compute='_compute_po_weights',
        digits=(16, 3),
        store=True,
    )
    total_labelled = fields.Float(
        string="Labelled Weight (g)",
        compute='_compute_po_weights',
        digits=(16, 3),
        store=True,
    )
    weight_left_to_label = fields.Float(
        string="Weight Left to Label (g)",
        compute='_compute_po_weights',
        digits=(16, 3),
        store=True,
    )
    total_labels_count = fields.Integer(
        string="Total Labels",
        compute='_compute_po_weights',
        store=True,
    )
    active_labels_count = fields.Integer(
        string="Active Labels",
        compute='_compute_po_weights',
        store=True,
    )
    inactive_labels_count = fields.Integer(
        string="Inactive Labels",
        compute='_compute_po_weights',
        store=True,
    )
    sold_labels_count = fields.Integer(
        string="Sold Labels",
        compute='_compute_po_weights',
        store=True,
    )
    not_activated_labels_count = fields.Integer(
        string="Not Activated Labels",
        compute='_compute_po_weights',
        store=True,
    )
    fulfillment_pct = fields.Float(
        string="Labeling %",
        compute='_compute_po_weights',
        digits=(16, 1),
        store=True,
    )
    label_ids = fields.Many2many(
        'product.label',
        string="Labels against PO",
        compute='_compute_labels',
    )

    def _split_inactive_counts(self, labels):
        inactive_labels = labels.filtered(lambda l: not l.active)
        if not inactive_labels:
            return 0, 0
        self.env.cr.execute("""
            SELECT DISTINCT label_id FROM sale_order_line 
            WHERE label_id IN %s
        """, (tuple(inactive_labels.ids),))
        sold_ids = set(r[0] for r in self.env.cr.fetchall())

        self.env.cr.execute("""
            SELECT DISTINCT aml.label_id FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            WHERE aml.label_id IN %s AND am.move_type = 'out_invoice' AND am.state != 'cancel'
        """, (tuple(inactive_labels.ids),))
        sold_ids.update(r[0] for r in self.env.cr.fetchall())

        sold_count = sum(1 for l in inactive_labels if l.id in sold_ids or (l.branch_location_id and l.branch_location_id.usage == 'customer'))
        not_activated_count = len(inactive_labels) - sold_count
        return sold_count, not_activated_count

    @api.depends('purchase_id')
    def _compute_available_product_templates(self):
        for rec in self:
            if not rec.purchase_id:
                rec.available_product_template_ids = [(5, 0, 0)]
                continue
            tmpl_ids = set()
            for line in rec.purchase_id.order_line:
                if getattr(line, 'product_template_id', False):
                    tmpl_ids.add(line.product_template_id.id)
                elif line.product_id and line.product_id.product_tmpl_id:
                    tmpl_ids.add(line.product_id.product_tmpl_id.id)

            labels = self.env['product.label'].with_context(active_test=False).search([
                ('purchase_id', '=', rec.purchase_id.id)
            ])
            for label in labels:
                if label.product_template_id:
                    tmpl_ids.add(label.product_template_id.id)
                elif label.product_id and label.product_id.product_tmpl_id:
                    tmpl_ids.add(label.product_id.product_tmpl_id.id)

            rec.available_product_template_ids = [(6, 0, list(tmpl_ids))]

    @api.depends(
        'purchase_id',
        'purchase_id.total_weight',
        'purchase_id.order_line.product_qty',
        'purchase_id.order_line.qty_received',
        'purchase_id.partner_id',
        'purchase_id.label_ids',
        'purchase_id.label_ids.sale_gross_weight',
        'purchase_id.label_ids.active',
        'product_template_id',
    )
    def _compute_po_weights(self):
        for rec in self:
            if not rec.purchase_id:
                rec.total_weight = 0.0
                rec.total_labelled = 0.0
                rec.weight_left_to_label = 0.0
                rec.total_labels_count = 0
                rec.active_labels_count = 0
                rec.inactive_labels_count = 0
                rec.sold_labels_count = 0
                rec.not_activated_labels_count = 0
                rec.fulfillment_pct = 0.0
                continue

            po = rec.purchase_id
            domain = [('purchase_id', '=', po.id)]
            if rec.product_template_id:
                domain += [
                    '|',
                    ('product_template_id', '=', rec.product_template_id.id),
                    ('product_id.product_tmpl_id', '=', rec.product_template_id.id)
                ]

            labels = self.env['product.label'].with_context(active_test=False).search(domain)

            if rec.product_template_id:
                matching_lines = po.order_line.filtered(
                    lambda l: l.product_id.product_tmpl_id == rec.product_template_id or (getattr(l, 'product_template_id', False) == rec.product_template_id)
                )
                po_prod_lines = matching_lines.filtered(lambda l: l.product_id.detailed_type == 'product')
                if po_prod_lines and any(po_prod_lines.mapped('qty_received')):
                    total_po_wt = sum(po_prod_lines.mapped('qty_received'))
                elif matching_lines:
                    total_po_wt = sum(matching_lines.mapped('product_qty'))
                else:
                    total_po_wt = sum(labels.mapped('sale_gross_weight'))
            else:
                total_po_wt = po.total_weight or sum(po.order_line.mapped('product_qty'))

            labeled_wt = sum(labels.mapped('sale_gross_weight'))
            left_wt = max(0.0, total_po_wt - labeled_wt)

            sold_count, not_activated_count = rec._split_inactive_counts(labels)

            rec.total_weight = total_po_wt
            rec.total_labelled = labeled_wt
            rec.weight_left_to_label = left_wt
            rec.total_labels_count = len(labels)
            rec.active_labels_count = len(labels.filtered(lambda l: l.active))
            rec.inactive_labels_count = len(labels.filtered(lambda l: not l.active))
            rec.sold_labels_count = sold_count
            rec.not_activated_labels_count = not_activated_count
            rec.fulfillment_pct = min(100.0, round((labeled_wt / total_po_wt * 100.0), 1)) if total_po_wt > 0 else (100.0 if labeled_wt > 0 else 0.0)

    @api.depends('purchase_id', 'product_template_id')
    def _compute_labels(self):
        for rec in self:
            if rec.purchase_id:
                domain = [('purchase_id', '=', rec.purchase_id.id)]
                if rec.product_template_id:
                    domain += [
                        '|',
                        ('product_template_id', '=', rec.product_template_id.id),
                        ('product_id.product_tmpl_id', '=', rec.product_template_id.id)
                    ]
                labels = self.env['product.label'].with_context(active_test=False).search(domain)
                rec.label_ids = [(6, 0, labels.ids)]
            else:
                rec.label_ids = [(5, 0, 0)]

    @api.onchange('product_template_id')
    def _onchange_product_template_id(self):
        self._compute_labels()
        self._compute_po_weights()

    @api.onchange('purchase_id')
    def _onchange_purchase_id(self):
        self.product_template_id = False
        if self.purchase_id:
            self.partner_id = self.purchase_id.partner_id.id
            self.company_id = self.purchase_id.company_id.id
            self.po_date = self.purchase_id.date_order
            self.po_state = self.purchase_id.state
            self._compute_available_product_templates()
            self._compute_labels()
            self._compute_po_weights()
        else:
            self.partner_id = False
            self.available_product_template_ids = [(5, 0, 0)]
            self.label_ids = [(5, 0, 0)]
            self.total_weight = 0.0
            self.total_labelled = 0.0
            self.weight_left_to_label = 0.0
            self.total_labels_count = 0
            self.active_labels_count = 0
            self.inactive_labels_count = 0
            self.sold_labels_count = 0
            self.not_activated_labels_count = 0
            self.fulfillment_pct = 0.0

    def action_refresh(self):
        self._compute_available_product_templates()
        self._compute_po_weights()
        self._compute_labels()

    def action_open_purchase_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.purchase_id.name,
            'res_model': 'purchase.order',
            'res_id': self.purchase_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_label(self):
        self.ensure_one()
        context = {
            'default_purchase_id': self.purchase_id.id,
            'default_partner_id': self.partner_id.id if self.partner_id else False,
        }
        if self.product_template_id:
            context['default_product_template_id'] = self.product_template_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Product Label'),
            'res_model': 'product.label',
            'view_mode': 'form',
            'target': 'current',
            'context': context,
        }

    @api.model
    def sync_existing_purchase_orders(self):
        """Pre-populate tracker records for purchase orders that have product labels."""
        po_ids_with_labels = self.env['product.label'].with_context(active_test=False).search([
            ('purchase_id', '!=', False)
        ]).mapped('purchase_id.id')

        existing_tracked = self.search([]).mapped('purchase_id.id')
        to_create = set(po_ids_with_labels) - set(existing_tracked)
        if to_create:
            self.create([{'purchase_id': p_id} for p_id in to_create])


class ProductLabel(models.Model):
    _inherit = 'product.label'

    sold_status = fields.Selection([
        ('sold', 'Sold'),
        ('not_activated', 'Not Activated'),
    ], string="Status", compute='_compute_sold_status')

    @api.depends('active', 'branch_location_id')
    def _compute_sold_status(self):
        inactive_labels = self.filtered(lambda l: not l.active)
        sold_ids = set()
        if inactive_labels:
            self.env.cr.execute("""
                SELECT DISTINCT label_id FROM sale_order_line 
                WHERE label_id IN %s
            """, (tuple(inactive_labels.ids),))
            sold_ids.update(r[0] for r in self.env.cr.fetchall())

            self.env.cr.execute("""
                SELECT DISTINCT aml.label_id FROM account_move_line aml
                JOIN account_move am ON am.id = aml.move_id
                WHERE aml.label_id IN %s AND am.move_type = 'out_invoice' AND am.state != 'cancel'
            """, (tuple(inactive_labels.ids),))
            sold_ids.update(r[0] for r in self.env.cr.fetchall())

        for rec in self:
            if rec.active:
                if rec.branch_location_id and rec.branch_location_id.usage == 'customer':
                    rec.sold_status = 'sold'
                else:
                    rec.sold_status = False
            else:
                if rec.id in sold_ids or (rec.branch_location_id and rec.branch_location_id.usage == 'customer'):
                    rec.sold_status = 'sold'
                else:
                    rec.sold_status = 'not_activated'
