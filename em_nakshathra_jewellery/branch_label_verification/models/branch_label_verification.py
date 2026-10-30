# -*- coding: utf-8 -*-
import base64
from io import BytesIO
import xlsxwriter

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


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
    ], readonly=True)

    line_ids = fields.One2many(
        'branch.label.verification.line',
        'verification_id',
        string='Verification Lines',
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

    notes = fields.Text(string='Audit Observations & Remarks')

    @api.depends(
        'line_ids',
        'line_ids.status',
        'line_ids.sale_gross_weight',
        'line_ids.sale_net_weight'
    )
    def _compute_kpi_summary(self):
        for rec in self:
            expected_lines = rec.line_ids.filtered(lambda l: l.status != 'extra')
            verified_lines = rec.line_ids.filtered(lambda l: l.status == 'verified')
            pending_lines = rec.line_ids.filtered(lambda l: l.status == 'pending')
            missing_lines = rec.line_ids.filtered(lambda l: l.status == 'missing')
            extra_lines = rec.line_ids.filtered(lambda l: l.status == 'extra')

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

        domain = [('branch_id', '=', self.branch_id.id)]
        if self.location_ids:
            domain.append(('branch_location_id', 'in', self.location_ids.ids))

        if self.label_filter == 'active':
            domain.append(('active', '=', True))
        elif self.label_filter == 'inactive':
            domain.append(('active', '=', False))

        labels = self.env['product.label'].search(domain, order='product_tmpl_id asc, name asc')
        if not labels:
            raise UserError(_("No labels found for branch '%s' matching the selected criteria.") % self.branch_id.name)

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
                'active': lbl.active,
                'status': 'pending',
                'is_verified': False,
            })

        self.env['branch.label.verification.line'].create(lines_vals)
        self.write({
            'state': 'in_progress',
            'last_scanned_message': _("Loaded %d labels for branch '%s'. Ready for verification.") % (len(labels), self.branch_id.name),
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

        # Update verified product.label records
        verified_lines = self.line_ids.filtered(lambda l: l.status == 'verified' and l.label_id)
        if verified_lines:
            verified_lines.mapped('label_id').sudo().write({
                'last_verification_id': self.id,
                'last_verification_date': fields.Datetime.now(),
                'last_verified_by': self.env.user.id,
            })

        self.state = 'done'
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
        self.state = 'draft'
        return True

    def action_export_excel(self):
        """Generate styled Excel report summarizing the branch label audit."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/branch_label_verification/export_xlsx?id={self.id}',
            'target': 'new',
        }


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
        related='label_id.name',
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

    def action_verify_line(self):
        """One-click verify action from the list view row."""
        self.ensure_one()
        self.write({
            'status': 'verified',
            'is_verified': True,
            'verified_datetime': fields.Datetime.now(),
            'verified_by': self.env.user.id,
        })
        self.verification_id.write({
            'last_scanned_message': _("✅ Verified manually: '%s' (%s)") % (
                self.label_id.name or '',
                self.product_id.display_name or ''
            ),
            'last_scanned_status': 'success',
        })
        return True

    def action_unverify_line(self):
        """Undo verification for this row."""
        self.ensure_one()
        new_status = 'pending' if self.status != 'extra' else 'extra'
        self.write({
            'status': new_status,
            'is_verified': False,
            'verified_datetime': False,
            'verified_by': False,
        })
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


class ProductLabelInherit(models.Model):
    _inherit = 'product.label'

    last_verification_id = fields.Many2one(
        'branch.label.verification',
        string='Last Verification Audit',
        readonly=True,
        copy=False,
    )
    last_verification_date = fields.Datetime(
        string='Last Verified At',
        readonly=True,
        copy=False,
    )
    last_verified_by = fields.Many2one(
        'res.users',
        string='Last Verified By',
        readonly=True,
        copy=False,
    )

    def action_view_verification_audits(self):
        """Smart button action to show all audits containing this label."""
        self.ensure_one()
        lines = self.env['branch.label.verification.line'].search([('label_id', '=', self.id)])
        audit_ids = lines.mapped('verification_id').ids
        return {
            'name': _("Verification Audits"),
            'type': 'ir.actions.act_window',
            'res_model': 'branch.label.verification',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', audit_ids)],
            'target': 'current',
        }
