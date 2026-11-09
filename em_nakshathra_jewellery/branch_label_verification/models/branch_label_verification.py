# -*- coding: utf-8 -*-
import base64
import logging
from io import BytesIO
from dateutil.relativedelta import relativedelta
import xlsxwriter

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class BranchLabelVerification(models.Model):
    _name = 'branch.label.verification'
    _description = 'Branch Label Verification & Stock Audit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    def _get_default_branch(self):
        return self.env.user.branch_id.id if hasattr(self.env.user, 'branch_id') and self.env.user.branch_id else False

    name = fields.Char(
        string='Audit Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        tracking=True,
    )
    date = fields.Date(
        string='Verification Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Auditor / Verifier',
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    branch_id = fields.Many2one(
        'res.branch',
        string='Default Branch',
        default=_get_default_branch,
        required=True,
        tracking=True,
        help="Branch whose labels are being audited. Defaults to the current user's default branch.",
    )
    location_ids = fields.Many2many(
        'stock.location',
        'branch_label_verification_loc_rel',
        'verification_id',
        'location_id',
        string='Target Locations',
        domain="[('branch_id', '=', branch_id), ('usage', '=', 'internal')]",
        help="Optional: Restrict to specific counter(s) or vault/safe locations in this branch. Leave empty to audit all internal locations.",
    )
    label_filter = fields.Selection([
        ('active', 'Active Labels Only (In Stock)'),
        ('inactive', 'Inactive / Sold Labels Only'),
        ('all', 'All Labels (Active & Inactive)'),
    ], string='Label Filter', default='active', required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'Verifying'),
        ('done', 'Completed'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    scan_barcode = fields.Char(
        string='Scan Barcode / Label Ref',
        help='Scan barcode using scanner gun or type barcode / reference and hit Enter.',
    )
    last_scanned_message = fields.Char(
        string='Last Scan Feedback',
        readonly=True,
    )
    last_scanned_status = fields.Selection([
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('danger', 'Danger'),
        ('info', 'Info'),
    ], readonly=True)

    line_ids = fields.One2many(
        'branch.label.verification.line',
        'verification_id',
        string='Verification Lines',
    )
    template_summary_ids = fields.One2many(
        'branch.label.verification.template.summary',
        'verification_id',
        string='Product Template Summary',
    )

    # -------------------------------------------------------------
    # KPI / Summary Computed Fields
    # -------------------------------------------------------------
    total_expected_count = fields.Integer(
        string='Total Expected',
        compute='_compute_kpi_summary',
        store=True,
    )
    total_expected_gross_weight = fields.Float(
        string='Expected Gross Wt (g)',
        compute='_compute_kpi_summary',
        digits=(16, 3),
        store=True,
    )
    total_expected_net_weight = fields.Float(
        string='Expected Net Wt (g)',
        compute='_compute_kpi_summary',
        digits=(16, 3),
        store=True,
    )

    verified_count = fields.Integer(
        string='Verified Count',
        compute='_compute_kpi_summary',
        store=True,
    )
    verified_gross_weight = fields.Float(
        string='Verified Gross Wt (g)',
        compute='_compute_kpi_summary',
        digits=(16, 3),
        store=True,
    )
    verified_net_weight = fields.Float(
        string='Verified Net Wt (g)',
        compute='_compute_kpi_summary',
        digits=(16, 3),
        store=True,
    )

    pending_count = fields.Integer(
        string='Pending Count',
        compute='_compute_kpi_summary',
        store=True,
    )
    pending_gross_weight = fields.Float(
        string='Pending Gross Wt (g)',
        compute='_compute_kpi_summary',
        digits=(16, 3),
        store=True,
    )

    missing_count = fields.Integer(
        string='Missing Count',
        compute='_compute_kpi_summary',
        store=True,
    )
    missing_gross_weight = fields.Float(
        string='Missing Gross Wt (g)',
        compute='_compute_kpi_summary',
        digits=(16, 3),
        store=True,
    )

    extra_count = fields.Integer(
        string='Extra / Mismatch Count',
        compute='_compute_kpi_summary',
        store=True,
    )
    extra_gross_weight = fields.Float(
        string='Extra Gross Wt (g)',
        compute='_compute_kpi_summary',
        digits=(16, 3),
        store=True,
    )

    progress_rate = fields.Float(
        string='Verification Progress %',
        compute='_compute_kpi_summary',
        digits=(16, 1),
        store=True,
    )

    matched_templates_count = fields.Integer(
        string='Matched Templates',
        compute='_compute_template_counts',
        store=True,
    )
    mismatched_templates_count = fields.Integer(
        string='Mismatched Templates',
        compute='_compute_template_counts',
        store=True,
    )

    notes = fields.Text(string='Audit Observations & Remarks')

    @api.depends(
        'line_ids',
        'line_ids.status',
        'line_ids.sale_gross_weight',
        'line_ids.sale_net_weight',
        'line_ids.is_vault_item',
        'line_ids.is_old_gold',
        'line_ids.is_diamond_og',
    )
    def _compute_kpi_summary(self):
        for rec in self:
            expected_lines = rec.line_ids.filtered(lambda l: l.status != 'extra' and not l.is_vault_item and not l.is_old_gold and not l.is_diamond_og)
            verified_lines = rec.line_ids.filtered(lambda l: l.status == 'verified' and not l.is_vault_item and not l.is_old_gold and not l.is_diamond_og)
            pending_lines = rec.line_ids.filtered(lambda l: l.status == 'pending' and not l.is_vault_item and not l.is_old_gold and not l.is_diamond_og)
            missing_lines = rec.line_ids.filtered(lambda l: l.status == 'missing' and not l.is_vault_item and not l.is_old_gold and not l.is_diamond_og)
            extra_lines = rec.line_ids.filtered(lambda l: l.status == 'extra' and not l.is_vault_item and not l.is_old_gold and not l.is_diamond_og)

            exp_cnt = len(expected_lines)
            ver_cnt = len(verified_lines)

            rec.total_expected_count = exp_cnt
            rec.total_expected_gross_weight = sum(expected_lines.mapped('sale_gross_weight'))
            rec.total_expected_net_weight = sum(expected_lines.mapped('sale_net_weight'))

            rec.verified_count = ver_cnt
            rec.verified_gross_weight = sum(verified_lines.mapped('sale_gross_weight'))
            rec.verified_net_weight = sum(verified_lines.mapped('sale_net_weight'))

            rec.pending_count = len(pending_lines)
            rec.pending_gross_weight = sum(pending_lines.mapped('sale_gross_weight'))

            rec.missing_count = len(missing_lines)
            rec.missing_gross_weight = sum(missing_lines.mapped('sale_gross_weight'))

            rec.extra_count = len(extra_lines)
            rec.extra_gross_weight = sum(extra_lines.mapped('sale_gross_weight'))

            rec.progress_rate = round((ver_cnt / exp_cnt * 100.0), 1) if exp_cnt > 0 else 0.0

    @api.depends('template_summary_ids.is_matched')
    def _compute_template_counts(self):
        for rec in self:
            rec.matched_templates_count = len(rec.template_summary_ids.filtered('is_matched'))
            rec.mismatched_templates_count = len(rec.template_summary_ids.filtered(lambda s: not s.is_matched))

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            seq = self.env['ir.sequence'].next_by_code('branch.label.verification')
            vals['name'] = seq or _('New')
        return super().create(vals)

    @api.onchange('branch_id')
    def _onchange_branch_id(self):
        if self.branch_id:
            self.location_ids = [(5, 0, 0)]

    # -------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------
    def action_load_branch_labels(self):
        """Fetch all labels in the default branch and create verification lines."""
        self.ensure_one()
        if not self.branch_id:
            raise UserError(_("Please select a Branch first."))

        # Delete existing lines
        self.line_ids.unlink()

        # Determine internal locations in target branch
        if self.location_ids:
            target_locations = self.location_ids
        else:
            target_locations = self.env['stock.location'].search([
                ('branch_id', '=', self.branch_id.id),
                ('usage', '=', 'internal')
            ])

        domain = [('branch_id', '=', self.branch_id.id)]
        if self.location_ids:
            domain.append(('branch_location_id', 'in', self.location_ids.ids))

        if self.label_filter == 'active':
            domain.append(('active', '=', True))
        elif self.label_filter == 'inactive':
            domain.append(('active', '=', False))

        labels = self.env['product.label'].search(domain, order='product_tmpl_id asc, name asc')

        # Check for bulk stock quants (vault items, old gold, diamond og) in target locations
        bulk_quants = self.env['stock.quant'].search([
            ('location_id', 'in', target_locations.ids),
            ('quantity', '>', 0),
            '|', '|',
            ('product_id.product_tmpl_id.is_vault_item', '=', True),
            ('product_id.product_tmpl_id.is_old_gold', '=', True),
            ('product_id.product_tmpl_id.is_diamond_og', '=', True),
        ])

        if not labels and not bulk_quants:
            raise UserError(_("No labels or bulk stock found for branch '%s' matching the selected criteria.") % self.branch_id.name)

        lines_vals = []
        for lbl in labels:
            tmpl = lbl.product_tmpl_id or (lbl.product_id.product_tmpl_id if lbl.product_id else False)
            purity = lbl.purity_id or lbl.sale_purity_id
            lines_vals.append({
                'verification_id': self.id,
                'label_id': lbl.id,
                'product_id': lbl.product_id.id,
                'product_tmpl_id': tmpl.id if tmpl else False,
                'categ_id': lbl.product_id.categ_id.id if lbl.product_id and lbl.product_id.categ_id else False,
                'purity_id': purity.id if purity else False,
                'branch_id': lbl.branch_id.id,
                'location_id': lbl.branch_location_id.id if lbl.branch_location_id else False,
                'sale_gross_weight': lbl.sale_gross_weight or 0.0,
                'sale_net_weight': lbl.sale_net_weight or 0.0,
                'tag_weight': lbl.tag_weight or 0.0,
                'system_qty': 1.0,
                'system_weight': lbl.sale_gross_weight or 0.0,
                'system_tag_weight': lbl.tag_weight or 0.0,
                'system_total_weight': (lbl.sale_gross_weight or 0.0) + (lbl.tag_weight or 0.0),
                'manual_qty': 0.0,
                'manual_weight': 0.0,
                'manual_tag_weight': 0.0,
                'manual_total_weight': 0.0,
                'active': lbl.active,
                'status': 'pending',
                'is_verified': False,
            })

        self.env['branch.label.verification.line'].create(lines_vals)
        self._sync_template_summaries()
        self.write({
            'state': 'in_progress',
            'last_scanned_message': _("Loaded %d labels for branch '%s'. Ready for verification.") % (len(lines_vals), self.branch_id.name),
            'last_scanned_status': 'success',
        })
        return True

    @api.onchange('scan_barcode')
    def _onchange_scan_barcode(self):
        if self.scan_barcode and self.state == 'in_progress':
            self.action_scan_barcode()

    @api.model
    def action_scan_barcode(self, check_id=False, barcode=False):
        """
        Process scanned barcode or reference:
        - Automatically called when barcode scanner fires Enter / Tab
        - Works both from RPC call (check_id, barcode) and form button call (self).
        - Matches against loaded expected lines
        - Flags duplicates
        - Detects foreign branch or unexpected labels
        - Updates line and database record immediately
        - Returns structured result dict for JS auto-scanner and notifications
        """
        if not check_id and self:
            check = self[0]
            raw_code = (check.scan_barcode or '').strip()
            is_rpc = False
        else:
            check = self.browse(check_id) if check_id else self
            raw_code = (barcode or '').strip()
            is_rpc = True

        if not check.exists():
            return {'error': _("Verification session not found."), 'status': 'error'}

        if not raw_code:
            return {'error': _("Empty barcode received."), 'status': 'error'}

        # Clear barcode input for next scan
        vals_to_write = {'scan_barcode': False}

        # 1. Search in current verification lines
        matching_lines = check.line_ids.filtered(
            lambda l: (l.label_id.barcode and l.label_id.barcode.strip() == raw_code)
                   or (l.label_id.barcode2 and l.label_id.barcode2.strip() == raw_code)
                   or (l.label_id.name and l.label_id.name.strip().upper() == raw_code.upper())
                   or (l.label_id.label_number and l.label_id.label_number.strip().upper() == raw_code.upper())
        )

        if matching_lines:
            line = matching_lines[0]
            if line.status == 'verified':
                time_str = fields.Datetime.to_string(line.verified_datetime) if line.verified_datetime else ''
                user_name = line.verified_by.name if line.verified_by else _('User')
                msg = _("⚠️ Already Verified: '%s' (%s) was verified at %s by %s.") % (
                    line.label_id.name or '',
                    line.product_id.display_name or '',
                    time_str,
                    user_name
                )
                vals_to_write.update({
                    'last_scanned_message': msg,
                    'last_scanned_status': 'warning',
                })
                check.write(vals_to_write)
                if is_rpc:
                    return {
                        'status': 'warning',
                        'warning': True,
                        'product': line.label_id.name or '',
                        'message': msg,
                    }
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Already Verified!'),
                        'message': msg,
                        'sticky': False,
                        'type': 'warning',
                    }
                }
            else:
                line.write({
                    'status': 'verified',
                    'is_verified': True,
                    'verified_datetime': fields.Datetime.now(),
                    'verified_by': self.env.user.id,
                    'manual_qty': 1.0,
                    'manual_weight': line.sale_gross_weight or 0.0,
                    'manual_tag_weight': line.tag_weight or 0.0,
                    'manual_total_weight': (line.sale_gross_weight or 0.0) + (line.tag_weight or 0.0),
                })
                prod_title = f"{line.label_id.name or ''} | {line.product_id.display_name or ''} ({line.sale_gross_weight or 0.0:.3f} g)"
                msg = _("✅ Verified: '%s' | %s | Gross: %.3f g") % (
                    line.label_id.name or '',
                    line.product_id.display_name or '',
                    line.sale_gross_weight or 0.0
                )
                vals_to_write.update({
                    'last_scanned_message': msg,
                    'last_scanned_status': 'success',
                })
                check.write(vals_to_write)
                if is_rpc:
                    return {
                        'status': 'verified',
                        'success': True,
                        'product': prod_title,
                        'message': msg,
                        'label_ref': line.label_id.name or '',
                        'gross_weight': line.sale_gross_weight or 0.0,
                    }
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Label Verified!'),
                        'message': msg,
                        'sticky': False,
                        'type': 'success',
                    }
                }

        # 2. Not in loaded lines - check if it exists in the system
        external_label = self.env['product.label'].search([
            '|', '|', '|',
            ('barcode', '=', raw_code),
            ('barcode2', '=', raw_code),
            ('name', '=ilike', raw_code),
            ('label_number', '=ilike', raw_code),
        ], limit=1)

        if external_label:
            tmpl = external_label.product_tmpl_id or (external_label.product_id.product_tmpl_id if external_label.product_id else False)
            purity = external_label.purity_id or external_label.sale_purity_id
            other_branch = external_label.branch_id.name if external_label.branch_id else _('No Branch')

            is_wrong_branch = external_label.branch_id != check.branch_id
            note = _("Foreign Branch: Assigned to '%s'") % other_branch if is_wrong_branch else _("Extra: Label was not in initial load list")
            if not external_label.active:
                note += _(" (Inactive / Sold in system)")

            self.env['branch.label.verification.line'].create({
                'verification_id': check.id,
                'label_id': external_label.id,
                'product_id': external_label.product_id.id,
                'product_tmpl_id': tmpl.id if tmpl else False,
                'categ_id': external_label.product_id.categ_id.id if external_label.product_id and external_label.product_id.categ_id else False,
                'purity_id': purity.id if purity else False,
                'branch_id': external_label.branch_id.id,
                'location_id': external_label.branch_location_id.id if external_label.branch_location_id else False,
                'sale_gross_weight': external_label.sale_gross_weight or 0.0,
                'sale_net_weight': external_label.sale_net_weight or 0.0,
                'tag_weight': external_label.tag_weight or 0.0,
                'active': external_label.active,
                'status': 'extra',
                'is_verified': True,
                'verified_datetime': fields.Datetime.now(),
                'verified_by': self.env.user.id,
                'notes': note,
            })
            check._sync_template_summaries()

            msg = _("🚨 Mismatch / Extra: '%s' belongs to '%s'! Added to Extra / Mismatch list.") % (
                external_label.name,
                other_branch
            )
            vals_to_write.update({
                'last_scanned_message': msg,
                'last_scanned_status': 'warning',
            })
            check.write(vals_to_write)
            if is_rpc:
                return {
                    'status': 'extra',
                    'success': True,
                    'warning': True,
                    'product': f"{external_label.name} (Extra - {other_branch})",
                    'message': msg,
                }
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Branch Mismatch / Extra Item!'),
                    'message': msg,
                    'sticky': True,
                    'type': 'warning',
                }
            }

        # 3. Label not found in database at all
        msg = _("❌ Not Found: No label in system matches barcode/code '%s'.") % raw_code
        vals_to_write.update({
            'last_scanned_message': msg,
            'last_scanned_status': 'danger',
        })
        check.write(vals_to_write)
        if is_rpc:
            return {
                'status': 'error',
                'error': msg,
                'message': msg,
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Unknown Label / Barcode'),
                'message': msg,
                'sticky': False,
                'type': 'danger',
            }
        }

    def action_mark_remaining_missing(self):
        """Mark all remaining pending labels as Missing."""
        self.ensure_one()
        pending = self.line_ids.filtered(lambda l: l.status == 'pending')
        if not pending:
            raise UserError(_("There are no pending labels to mark as missing."))
        pending.write({'status': 'missing'})
        self.write({
            'last_scanned_message': _("Marked %d pending labels as Missing.") % len(pending),
            'last_scanned_status': 'warning',
        })
        return True

    def action_complete(self):
        """Finalize verification audit and record timestamps on product labels."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Cannot complete an empty verification audit."))

        # If there are pending labels, warn or let user decide
        pending_cnt = self.pending_count
        if pending_cnt > 0:
            # Auto-mark remaining as missing
            self.action_mark_remaining_missing()

        self.state = 'done'
        self._sync_template_summaries()
        self.write({
            'last_scanned_message': _("Verification completed successfully on %s. Verified: %d, Missing: %d, Extra: %d.") % (
                fields.Date.today(),
                self.verified_count,
                self.missing_count,
                self.extra_count,
            ),
            'last_scanned_status': 'success',
        })
        return True

    def action_reset(self):
        """Reset verification lines back to pending."""
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_("Completed audits cannot be reset. Create a new audit instead."))
        self.line_ids.filtered(lambda l: l.status != 'extra').write({
            'status': 'pending',
            'is_verified': False,
            'verified_datetime': False,
            'verified_by': False,
        })
        # Remove extra lines scanned during session
        self.line_ids.filtered(lambda l: l.status == 'extra').unlink()
        self._sync_template_summaries()
        self.state = 'in_progress'
        self.write({
            'last_scanned_message': _("Verification counts have been reset."),
            'last_scanned_status': 'warning',
        })
        return True

    def action_cancel(self):
        self.ensure_one()
        self.state = 'cancel'
        return True

    def action_draft(self):
        self.ensure_one()
        self.write({
            'state': 'draft',
            'last_scanned_message': _("Audit reset to Draft."),
            'last_scanned_status': 'warning',
        })
        return True

    def action_start_verification(self):
        """Move from draft to in_progress to resume or start scanning."""
        self.ensure_one()
        if not self.line_ids:
            return self.action_load_branch_labels()
        self.write({
            'state': 'in_progress',
            'last_scanned_message': _("Verification in progress."),
            'last_scanned_status': 'success',
        })
        return True

    def action_export_excel(self):
        """Generate styled Excel report summarizing the branch label audit."""
        self.ensure_one()
        is_manager = self.env.user.has_group('branch_label_verification.group_branch_label_verification_branch_manager') or self.env.is_superuser()
        rtype = 'manager' if is_manager else 'billing'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/branch_label_verification/export_xlsx?id={self.id}&report_type={rtype}',
            'target': 'new',
        }

    def _sync_template_summaries(self):
        """Ensure all product templates represented in lines and bulk items (vault, old gold, diamond og)
        have summary records, and sync manual_qty with the count of verified lines."""
        for rec in self:
            templates_in_lines = rec.line_ids.mapped('product_tmpl_id').filtered(lambda t: bool(t))

            # Target locations for bulk items (Vault, Old Gold, Diamond OG)
            if rec.location_ids:
                bulk_locs = rec.location_ids
            else:
                bulk_locs = self.env['stock.location'].search([
                    ('branch_id', '=', rec.branch_id.id),
                    ('usage', '=', 'internal')
                ])

            bulk_quants = self.env['stock.quant'].search([
                ('location_id', 'in', bulk_locs.ids),
                ('quantity', '>', 0),
                '|', '|',
                ('product_id.product_tmpl_id.is_vault_item', '=', True),
                ('product_id.product_tmpl_id.is_old_gold', '=', True),
                ('product_id.product_tmpl_id.is_diamond_og', '=', True),
            ])
            bulk_tmpls = bulk_quants.mapped('product_id.product_tmpl_id')
            all_tmpls = templates_in_lines | bulk_tmpls

            # Remove summaries for templates that are no longer in lines or bulk quants
            obsolete = rec.template_summary_ids.filtered(lambda s: s.product_tmpl_id not in all_tmpls)
            if obsolete:
                obsolete.sudo().unlink()

            existing_tmpls = rec.template_summary_ids.mapped('product_tmpl_id')
            missing_tmpls = all_tmpls - existing_tmpls
            if missing_tmpls:
                self.env['branch.label.verification.template.summary'].create([
                    {
                        'verification_id': rec.id,
                        'product_tmpl_id': tmpl.id,
                    }
                    for tmpl in missing_tmpls
                ])

            # Sync manual_qty, manual_weight, manual_tag_weight, manual_total_weight with count of verified lines
            lines_by_tmpl = {}
            for line in rec.line_ids:
                if line.product_tmpl_id:
                    lines_by_tmpl.setdefault(line.product_tmpl_id.id, []).append(line)

            for summary in rec.template_summary_ids:
                if summary.is_vault_item or summary.is_old_gold or summary.is_diamond_og:
                    # For bulk items (Vault, Old Gold, Diamond OG), manual weights are entered directly by the user; keep them intact
                    continue
                lines = lines_by_tmpl.get(summary.product_tmpl_id.id, [])
                verified_lines = [l for l in lines if l.status == 'verified']
                verified_count = float(len(verified_lines))
                verified_gross = sum(l.sale_gross_weight or 0.0 for l in verified_lines)
                verified_tag = sum(l.tag_weight or 0.0 for l in verified_lines)
                verified_total = verified_gross + verified_tag

                vals = {}
                if summary.manual_qty != verified_count:
                    vals['manual_qty'] = verified_count
                if abs(summary.manual_weight - verified_gross) > 0.0001:
                    vals['manual_weight'] = verified_gross
                if abs(summary.manual_tag_weight - verified_tag) > 0.0001:
                    vals['manual_tag_weight'] = verified_tag
                if abs(summary.manual_total_weight - verified_total) > 0.0001:
                    vals['manual_total_weight'] = verified_total
                if vals:
                    summary.write(vals)

    def action_refresh_template_summary(self):
        """Refresh / re-sync template summary records."""
        self.ensure_one()
        self._sync_template_summaries()
        matched = len(self.template_summary_ids.filtered('is_matched'))
        mismatched = len(self.template_summary_ids) - matched
        self.write({
            'matched_templates_count': matched,
            'mismatched_templates_count': mismatched,
        })
        return True

    def action_check_match(self):
        """Validate template counts against system quantities and weights."""
        self.ensure_one()
        if not self.template_summary_ids:
            raise UserError(_("No product templates loaded. Please load labels first."))

        matched_count = len(self.template_summary_ids.filtered('is_matched'))
        total_count = len(self.template_summary_ids)
        mismatched_count = total_count - matched_count

        if mismatched_count == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('All Templates Matched!'),
                    'message': _('All %d product templates matched within tolerance.') % total_count,
                    'sticky': False,
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Mismatched Templates Found'),
                    'message': _('%d out of %d product templates are matched. %d have differences.') % (
                        matched_count, total_count, mismatched_count
                    ),
                    'sticky': True,
                    'type': 'warning',
                }
            }

    def action_autofill_weights(self):
        """Auto-populate manual weights from verified lines."""
        for rec in self:
            lines_by_tmpl = {}
            for line in rec.line_ids:
                if line.product_tmpl_id:
                    lines_by_tmpl.setdefault(line.product_tmpl_id.id, []).append(line)
            for summary in rec.template_summary_ids:
                lines = lines_by_tmpl.get(summary.product_tmpl_id.id, [])
                verified_lines = [l for l in lines if l.status == 'verified']
                gross_wt = sum(l.sale_gross_weight or 0.0 for l in verified_lines)
                tag_wt = sum(l.tag_weight or 0.0 for l in verified_lines)
                summary.write({
                    'manual_qty': float(len(verified_lines)),
                    'manual_weight': gross_wt,
                    'manual_tag_weight': tag_wt,
                    'manual_total_weight': gross_wt + tag_wt,
                })
        return True

    def action_reset_counted_weights(self):
        """Reset manual weights to 0.0 while preserving verified label counts."""
        for rec in self:
            rec.template_summary_ids.write({
                'manual_weight': 0.0,
                'manual_tag_weight': 0.0,
                'manual_total_weight': 0.0,
            })
        return True

    def web_read(self, specification):
        for rec in self:
            if rec.line_ids and not rec.template_summary_ids:
                try:
                    rec._sync_template_summaries()
                except Exception:
                    pass
        return super().web_read(specification)

    # -------------------------------------------------------------
    # Automatic Purge / Cleanup Cron
    # -------------------------------------------------------------
    @api.model
    def cron_cleanup_old_verifications(self, retention_months=2):
        """Automatically delete all audit records older than retention_months (default 2 months),
        regardless of status (including Draft, Verifying, Completed, and Cancelled)."""
        cutoff_date = fields.Date.today() - relativedelta(months=retention_months)
        _logger.info(
            "Branch Label Verification: Starting automatic purge of audits older than %s (retention: %d months)...",
            cutoff_date, retention_months
        )

        domain = [
            '|',
            ('date', '<', cutoff_date),
            '&', ('date', '=', False), ('create_date', '<', fields.Datetime.to_datetime(cutoff_date))
        ]

        total_purged = 0
        while True:
            old_audits = self.search(domain, limit=50)
            if not old_audits:
                break
            count = len(old_audits)
            total_purged += count
            old_audits.unlink()
            self.env.cr.commit()

        _logger.info(
            "Branch Label Verification: Finished automatic purge. Deleted %d audit records older than %s.",
            total_purged, cutoff_date
        )
        return True


class BranchLabelVerificationLine(models.Model):
    _name = 'branch.label.verification.line'
    _description = 'Branch Label Verification Line'
    _order = 'status desc, sale_gross_weight desc, id desc'

    verification_id = fields.Many2one(
        'branch.label.verification',
        string='Verification Session',
        required=True,
        ondelete='cascade',
        index=True,
    )
    label_id = fields.Many2one(
        'product.label',
        string='Product Label',
        index=True,
        ondelete='set null',
    )
    name = fields.Char(
        string='Label Reference',
        compute='_compute_line_name',
        store=True,
        readonly=True,
    )
    barcode = fields.Char(
        string='Barcode',
        related='label_id.barcode',
        store=True,
        readonly=True,
    )
    barcode2 = fields.Char(
        string='Second Barcode',
        related='label_id.barcode2',
        store=True,
        readonly=True,
    )
    is_vault_item = fields.Boolean(
        string='Vault Item',
        related='product_tmpl_id.is_vault_item',
        store=True,
        readonly=True,
    )
    is_old_gold = fields.Boolean(
        string='Old Gold',
        related='product_tmpl_id.is_old_gold',
        store=True,
        readonly=True,
    )
    is_diamond_og = fields.Boolean(
        string='Diamond OG',
        related='product_tmpl_id.is_diamond_og',
        store=True,
        readonly=True,
    )

    @api.depends('label_id.name', 'product_id.display_name', 'product_tmpl_id.is_vault_item')
    def _compute_line_name(self):
        for rec in self:
            if rec.label_id:
                rec.name = rec.label_id.name
            elif rec.product_tmpl_id and rec.product_tmpl_id.is_vault_item:
                rec.name = f"{rec.product_id.display_name or rec.product_tmpl_id.name} (Vault Stock)"
            else:
                rec.name = rec.product_id.display_name or _("Unlabelled Stock")
    product_id = fields.Many2one(
        'product.product',
        string='Variant',
        readonly=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        readonly=True,
    )
    categ_id = fields.Many2one(
        'product.category',
        string='Category',
        readonly=True,
    )
    purity_id = fields.Many2one(
        'gold.purity',
        string='Purity',
        readonly=True,
    )
    branch_id = fields.Many2one(
        'res.branch',
        string='Current Branch',
        readonly=True,
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        readonly=True,
    )
    sale_gross_weight = fields.Float(
        string='Gross Wt (g)',
        digits=(16, 3),
        readonly=True,
    )
    sale_net_weight = fields.Float(
        string='Net Wt (g)',
        digits=(16, 3),
        readonly=True,
    )
    tag_weight = fields.Float(
        string='Tag Wt (g)',
        digits=(16, 3),
        readonly=True,
    )
    active = fields.Boolean(
        string='In Stock',
        readonly=True,
    )
    status = fields.Selection([
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('missing', 'Missing'),
        ('extra', 'Extra / Mismatch'),
    ], string='Verification Status', default='pending', required=True, index=True)

    is_verified = fields.Boolean(
        string='Verified?',
        default=False,
    )
    verified_datetime = fields.Datetime(
        string='Verified At',
        readonly=True,
    )
    verified_by = fields.Many2one(
        'res.users',
        string='Verified By',
        readonly=True,
    )
    notes = fields.Char(
        string='Remarks',
    )

    # System values (Expected)
    system_qty = fields.Float(
        string='System Label Count',
        digits=(16, 0),
        default=1.0,
        readonly=True,
    )
    system_weight = fields.Float(
        string='System Weight',
        digits=(16, 3),
        readonly=True,
    )
    system_tag_weight = fields.Float(
        string='System Tag Weight',
        digits=(16, 3),
        readonly=True,
    )
    system_total_weight = fields.Float(
        string='System Total Wt',
        digits=(16, 3),
        readonly=True,
    )

    # Counted / Manual values
    manual_qty = fields.Float(
        string='Counted Labels',
        digits=(16, 0),
        default=0.0,
    )
    manual_weight = fields.Float(
        string='Counted Weight',
        digits=(16, 3),
        default=0.0,
    )
    manual_tag_weight = fields.Float(
        string='Counted Tag Weight',
        digits=(16, 3),
        default=0.0,
    )
    manual_total_weight = fields.Float(
        string='Counted Total Wt',
        digits=(16, 3),
        default=0.0,
    )

    # Differences
    difference_qty = fields.Float(
        string='Diff Label',
        digits=(16, 0),
        compute='_compute_line_differences',
        store=True,
    )
    difference_weight = fields.Float(
        string='Diff Weight',
        digits=(16, 3),
        compute='_compute_line_differences',
        store=True,
    )
    difference_tag_weight = fields.Float(
        string='Diff Tag Weight',
        digits=(16, 3),
        compute='_compute_line_differences',
        store=True,
    )
    difference_total_weight = fields.Float(
        string='Diff Total Wt',
        compute='_compute_line_differences',
        digits=(16, 3),
        store=True,
    )

    # Boolean match flags with toggle switch widgets
    is_qty_matched = fields.Boolean(
        string='Qty Matched',
        compute='_compute_line_differences',
        store=True,
    )
    is_weight_matched = fields.Boolean(
        string='Weight Matched',
        compute='_compute_line_differences',
        store=True,
    )
    is_tag_weight_matched = fields.Boolean(
        string='Tag Weight Matched',
        compute='_compute_line_differences',
        store=True,
    )
    is_total_weight_matched = fields.Boolean(
        string='Total Weight Matched',
        compute='_compute_line_differences',
        store=True,
    )
    is_matched = fields.Boolean(
        string='Matched',
        compute='_compute_line_differences',
        store=True,
    )

    @api.depends(
        'system_qty', 'manual_qty',
        'system_weight', 'manual_weight',
        'system_tag_weight', 'manual_tag_weight',
        'system_total_weight', 'manual_total_weight',
        'sale_gross_weight', 'tag_weight', 'status'
    )
    def _compute_line_differences(self):
        for rec in self:
            if not rec.system_weight and rec.sale_gross_weight:
                rec.system_weight = rec.sale_gross_weight or 0.0
                rec.system_tag_weight = rec.tag_weight or 0.0
                rec.system_total_weight = (rec.sale_gross_weight or 0.0) + (rec.tag_weight or 0.0)
                if not rec.system_qty and rec.status != 'extra':
                    rec.system_qty = 1.0

            rec.difference_qty = rec.manual_qty - rec.system_qty
            rec.difference_weight = rec.manual_weight - rec.system_weight
            rec.difference_tag_weight = rec.manual_tag_weight - rec.system_tag_weight
            rec.difference_total_weight = rec.manual_total_weight - rec.system_total_weight

            qty_match = abs(rec.manual_qty - rec.system_qty) < 0.001
            weight_match = abs(rec.manual_weight - rec.system_weight) <= 0.250
            tag_weight_match = abs(rec.manual_tag_weight - rec.system_tag_weight) <= 0.050
            total_weight_match = abs(rec.manual_total_weight - rec.system_total_weight) <= 0.300

            rec.is_qty_matched = qty_match
            rec.is_weight_matched = weight_match
            rec.is_tag_weight_matched = tag_weight_match
            rec.is_total_weight_matched = total_weight_match
            rec.is_matched = qty_match and total_weight_match

    @api.onchange('manual_weight', 'manual_tag_weight')
    def _onchange_manual_weights(self):
        for rec in self:
            rec.manual_total_weight = (rec.manual_weight or 0.0) + (rec.manual_tag_weight or 0.0)

    @api.onchange('manual_qty')
    def _onchange_manual_qty(self):
        for rec in self:
            if rec.manual_qty > 0 and rec.status == 'pending':
                rec.status = 'verified'
                rec.is_verified = True
                rec.verified_datetime = fields.Datetime.now()
                rec.verified_by = self.env.user.id
            elif rec.manual_qty == 0 and rec.status == 'verified':
                rec.status = 'pending'
                rec.is_verified = False

    def action_verify_line(self):
        """One-click verify action from the list view row or selected rows."""
        return self.action_verify_selected()

    def action_verify_selected(self):
        """Verify all lines in self."""
        lines_to_verify = self.filtered(lambda l: l.status != 'verified')
        if not lines_to_verify:
            return True
        for line in lines_to_verify:
            line.write({
                'status': 'verified',
                'is_verified': True,
                'verified_datetime': fields.Datetime.now(),
                'verified_by': self.env.user.id,
                'manual_qty': 1.0,
                'manual_weight': line.sale_gross_weight or 0.0,
                'manual_tag_weight': line.tag_weight or 0.0,
                'manual_total_weight': (line.sale_gross_weight or 0.0) + (line.tag_weight or 0.0),
            })
        for audit in lines_to_verify.mapped('verification_id'):
            if len(lines_to_verify) == 1:
                line = lines_to_verify[0]
                msg = _("✅ Verified manually: '%s' (%s)") % (
                    line.label_id.name or '',
                    line.product_id.display_name or ''
                )
            else:
                msg = _("✅ Verified %d selected labels.") % len(lines_to_verify)
            audit.write({
                'last_scanned_message': msg,
                'last_scanned_status': 'success',
            })
            audit._sync_template_summaries()
        return True

    def action_unverify_line(self):
        """Undo verification for this row or selected rows."""
        return self.action_unverify_selected()

    def action_unverify_selected(self):
        """Undo verification for all lines in self."""
        for line in self:
            new_status = 'pending' if line.status != 'extra' else 'extra'
            line.write({
                'status': new_status,
                'is_verified': False,
                'verified_datetime': False,
                'verified_by': False,
                'manual_qty': 0.0,
                'manual_weight': 0.0,
                'manual_tag_weight': 0.0,
                'manual_total_weight': 0.0,
            })
        for audit in self.mapped('verification_id'):
            audit.write({
                'last_scanned_message': _("Reset %d label(s) back to pending.") % len(self),
                'last_scanned_status': 'warning',
            })
            audit._sync_template_summaries()
        return True

    def action_view_label(self):
        """Open the detailed product.label form."""
        self.ensure_one()
        if not self.label_id:
            raise UserError(_("No linked product label record found."))
        return {
            'name': _("Product Label"),
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'res_id': self.label_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        audits = lines.mapped('verification_id')
        audits._sync_template_summaries()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('status', 'is_verified', 'product_tmpl_id', 'manual_qty', 'manual_weight', 'manual_tag_weight', 'manual_total_weight')):
            audits = self.mapped('verification_id')
            audits._sync_template_summaries()
        return res

    def unlink(self):
        audits = self.mapped('verification_id').exists()
        res = super().unlink()
        existing_audits = audits.exists()
        if existing_audits:
            existing_audits._sync_template_summaries()
        return res


class BranchLabelVerificationTemplateSummary(models.Model):
    _name = 'branch.label.verification.template.summary'
    _description = 'Branch Label Verification Template Summary'
    _order = 'product_tmpl_id'

    verification_id = fields.Many2one(
        'branch.label.verification',
        string='Verification Session',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        required=True,
        readonly=True,
        index=True,
    )

    system_qty = fields.Float(
        string='Total Labels',
        compute='_compute_system_totals',
        store=True,
        digits=(16, 0),
        readonly=True,
    )
    system_weight = fields.Float(
        string='Total Weight',
        compute='_compute_system_totals',
        store=True,
        digits=(16, 3),
        readonly=True,
    )
    system_tag_weight = fields.Float(
        string='System Tag Weight',
        compute='_compute_system_totals',
        store=True,
        digits=(16, 3),
        readonly=True,
    )
    system_total_weight = fields.Float(
        string='System Total Wt',
        compute='_compute_system_totals',
        store=True,
        digits=(16, 3),
        readonly=True,
    )
    verification_state = fields.Selection(
        related='verification_id.state',
        string='Session Status',
        store=True,
        readonly=True,
    )
    missing_qty = fields.Float(
        string='Missing Labels',
        compute='_compute_system_totals',
        store=True,
        digits=(16, 0),
        readonly=True,
    )
    is_missing = fields.Boolean(
        string='Is Missing',
        compute='_compute_system_totals',
        store=True,
        readonly=True,
    )
    is_vault_item = fields.Boolean(
        string='Vault Item',
        related='product_tmpl_id.is_vault_item',
        store=True,
        readonly=True,
    )
    is_old_gold = fields.Boolean(
        string='Old Gold',
        related='product_tmpl_id.is_old_gold',
        store=True,
        readonly=True,
    )
    is_diamond_og = fields.Boolean(
        string='Diamond OG',
        related='product_tmpl_id.is_diamond_og',
        store=True,
        readonly=True,
    )

    manual_qty = fields.Float(
        string='Counted Labels',
        store=True,
        digits=(16, 0),
        default=0.0,
    )
    manual_weight = fields.Float(
        string='Counted Weight',
        store=True,
        digits=(16, 3),
        default=0.0,
    )
    manual_tag_weight = fields.Float(
        string='Counted Tag Weight',
        store=True,
        digits=(16, 3),
        default=0.0,
    )
    manual_total_weight = fields.Float(
        string='Counted Total Wt',
        store=True,
        digits=(16, 3),
        default=0.0,
    )

    difference_qty = fields.Float(
        string='Diff Labels',
        compute='_compute_differences',
        store=True,
        digits=(16, 0),
        readonly=True,
    )
    difference_weight = fields.Float(
        string='Diff Weight',
        compute='_compute_differences',
        store=True,
        digits=(16, 3),
        readonly=True,
    )
    difference_tag_weight = fields.Float(
        string='Diff Tag Weight',
        compute='_compute_differences',
        store=True,
        digits=(16, 3),
        readonly=True,
    )
    difference_total_weight = fields.Float(
        string='Diff Total Wt',
        compute='_compute_differences',
        store=True,
        digits=(16, 3),
        readonly=True,
    )

    is_qty_matched = fields.Boolean(
        string='Qty Matched',
        compute='_compute_differences',
        store=True,
    )
    is_weight_matched = fields.Boolean(
        string='Weight Matched',
        compute='_compute_differences',
        store=True,
    )
    is_tag_weight_matched = fields.Boolean(
        string='Tag Weight Matched',
        compute='_compute_differences',
        store=True,
    )
    is_total_weight_matched = fields.Boolean(
        string='Total Weight Matched',
        compute='_compute_differences',
        store=True,
    )
    is_matched = fields.Boolean(
        string='Matched',
        compute='_compute_differences',
        store=True,
    )

    @api.depends(
        'product_tmpl_id',
        'product_tmpl_id.is_vault_item',
        'product_tmpl_id.is_old_gold',
        'product_tmpl_id.is_diamond_og',
        'verification_id.state',
        'verification_id.line_ids',
        'verification_id.line_ids.status',
        'verification_id.line_ids.sale_gross_weight',
        'verification_id.line_ids.sale_net_weight',
        'verification_id.line_ids.tag_weight',
    )
    def _compute_system_totals(self):
        for check in self.mapped('verification_id'):
            check_summaries = self.filtered(lambda s: s.verification_id == check)
            lines_by_tmpl = {}
            for line in check.line_ids:
                if line.product_tmpl_id:
                    lines_by_tmpl.setdefault(line.product_tmpl_id.id, []).append(line)

            # Pre-fetch stock quants for bulk summaries (vault items, old gold, diamond og)
            bulk_summaries = check_summaries.filtered(lambda s: s.is_vault_item or s.is_old_gold or s.is_diamond_og)
            bulk_weight_by_tmpl = {}
            if bulk_summaries:
                bulk_locs = check.location_ids if check.location_ids else self.env['stock.location'].search([
                    ('branch_id', '=', check.branch_id.id),
                    ('usage', '=', 'internal')
                ])
                quants = self.env['stock.quant'].search([
                    ('location_id', 'in', bulk_locs.ids),
                    ('quantity', '>', 0),
                    ('product_id.product_tmpl_id', 'in', bulk_summaries.mapped('product_tmpl_id').ids)
                ])
                for tmpl in bulk_summaries.mapped('product_tmpl_id'):
                    tmpl_quants = quants.filtered(lambda q: q.product_id.product_tmpl_id == tmpl)
                    total_quant = sum(tmpl_quants.mapped('quantity'))
                    tmpl_labels = check.line_ids.filtered(lambda l: l.product_tmpl_id == tmpl and l.label_id)
                    total_lbl_wt = sum(tmpl_labels.mapped('sale_gross_weight'))
                    bulk_weight_by_tmpl[tmpl.id] = max(0.0, round(total_quant - total_lbl_wt, 3))

            for rec in check_summaries:
                if not rec.product_tmpl_id:
                    rec.system_qty = 0.0
                    rec.system_weight = 0.0
                    rec.system_tag_weight = 0.0
                    rec.system_total_weight = 0.0
                    rec.missing_qty = 0.0
                    rec.is_missing = False
                    continue

                if rec.is_vault_item or rec.is_old_gold or rec.is_diamond_og:
                    b_wt = bulk_weight_by_tmpl.get(rec.product_tmpl_id.id, 0.0)
                    rec.system_qty = 0.0
                    rec.system_weight = b_wt
                    rec.system_tag_weight = 0.0
                    rec.system_total_weight = b_wt
                    rec.missing_qty = 0.0
                    rec.is_missing = False
                else:
                    lines = lines_by_tmpl.get(rec.product_tmpl_id.id, [])
                    expected_lines = [l for l in lines if l.status != 'extra']
                    missing_lines = [l for l in lines if l.status == 'missing']

                    rec.system_qty = float(sum(l.system_qty for l in expected_lines))
                    rec.system_weight = sum(l.sale_gross_weight or 0.0 for l in expected_lines)
                    rec.system_tag_weight = sum(l.tag_weight or 0.0 for l in expected_lines)
                    rec.system_total_weight = rec.system_weight + rec.system_tag_weight
                    rec.missing_qty = float(sum(l.system_qty for l in missing_lines))
                    rec.is_missing = len(missing_lines) > 0 or (check.state == 'done' and len(missing_lines) > 0)

    @api.depends(
        'system_qty',
        'system_weight',
        'system_tag_weight',
        'system_total_weight',
        'manual_qty',
        'manual_weight',
        'manual_tag_weight',
        'manual_total_weight',
        'is_vault_item',
        'is_old_gold',
        'is_diamond_og',
    )
    def _compute_differences(self):
        for rec in self:
            rec.difference_qty = rec.manual_qty - rec.system_qty
            rec.difference_weight = rec.manual_weight - rec.system_weight
            rec.difference_tag_weight = rec.manual_tag_weight - rec.system_tag_weight
            rec.difference_total_weight = rec.manual_total_weight - rec.system_total_weight

            if rec.is_vault_item or rec.is_old_gold or rec.is_diamond_og:
                qty_match = True
                weight_match = abs(rec.manual_weight - rec.system_weight) <= 0.250
                tag_match = True
                total_weight_match = abs(rec.difference_total_weight) <= 0.300 or weight_match
            else:
                qty_match = abs(rec.manual_qty - rec.system_qty) < 0.001
                weight_match = abs(rec.manual_weight - rec.system_weight) <= 0.250
                tag_match = abs(rec.manual_tag_weight - rec.system_tag_weight) <= 0.050
                total_weight_match = abs(rec.difference_total_weight) <= 0.300

            rec.is_qty_matched = qty_match
            rec.is_weight_matched = weight_match
            rec.is_tag_weight_matched = tag_match
            rec.is_total_weight_matched = total_weight_match
            rec.is_matched = qty_match and total_weight_match

    @api.onchange('manual_weight', 'manual_tag_weight')
    def _onchange_manual_weights(self):
        for rec in self:
            rec.manual_total_weight = (rec.manual_weight or 0.0) + (rec.manual_tag_weight or 0.0)

