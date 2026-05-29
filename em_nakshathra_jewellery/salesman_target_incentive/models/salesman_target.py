from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SalesmanTarget(models.Model):
    _name = 'salesman.target'
    _description = 'Salesman Target & Incentive'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
    )
    salesman_id = fields.Many2one(
        'res.users',
        string='Salesman',
        required=True,
        domain=[('share', '=', False)],
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        compute='_compute_employee_id',
        store=True,
    )

    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        required=True,
    )
    date_from = fields.Date(string='Period From', required=True)
    date_to = fields.Date(string='Period To', required=True)

    # Targets
    target_amount = fields.Monetary(
        string='Target Amount',
        currency_field='currency_id',
        required=True,
    )
    target_gms_22k = fields.Float(
        string='Target GMS (grams) 22K',
        digits=(16, 3),
        required=True,
    )
    target_gms_18ct = fields.Float(
        string='Target GMS (grams) 18CT',
        digits=(16, 3),
        required=True,
    )
    target_gms_22kt = fields.Float(
        string='Target GMS (grams) 22KT',
        digits=(16, 3),
        required=True,
    )

    incentive_amount = fields.Monetary(
        string='Fixed Incentive Amount',
        currency_field='currency_id',
        required=True,
    )

    # BRANCH TARGETS
    branch_target_gms_22k = fields.Float(
        string='Branch Target GMS (grams) 22K',
        digits=(16, 3),
    )

    branch_target_gms_18ct = fields.Float(
        string='Branch Target GMS (grams) 18CT',
        digits=(16, 3),
    )

    branch_target_gms_22kt = fields.Float(
        string='Branch Target GMS (grams) 22KT',
        digits=(16, 3),
    )

    # =========================================================
    # ACHIEVEMENTS
    # =========================================================

    achieved_amount = fields.Monetary(
        string='Achieved Amount',
        currency_field='currency_id',
        compute='_compute_achievements',
        store=True,
    )

    achieved_gms_22k = fields.Float(
        string='Achieved 22K GMS',
        compute='_compute_achievements',
        store=True,
        digits=(16, 3),
    )

    achieved_gms_18ct = fields.Float(
        string='Achieved 18CT GMS',
        compute='_compute_achievements',
        store=True,
        digits=(16, 3),
    )

    achieved_gms_22kt = fields.Float(
        string='Achieved 22KT GMS',
        compute='_compute_achievements',
        store=True,
        digits=(16, 3),
    )

    achieved_gms = fields.Float(
        string='Achieved Total GMS',
        compute='_compute_achievements',
        store=True,
        digits=(16, 3),
    )

    # BRANCH ACHIEVEMENTS
    branch_achieved_gms_22k = fields.Float(
        string='Branch Achieved 22K GMS',
        compute='_compute_achievements',
        store=True,
        digits=(16, 3),
    )

    branch_achieved_gms_18ct = fields.Float(
        string='Branch Achieved 18CT GMS',
        compute='_compute_achievements',
        store=True,
        digits=(16, 3),
    )

    branch_achieved_gms_22kt = fields.Float(
        string='Branch Achieved 22KT GMS',
        compute='_compute_achievements',
        store=True,
        digits=(16, 3),
    )

    # RESULT
    is_achieved = fields.Boolean(
        string='Both Targets Hit',
        compute='_compute_achievements',
        store=True,
    )
    earned_incentive = fields.Monetary(
        string='Earned Incentive',
        currency_field='currency_id',
        compute='_compute_achievements',
        store=True,
    )

    # Progress percentages
    amount_progress = fields.Float(
        string='Amount Progress (%)',
        compute='_compute_achievements',
        store=True,
    )

    gms_progress = fields.Float(
        string='GMS Progress (%)',
        compute='_compute_achievements',
        store=True,
    )

    # OTHER
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
    ], default='draft')

    payslip_id = fields.Many2one(
        'hr.payslip',
        readonly=True,
    )

    payment_date = fields.Date(readonly=True)
    notes = fields.Text()

    # EMPLOYEE
    @api.depends('salesman_id')
    def _compute_employee_id(self):
        for rec in self:
            employee = self.env['hr.employee'].search([
                ('user_id', '=', rec.salesman_id.id)
            ], limit=1)

            rec.employee_id = employee

    # ACHIEVEMENTS
    @api.depends(
        'salesman_id',
        'branch_id',
        'date_from',
        'date_to',
    )
    def _compute_achievements(self):

        SaleOrderLine = self.env['sale.order.line']

        for rec in self:

            rec.achieved_amount = 0.0
            rec.achieved_gms_22k = 0.0
            rec.achieved_gms_18ct = 0.0
            rec.achieved_gms_22kt = 0.0

            rec.branch_achieved_gms_22k = 0.0
            rec.branch_achieved_gms_18ct = 0.0
            rec.branch_achieved_gms_22kt = 0.0

            rec.amount_progress = 0.0
            rec.gms_progress = 0.0

            rec.is_achieved = False
            rec.earned_incentive = 0.0

            if not rec.salesman_id:
                continue

            start_date = fields.Datetime.to_datetime(rec.date_from)

            end_date = fields.Datetime.to_datetime(
                rec.date_to
            ).replace(
                hour=23,
                minute=59,
                second=59
            )

            # =====================================================
            # PERSONAL SALES
            # =====================================================

            salesman_domain = [
                ('order_id.user_id', '=', rec.salesman_id.id),
                ('order_id.branch_id', '=', rec.branch_id.id),
                ('order_id.state', 'in', ['sale', 'done']),
                ('order_id.date_order', '>=', start_date),
                ('order_id.date_order', '<=', end_date),
            ]

            salesman_lines = SaleOrderLine.search(salesman_domain)

            achieved_amount = 0.0

            achieved_22k = 0.0
            achieved_18ct = 0.0
            achieved_22kt = 0.0

            for line in salesman_lines:

                if line.display_type:
                    continue

                if not line.purity_id:
                    continue

                purity = (line.purity_id.name or '').strip().upper()

                grams = line.product_uom_qty or 0.0

                amount = line.price_subtotal or 0.0

                if purity == '22K':
                    achieved_22k += grams
                    achieved_amount += amount

                elif purity == '18CT':
                    achieved_18ct += grams
                    achieved_amount += amount

                elif purity == '22KT':
                    achieved_22kt += grams
                    achieved_amount += amount

            # =====================================================
            # BRANCH SALES
            # =====================================================

            branch_domain = [
                ('order_id.branch_id', '=', rec.branch_id.id),
                ('order_id.state', 'in', ['sale', 'done']),
                ('order_id.date_order', '>=', start_date),
                ('order_id.date_order', '<=', end_date),
            ]

            branch_lines = SaleOrderLine.search(branch_domain)

            branch_22k = 0.0
            branch_18ct = 0.0
            branch_22kt = 0.0

            for line in branch_lines:

                if line.display_type:
                    continue

                if not line.purity_id:
                    continue

                purity = (line.purity_id.name or '').strip().upper()

                grams = line.product_uom_qty or 0.0

                if purity == '22K':
                    branch_22k += grams

                elif purity == '18CT':
                    branch_18ct += grams

                elif purity == '22KT':
                    branch_22kt += grams

            # =====================================================
            # PROGRESS
            # =====================================================

            total_target = (
                rec.target_gms_22k
                + rec.target_gms_18ct
                + rec.target_gms_22kt
            )

            total_achieved = (
                achieved_22k
                + achieved_18ct
                + achieved_22kt
            )

            amount_progress = 0.0
            gms_progress = 0.0

            if rec.target_amount:
                amount_progress = (
                    achieved_amount / rec.target_amount
                ) * 100

            if total_target:
                gms_progress = (
                    total_achieved / total_target
                ) * 100

            # =====================================================
            # FINAL ACHIEVEMENT
            # =====================================================

            personal_target_hit = (
                achieved_amount >= rec.target_amount
                and achieved_22k >= rec.target_gms_22k
                and achieved_18ct >= rec.target_gms_18ct
                and achieved_22kt >= rec.target_gms_22kt
            )

            # IMPORTANT:
            # ONLY PERSONAL TARGET COUNTS

            rec.is_achieved = personal_target_hit

            rec.earned_incentive = (
                rec.incentive_amount
                if personal_target_hit
                else 0.0
            )

            # WRITE
            rec.achieved_amount = achieved_amount

            rec.achieved_gms_22k = achieved_22k
            rec.achieved_gms_18ct = achieved_18ct
            rec.achieved_gms_22kt = achieved_22kt

            rec.branch_achieved_gms_22k = branch_22k
            rec.branch_achieved_gms_18ct = branch_18ct
            rec.branch_achieved_gms_22kt = branch_22kt

            rec.achieved_gms = total_achieved

            rec.amount_progress = min(amount_progress, 100.0)
            rec.gms_progress = min(gms_progress, 100.0)

    # VALIDATIONS
    @api.constrains('branch_id','date_from','date_to','target_gms_22k','target_gms_18ct','target_gms_22kt','branch_target_gms_22k','branch_target_gms_18ct','branch_target_gms_22kt')
    def _check_branch_target_limit(self):
        for rec in self:
            records = self.search([
                ('id', '!=', rec.id),
                ('branch_id', '=', rec.branch_id.id),
                ('date_from', '=', rec.date_from),
                ('date_to', '=', rec.date_to),
            ])
            total_22k = sum(records.mapped('target_gms_22k'))
            total_18ct = sum(records.mapped('target_gms_18ct'))
            total_22kt = sum(records.mapped('target_gms_22kt'))

            total_22k += rec.target_gms_22k
            total_18ct += rec.target_gms_18ct
            total_22kt += rec.target_gms_22kt

            if total_22k > rec.branch_target_gms_22k:
                raise ValidationError(_(
                    'Total 22K target exceeds Branch Target.\n'
                    'Allowed: %s\n'
                    'Current Total: %s'
                ) % (
                    rec.branch_target_gms_22k,
                    total_22k
                ))

            if total_18ct > rec.branch_target_gms_18ct:
                raise ValidationError(_(
                    'Total 18CT target exceeds Branch Target.\n'
                    'Allowed: %s\n'
                    'Current Total: %s'
                ) % (
                    rec.branch_target_gms_18ct,
                    total_18ct
                ))

            if total_22kt > rec.branch_target_gms_22kt:
                raise ValidationError(_(
                    'Total 22KT target exceeds Branch Target.\n'
                    'Allowed: %s\n'
                    'Current Total: %s'
                ) % (
                    rec.branch_target_gms_22kt,
                    total_22kt
                ))

    @api.constrains('target_amount', 'target_gms_22k', 'target_gms_18ct', 'target_gms_22kt', 'incentive_amount')
    def _check_positive_targets(self):
        for rec in self:
            if rec.target_amount <= 0:
                raise ValidationError(_('Target Amount must be greater than zero.'))

            if rec.target_gms_22k < 0:
                raise ValidationError(_('22K Target GMS must be positive.'))

            if rec.target_gms_18ct < 0:
                raise ValidationError(_('18CT Target GMS must be positive.'))

            if rec.target_gms_22kt < 0:
                raise ValidationError(_('22KT Target GMS must be positive.'))

            if rec.incentive_amount <= 0:
                raise ValidationError(_('Incentive Amount must be greater than zero.'))
            if rec.branch_target_gms_22k < 0:
                raise ValidationError(_('Branch 22K Target must be positive.'))

            if rec.branch_target_gms_18ct < 0:
                raise ValidationError(_('Branch 18CT Target must be positive.'))

            if rec.branch_target_gms_22kt < 0:
                raise ValidationError(_('Branch 22KT Target must be positive.'))

    # DATE VALIDATION
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise ValidationError(
                    _('Period From must be before Period To.')
                )

    # CREATE SEQUENCE
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env[
                    'ir.sequence'
                ].next_by_code('salesman.target') or _('New')
        return super().create(vals_list)

    # BUTTONS
    def action_confirm(self):
        for rec in self:
            rec.state = 'confirmed'

    def action_mark_paid(self):
        for rec in self:
            if not rec.is_achieved:
                raise ValidationError(_(
                    'Salesman target not achieved.'
                ))
            rec.state = 'paid'

    def action_reset_draft(self):
        for rec in self:
            rec.state = 'draft'

    def action_refresh_achievements(self):
        """Manual refresh button to recompute achievements."""
        self._compute_achievements()
        return True
