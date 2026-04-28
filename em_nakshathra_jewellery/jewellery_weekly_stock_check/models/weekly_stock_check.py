from odoo import models, fields, api, _
from odoo.exceptions import UserError


class JewelleryWeeklyStockCheck(models.Model):
    _name = 'jewellery.weekly.stock.check'
    _description = 'Weekly Stock Check'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Reference', required=True, copy=False,
        readonly=True, default=lambda self: _('New')
    )
    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        required=True,
        tracking=True
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        required=True,
        domain="[('usage', '=', 'internal'), ('branch_id', '=', branch_id)]",
        tracking=True
    )
    date = fields.Date(
        string='Check Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('matched', 'Matched / Corrected'),
        ('mismatch', 'Mismatch'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    line_ids = fields.One2many(
        'jewellery.weekly.stock.check.line',
        'stock_check_id',
        string='Stock Check Lines'
    )

    template_summary_ids = fields.One2many(
        'jewellery.weekly.stock.check.template.summary',
        'stock_check_id',
        string='Template Summary'
    )

    total_lines = fields.Integer(string='Total Products', compute='_compute_summary')
    total_labels = fields.Float(string='Total Labels', compute='_compute_summary', digits=(16, 0))
    total_weight = fields.Float(string='Total Weight', compute='_compute_summary', digits=(16, 3))
    matched_lines = fields.Integer(string='Matched', compute='_compute_summary')
    mismatched_lines = fields.Integer(string='Mismatched', compute='_compute_summary')

    @api.onchange('branch_id')
    def _onchange_branch_id(self):
        if self.branch_id:
            self.location_id = False

    @api.depends('line_ids', 'line_ids.is_matched', 'line_ids.system_qty', 'line_ids.system_weight')
    def _compute_summary(self):
        for rec in self:
            rec.total_lines = len(rec.line_ids)
            rec.total_labels = sum(rec.line_ids.mapped('system_qty'))
            rec.total_weight = sum(rec.line_ids.mapped('system_weight'))
            rec.matched_lines = len(rec.line_ids.filtered('is_matched'))
            rec.mismatched_lines = rec.total_lines - rec.matched_lines

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = (
                self.env['ir.sequence'].next_by_code('jewellery.weekly.stock.check') or _('New')
            )
        return super().create(vals)

    def action_load_products(self):
        """Load products with label counts (branch) and stock weights (location)."""
        self.ensure_one()
        if not self.location_id:
            raise UserError(_("Please select a location first."))
        
        branch = self.branch_id
        if not branch:
            raise UserError(_("The selected location is not associated with any branch."))

        # Remove existing lines and summary
        self.line_ids.unlink()
        self.template_summary_ids.unlink()

        # 1. Get active labels for this branch
        labels = self.env['product.label'].search([
            ('branch_id', '=', branch.id),
            ('active', '=', True),
        ])

        # 2. Get on-hand stock quants for this location
        quants = self.env['stock.quant'].search([
            ('location_id', '=', self.location_id.id),
            ('quantity', '>', 0),
        ])

        if not labels and not quants:
            raise UserError(_("No active labels or stock found for this location/branch."))

        # Create lines per label
        lines = []
        for label in labels:
            lines.append({
                'stock_check_id': self.id,
                'product_tmpl_id': label.product_id.product_tmpl_id.id,
                'product_id': label.product_id.id,
                'label_id': label.id,
                'system_qty': 1.0,
                'system_weight': label.sale_gross_weight,
                'manual_qty': 0.0,
                'manual_weight': 0.0,
            })
            
        # Add stock for products without labels (if any)
        labeled_product_ids = labels.mapped('product_id').ids
        for quant in quants:
            if quant.product_id.id not in labeled_product_ids:
                lines.append({
                    'stock_check_id': self.id,
                    'product_tmpl_id': quant.product_id.product_tmpl_id.id,
                    'product_id': quant.product_id.id,
                    'system_qty': 0.0,
                    'system_weight': quant.quantity,
                    'manual_qty': 0.0,
                    'manual_weight': 0.0,
                })

        self.env['jewellery.weekly.stock.check.line'].create(lines)

        # Create template summary lines
        templates = self.line_ids.mapped('product_tmpl_id')
        summary_vals = []
        for tmpl in templates:
            summary_vals.append({
                'stock_check_id': self.id,
                'product_tmpl_id': tmpl.id,
            })
        if summary_vals:
            self.env['jewellery.weekly.stock.check.template.summary'].create(summary_vals)

        self.state = 'in_progress'
        return True

    def action_check_match(self):
        """Validate manual counts against system quantities and weights."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("No products loaded. Please load products first."))

        all_matched = all(line.is_matched for line in self.line_ids)
        if all_matched:
            self.state = 'matched'
        else:
            self.state = 'mismatch'
        return True

    def action_reset_counts(self):
        """Reset all manual counts so staff can recount."""
        self.ensure_one()
        self.line_ids.write({
            'manual_qty': 0.0,
            'manual_weight': 0.0,
        })
        self.state = 'in_progress'

    def action_cancel(self):
        self.state = 'cancel'

    def action_draft(self):
        self.state = 'draft'

    def action_export_counter_xlsx(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/stock_check/export_report?report_id={self.id}&report_type=counter',
            'target': 'new',
        }

    def action_export_manager_xlsx(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/stock_check/export_report?report_id={self.id}&report_type=manager',
            'target': 'new',
        }

    def action_print_report_pdf(self):
        self.ensure_one()
        if self.env.user.has_group('jewellery_weekly_stock_check.group_jewellery_stock_manager'):
            return self.env.ref('jewellery_weekly_stock_check.action_report_stock_check_manager').report_action(self)
        return self.env.ref('jewellery_weekly_stock_check.action_report_stock_check_counter').report_action(self)

    def action_print_report_xlsx(self):
        self.ensure_one()
        if self.env.user.has_group('jewellery_weekly_stock_check.group_jewellery_stock_manager'):
            return self.action_export_manager_xlsx()
        return self.action_export_counter_xlsx()


class JewelleryWeeklyStockCheckLine(models.Model):
    _name = 'jewellery.weekly.stock.check.line'
    _description = 'Weekly Stock Check Line'
    _order = 'product_tmpl_id, product_id, label_id'

    stock_check_id = fields.Many2one(
        'jewellery.weekly.stock.check',
        string='Stock Check',
        ondelete='cascade'
    )

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        readonly=True
    )

    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        required=True,
        readonly=True
    )

    label_id = fields.Many2one(
        'product.label',
        string='Label',
        readonly=True
    )

    # System values - hidden from counters via groups in the view
    system_qty = fields.Float(
        string='System Label Count',
        digits=(16, 0),
        readonly=True
    )
    system_weight = fields.Float(
        string='System Weight',
        digits=(16, 3),
        readonly=True
    )

    # Manual count input by the staff
    manual_qty = fields.Float(
        string='Counted Labels',
        digits=(16, 0),
        default=0.0
    )
    manual_weight = fields.Float(
        string='Counted Weight',
        digits=(16, 3),
        default=0.0
    )

    # Difference: positive = surplus, negative = shortage
    difference_qty = fields.Float(
        string='Diff Label',
        digits=(16, 0),
        compute='_compute_difference',
        store=True
    )
    difference_weight = fields.Float(
        string='Diff Weight',
        digits=(16, 3),
        compute='_compute_difference',
        store=True
    )

    is_qty_matched = fields.Boolean(
        string='Qty Matched',
        compute='_compute_is_matched',
        store=True
    )
    is_weight_matched = fields.Boolean(
        string='Weight Matched',
        compute='_compute_is_matched',
        store=True
    )
    is_matched = fields.Boolean(
        string='Matched',
        compute='_compute_is_matched',
        store=True
    )

    @api.depends('system_qty', 'manual_qty', 'system_weight', 'manual_weight')
    def _compute_difference(self):
        for rec in self:
            rec.difference_qty = rec.manual_qty - rec.system_qty
            rec.difference_weight = rec.manual_weight - rec.system_weight

    @api.depends('system_qty', 'manual_qty', 'system_weight', 'manual_weight')
    def _compute_is_matched(self):
        for rec in self:
            # Match if manual count equals system quantity and weight
            qty_match = abs(rec.manual_qty - rec.system_qty) < 0.001
            # Allow 100mg (0.100g) tolerance for weight
            weight_match = abs(rec.manual_weight - rec.system_weight) <= 0.100
            rec.is_qty_matched = qty_match
            rec.is_weight_matched = weight_match
            rec.is_matched = qty_match and weight_match


class JewelleryWeeklyStockCheckTemplateSummary(models.Model):
    _name = 'jewellery.weekly.stock.check.template.summary'
    _description = 'Weekly Stock Check Template Summary'
    _order = 'product_tmpl_id'

    stock_check_id = fields.Many2one(
        'jewellery.weekly.stock.check',
        string='Stock Check',
        ondelete='cascade'
    )

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        readonly=True
    )

    system_qty = fields.Float(
        string='System Labels',
        compute='_compute_template_totals',
        store=True,
        digits=(16, 0)
    )
    system_weight = fields.Float(
        string='System Weight',
        compute='_compute_template_totals',
        store=True,
        digits=(16, 3)
    )

    manual_qty = fields.Float(
        string='Counted Labels',
        compute='_compute_template_totals',
        store=True,
        digits=(16, 0)
    )
    manual_weight = fields.Float(
        string='Counted Weight',
        compute='_compute_template_totals',
        store=True,
        digits=(16, 3)
    )

    difference_qty = fields.Float(
        string='Diff Labels',
        compute='_compute_template_totals',
        store=True,
        digits=(16, 0)
    )
    difference_weight = fields.Float(
        string='Diff Weight',
        compute='_compute_template_totals',
        store=True,
        digits=(16, 3)
    )

    @api.depends('stock_check_id.line_ids.manual_qty', 'stock_check_id.line_ids.manual_weight',
                 'stock_check_id.line_ids.system_qty', 'stock_check_id.line_ids.system_weight')
    def _compute_template_totals(self):
        for summary in self:
            lines = summary.stock_check_id.line_ids.filtered(lambda l: l.product_tmpl_id == summary.product_tmpl_id)
            summary.system_qty = sum(lines.mapped('system_qty'))
            summary.system_weight = sum(lines.mapped('system_weight'))
            summary.manual_qty = sum(lines.mapped('manual_qty'))
            summary.manual_weight = sum(lines.mapped('manual_weight'))
            summary.difference_qty = summary.manual_qty - summary.system_qty
            summary.difference_weight = summary.manual_weight - summary.system_weight
