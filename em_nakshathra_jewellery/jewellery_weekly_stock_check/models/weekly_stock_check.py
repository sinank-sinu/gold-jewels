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
        tracking=True,
        default=lambda self: self.env.user.branch_id.id,
    )
    location_ids = fields.Many2many(
        'stock.location',
        'stock_check_location_rel',   # relation table
        'stock_check_id',
        'location_id',
        string='Locations',
        domain="[('usage', '=', 'internal'), ('branch_id', '=', branch_id)]",
        required=True,
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

    visible_line_ids = fields.One2many(
        'jewellery.weekly.stock.check.line',
        'stock_check_id',
        string='Visible Stock Check Lines',
        domain=[('is_vault_item', '=', False)]
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
            self.location_ids = [(5, 0, 0)]


    @api.depends('template_summary_ids', 'template_summary_ids.is_matched', 'line_ids', 'line_ids.system_qty', 'line_ids.system_weight')
    def _compute_summary(self):
        line_dict = {}
        if self.ids:
            line_data = self.env['jewellery.weekly.stock.check.line'].read_group(
                [('stock_check_id', 'in', self.ids)],
                ['stock_check_id', 'system_qty:sum', 'system_weight:sum'],
                ['stock_check_id']
            )
            line_dict = {d['stock_check_id'][0]: d for d in line_data}

        for rec in self:
            rec.total_lines = len(rec.template_summary_ids)
            
            if not rec.id:
                rec.total_labels = sum(rec.line_ids.mapped('system_qty'))
                rec.total_weight = sum(rec.line_ids.mapped('system_weight'))
            else:
                ld = line_dict.get(rec.id, {})
                rec.total_labels = ld.get('system_qty', 0.0)
                rec.total_weight = ld.get('system_weight', 0.0)

            rec.matched_lines = len(rec.template_summary_ids.filtered('is_matched'))
            rec.mismatched_lines = rec.total_lines - rec.matched_lines

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = (
                self.env['ir.sequence'].next_by_code('jewellery.weekly.stock.check') or _('New')
            )
        return super().create(vals)

    def action_load_products(self):
        """Load products with active label counts (branch) and vault stock."""
        self.ensure_one()
        if not self.location_ids:
            raise UserError(_("Please select at least one location."))

        branch = self.branch_id
        if not branch:
            raise UserError(_("The selected location is not associated with any branch."))

        # Remove existing lines and summary
        self.line_ids.sudo().unlink()
        self.template_summary_ids.sudo().unlink()

        # Get active labels in the selected locations
        labels = self.env['product.label'].search([
            ('branch_location_id', 'in', self.location_ids.ids),
            ('active', '=', True),
        ])

        # Get on-hand stock quants for vault items in the selected locations
        vault_quants = self.env['stock.quant'].search([
            ('location_id', 'in', self.location_ids.ids),
            ('quantity', '>', 0),
            ('product_id.product_tmpl_id.is_vault_item', '=', True)
        ])

        if not labels and not vault_quants:
            raise UserError(_("No active labels or vault stock found for this location/branch."))

        # Create lines per active label
        lines = []
        all_products = labels.mapped('product_id') | vault_quants.mapped('product_id')

        # Explicitly exclude "Old Gold" from stock checks
        all_products = all_products.filtered(
            lambda p: 'old gold' not in (p.name or '').lower() and not getattr(p, 'is_old_gold', False)
        )

        for product in all_products:
            # Handle Active Labels
            prod_labels = labels.filtered(lambda l: l.product_id == product)
            is_vault = getattr(product.product_tmpl_id, 'is_vault_item', False)

            for label in prod_labels:
                lines.append({
                    'stock_check_id': self.id,
                    'product_tmpl_id': label.product_id.product_tmpl_id.id,
                    'product_id': label.product_id.id,
                    'label_id': label.id,
                    'system_qty': 1.0,
                    'system_weight': label.sale_gross_weight,
                    'system_tag_weight': label.tag_weight,
                    'manual_qty': 0.0,
                    'manual_weight': 0.0,
                    'manual_tag_weight': 0.0,
                    'branch_id': label.branch_id.id,
                    'location_id': label.branch_location_id.id,
                    'is_vault_item': is_vault,
                })

            # Handle Vault Stock
            if is_vault:
                prod_quants = vault_quants.filtered(lambda q: q.product_id == product)
                total_vault_qty = sum(prod_quants.mapped('quantity'))
                total_label_wt = sum(prod_labels.mapped('sale_gross_weight'))
                remaining_weight = round(total_vault_qty - total_label_wt, 3)

                if remaining_weight > 0.0001:
                    loc = prod_quants[0].location_id if prod_quants else self.location_ids[0]
                    branch_rec = loc.branch_id or self.branch_id
                    lines.append({
                        'stock_check_id': self.id,
                        'product_tmpl_id': product.product_tmpl_id.id,
                        'product_id': product.id,
                        'label_id': False,
                        'system_qty': 0.0,
                        'system_weight': remaining_weight,
                        'system_tag_weight': 0.0,
                        'manual_qty': 0.0,
                        'manual_weight': 0.0,
                        'manual_tag_weight': 0.0,
                        'branch_id': branch_rec.id,
                        'location_id': loc.id,
                        'is_vault_item': True,
                    })

        self.env['jewellery.weekly.stock.check.line'].with_context(skip_line_sync=True).create(lines)

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
        if not self.template_summary_ids:
            raise UserError(_("No products loaded. Please load products first."))

        all_matched = all(summary.is_matched for summary in self.template_summary_ids)
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
            'manual_tag_weight': 0.0,
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

    @api.model
    def action_scan_barcode(self, check_id, barcode):
        """
        Called via RPC when a barcode is scanned on the Weekly Stock Check form.
        Looks up the product.label by barcode, then updates the corresponding line.
        Returns a dict with either 'success' or 'error' key.
        """
        barcode = (barcode or '').strip()
        if not barcode:
            return {'error': _('Empty barcode received.')}
        check = self.browse(check_id)
        if not check.exists():
            return {'error': _('Stock Check record not found.')}
        if not check.branch_id:
            return {'error': _('Branch is required before scanning.')}
        if not check.location_ids:
            return {'error': _('At least one location is required before scanning.')}

        # 1. Try product.label barcode first
        label = self.env['product.label'].search([
            ('barcode', '=', barcode),
            ('branch_id', '=', check.branch_id.id),
            ('branch_location_id', 'in', check.location_ids.ids)
        ], limit=1)
        if label:
            already_scanned = check.line_ids.filtered(
                lambda l: l.label_id == label and (l.manual_qty > 0 or l.manual_weight > 0)
            )
            if already_scanned:
                return {'error': _('Barcode "%s" (Label: %s) has already been scanned.') % (barcode, label.name)}

            # Find existing line loaded by 'Load Products'
            existing_line = check.line_ids.filtered(lambda l: l.label_id == label)
            if existing_line:
                line = existing_line[0]
            else:
                # Create new line for label (Surplus)
                line = self.env['jewellery.weekly.stock.check.line'].create({
                    'stock_check_id': check.id,
                    'product_tmpl_id': label.product_id.product_tmpl_id.id,
                    'product_id': label.product_id.id,
                    'label_id': label.id,
                    'system_qty': 1.0,
                    'system_weight': label.sale_gross_weight,
                    'system_tag_weight':label.tag_weight,
                    'branch_id': label.branch_id.id,
                    'location_id': label.branch_location_id.id,
                })
            return {
                'success': True,
                'product': f"{label.display_name} (Matched)" if line.system_qty > 0 else f"{label.display_name} (Surplus)",
            }
        return {'error': _('No product or label found for barcode: %s') % barcode}


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

    is_vault_item = fields.Boolean(
        string='Vault Item',
        default=False
    )

    purity_id = fields.Many2one(
        'gold.purity',
        string='Purity',
        related='product_id.purity_id',
        store=True,
    )

    label_id = fields.Many2one(
        'product.label',
        string='Label',
        readonly=True
    )

    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        readonly=True
    )

    location_id = fields.Many2one(
        'stock.location',
        string='Location',
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
    # System tag weight (from label)
    system_tag_weight = fields.Float(
        string='System Tag Weight',
        digits=(16, 3),
        readonly=True
    )

    # Manual entered tag weight
    manual_tag_weight = fields.Float(
        string='Counted Tag Weight',
        digits=(16, 3),
        default=0.0
    )

    # Difference
    difference_tag_weight = fields.Float(
        string='Diff Tag Weight',
        digits=(16, 3),
        compute='_compute_difference',
        store=True
    )

    # Match flags
    is_tag_weight_matched = fields.Boolean(
        string='Tag Weight Matched',
        compute='_compute_is_matched',
        store=True
    )

    system_total_weight = fields.Float(
        string='System Total Wt',
        compute='_compute_total_weights',
        digits=(16, 3),
        store=True
    )

    manual_total_weight = fields.Float(
        string='Counted Total Wt',
        digits=(16, 3),
        default=0.0
    )
    difference_total_weight = fields.Float(
        string='Diff Total Wt',
        compute='_compute_total_weights',
        digits=(16, 3),
        store=True
    )
    is_total_weight_matched = fields.Boolean(
        string='Total Weight Matched',
        compute='_compute_is_matched',
        store=True
    )

    @api.onchange('label_id')
    def _onchange_label_id(self):
        for rec in self:
            if rec.label_id:
                rec.product_id = rec.label_id.product_id
                rec.product_tmpl_id = rec.label_id.product_id.product_tmpl_id
                rec.branch_id = rec.label_id.branch_id
                rec.location_id = rec.label_id.branch_location_id
                # Removed auto-calculation of manual weights and quantities

    @api.onchange('manual_total_weight')
    def _onchange_manual_total_weight(self):
        pass

    @api.onchange('manual_weight', 'manual_tag_weight')
    def _onchange_manual_weights(self):
        pass

    @api.depends('system_weight', 'manual_weight', 'system_tag_weight', 'manual_tag_weight')
    def _compute_total_weights(self):
        for rec in self:
            rec.system_total_weight = rec.system_weight + rec.system_tag_weight
            # rec.manual_total_weight = rec.manual_weight + rec.manual_tag_weight
            rec.difference_total_weight = rec.manual_total_weight - rec.system_total_weight

    @api.depends('system_qty', 'manual_qty', 'system_weight', 'manual_weight', 'system_tag_weight', 'manual_tag_weight')
    def _compute_difference(self):
        for rec in self:
            rec.difference_qty = rec.manual_qty - rec.system_qty
            rec.difference_weight = rec.manual_weight - rec.system_weight
            rec.difference_tag_weight = rec.manual_tag_weight - rec.system_tag_weight

    @api.depends('system_qty', 'manual_qty', 'system_weight', 'manual_weight', 'system_tag_weight', 'manual_tag_weight', 'manual_total_weight', 'system_total_weight')
    def _compute_is_matched(self):
        for rec in self:
            # Match if manual count equals system quantity
            qty_match = abs(rec.manual_qty - rec.system_qty) < 0.001
            # Allow 250mg (0.250g) tolerance for weight
            weight_match = abs(rec.manual_weight - rec.system_weight) <= 0.250
            # Tag weight tolerance, 50 mg tolerance (0.050g)
            tag_weight_match = abs(rec.manual_tag_weight - rec.system_tag_weight) <= 0.050
            
            # Total weight match (sum of weights)
            total_weight_match = abs(rec.manual_total_weight - rec.system_total_weight) <= 0.300

            rec.is_qty_matched = qty_match
            rec.is_weight_matched = weight_match
            rec.is_tag_weight_matched = tag_weight_match
            rec.is_total_weight_matched = total_weight_match

            # Overall match - based on qty and total weight
            rec.is_matched = qty_match and total_weight_match

    def _sync_summary(self):
        """Update the summary when line manual counts change."""
        if self.env.context.get('skip_line_sync'):
            return
        
        checks = self.mapped('stock_check_id')
        for check in checks:
            affected_tmpls = self.filtered(lambda l: l.stock_check_id == check).mapped('product_tmpl_id')
            if not affected_tmpls:
                continue
                
            summaries = check.template_summary_ids.filtered(lambda s: s.product_tmpl_id in affected_tmpls)
            
            # Auto-create missing summaries if they do not exist
            existing_tmpls = summaries.mapped('product_tmpl_id')
            missing_tmpls = affected_tmpls - existing_tmpls
            if missing_tmpls and check.id:
                new_summaries = self.env['jewellery.weekly.stock.check.template.summary'].create([
                    {'stock_check_id': check.id, 'product_tmpl_id': tmpl.id} for tmpl in missing_tmpls
                ])
                summaries |= new_summaries
                
            if not summaries:
                continue
                
            if not check.id:
                lines_by_tmpl = {}
                for line in check.line_ids:
                    if line.product_tmpl_id in affected_tmpls:
                        lines_by_tmpl.setdefault(line.product_tmpl_id, self.env['jewellery.weekly.stock.check.line'])
                        lines_by_tmpl[line.product_tmpl_id] |= line
                        
                for summary in summaries:
                    lines = lines_by_tmpl.get(summary.product_tmpl_id, self.env['jewellery.weekly.stock.check.line'])
                    summary.with_context(skip_summary_distribution=True).write({
                        'manual_qty': sum(lines.mapped('manual_qty')),
                        'manual_weight': sum(lines.mapped('manual_weight')),
                        'manual_tag_weight': sum(lines.mapped('manual_tag_weight')),
                        'manual_total_weight': sum(lines.mapped('manual_total_weight'))
                    })
                continue

            line_data = self.env['jewellery.weekly.stock.check.line'].read_group(
                [('stock_check_id', '=', check.id), ('product_tmpl_id', 'in', affected_tmpls.ids)],
                ['product_tmpl_id', 'manual_qty:sum', 'manual_weight:sum', 'manual_tag_weight:sum', 'manual_total_weight:sum'],
                ['product_tmpl_id']
            )
            line_dict = {d['product_tmpl_id'][0]: d for d in line_data}
            
            for summary in summaries:
                ld = line_dict.get(summary.product_tmpl_id.id, {})
                summary.with_context(skip_summary_distribution=True).write({
                    'manual_qty': ld.get('manual_qty', 0.0),
                    'manual_weight': ld.get('manual_weight', 0.0),
                    'manual_tag_weight': ld.get('manual_tag_weight', 0.0),
                    'manual_total_weight': ld.get('manual_total_weight', 0.0)
                })

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        res._sync_summary()
        return res

    def write(self, vals):
        res = super().write(vals)
        manual_fields = ['manual_qty', 'manual_weight', 'manual_tag_weight', 'manual_total_weight']
        if any(f in vals for f in manual_fields):
            self._sync_summary()
        return res


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
        compute='_compute_system_totals',
        store=True,
        digits=(16, 0)
    )
    system_weight = fields.Float(
        string='System Weight',
        compute='_compute_system_totals',
        store=True,
        digits=(16, 3)
    )

    manual_qty = fields.Float(
        string='Counted Labels',
        store=True,
        digits=(16, 0)
    )
    manual_weight = fields.Float(
        string='Counted Weight',
        store=True,
        digits=(16, 3)
    )

    difference_qty = fields.Float(
        string='Diff Labels',
        compute='_compute_differences',
        store=True,
        digits=(16, 0)
    )
    difference_weight = fields.Float(
        string='Diff Weight',
        compute='_compute_differences',
        store=True,
        digits=(16, 3)
    )

    is_qty_matched = fields.Boolean(
        string='Qty Matched',
        compute='_compute_differences',
        store=True
    )
    is_weight_matched = fields.Boolean(
        string='Weight Matched',
        compute='_compute_differences',
        store=True
    )
    is_matched = fields.Boolean(
        string='Matched',
        compute='_compute_differences',
        store=True
    )
    system_tag_weight = fields.Float(
        string='System Tag Weight',
        compute='_compute_system_totals',
        store=True,
        digits=(16, 3)
    )

    manual_tag_weight = fields.Float(
        string='Counted Tag Weight',
        store=True,
        digits=(16, 3)
    )

    difference_tag_weight = fields.Float(
        string='Diff Tag Weight',
        compute='_compute_differences',
        store=True,
        digits=(16, 3)
    )

    is_tag_weight_matched = fields.Boolean(
        string='Tag Weight Matched',
        compute='_compute_differences',
        store=True
    )

    system_total_weight = fields.Float(
        string='System Total Wt',
        compute='_compute_system_totals',
        digits=(16, 3),
        store=True
    )

    manual_total_weight = fields.Float(
        string='Counted Total Wt',
        digits=(16, 3),
        store=True
    )
    difference_total_weight = fields.Float(
        string='Diff Total Wt',
        compute='_compute_differences',
        digits=(16, 3),
        store=True
    )
    is_total_weight_matched = fields.Boolean(
        string='Total Weight Matched',
        compute='_compute_differences',
        store=True
    )

    @api.depends('stock_check_id.line_ids.system_qty', 'stock_check_id.line_ids.system_weight', 'stock_check_id.line_ids.system_tag_weight', 'stock_check_id.line_ids.system_total_weight')
    def _compute_system_totals(self):
        for check in self.mapped('stock_check_id'):
            summaries = self.filtered(lambda s: s.stock_check_id == check)
            
            if not check.id:
                lines_by_tmpl = {}
                for line in check.line_ids:
                    lines_by_tmpl.setdefault(line.product_tmpl_id, []).append(line)
                for summary in summaries:
                    lines = lines_by_tmpl.get(summary.product_tmpl_id, [])
                    summary.system_qty = sum(l.system_qty for l in lines)
                    summary.system_weight = sum(l.system_weight for l in lines)
                    summary.system_tag_weight = sum(l.system_tag_weight for l in lines)
                    summary.system_total_weight = sum(l.system_total_weight for l in lines)
                continue
                
            tmpl_ids = summaries.mapped('product_tmpl_id').ids
            line_data = self.env['jewellery.weekly.stock.check.line'].read_group(
                [('stock_check_id', '=', check.id), ('product_tmpl_id', 'in', tmpl_ids)],
                ['product_tmpl_id', 'system_qty:sum', 'system_weight:sum', 'system_tag_weight:sum', 'system_total_weight:sum'],
                ['product_tmpl_id']
            )
            
            line_dict = {d['product_tmpl_id'][0]: d for d in line_data}
            
            for summary in summaries:
                ld = line_dict.get(summary.product_tmpl_id.id, {})
                summary.system_qty = ld.get('system_qty', 0.0)
                summary.system_weight = ld.get('system_weight', 0.0)
                summary.system_tag_weight = ld.get('system_tag_weight', 0.0)
                summary.system_total_weight = ld.get('system_total_weight', 0.0)


    def write(self, vals):
        res = super().write(vals)
        # Removed auto-distribution of manual quantities and weights to lines
        return res



    @api.depends('manual_qty', 'manual_weight', 'manual_tag_weight', 'system_qty', 'system_weight', 'system_tag_weight', 'manual_total_weight', 'system_total_weight')
    def _compute_differences(self):
        for summary in self:
            summary.difference_qty = summary.manual_qty - summary.system_qty
            summary.difference_weight = summary.manual_weight - summary.system_weight
            summary.difference_tag_weight = summary.manual_tag_weight - summary.system_tag_weight
            summary.difference_total_weight = summary.manual_total_weight - summary.system_total_weight


            qty_match = abs(summary.manual_qty - summary.system_qty) < 0.001
            weight_match = abs(summary.manual_weight - summary.system_weight) <= 0.250
            tag_match = abs(summary.manual_tag_weight - summary.system_tag_weight) <= 0.050 

            summary.is_qty_matched = qty_match
            summary.is_weight_matched = weight_match
            summary.is_tag_weight_matched = tag_match
            summary.is_total_weight_matched = abs(summary.manual_total_weight - summary.system_total_weight) <= 0.300
            
            summary.is_matched = qty_match and summary.is_total_weight_matched

