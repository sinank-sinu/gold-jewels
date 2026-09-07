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
        readonly=False,
    )

    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        required=True,
    )
    branch_salesman_count = fields.Integer(
        string='Branch Salesmen Count',
        compute='_compute_branch_salesman_count',
    )
    date_from = fields.Date(string='Period From', required=True)
    date_to = fields.Date(string='Period To', required=True)

    # Targets
    target_amount = fields.Monetary(
        string='Target Amount',
        currency_field='currency_id',
    )
    target_gms_22k = fields.Float(
        string='Target GMS (grams) 22K',
        digits=(16, 3),
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
    target_diamond_ct = fields.Float(
        string='Target 18 KTD (grams)',
        digits=(16, 3),
        required=True,
    )

    incentive_amount = fields.Monetary(
        string='Fixed Incentive Amount',
        currency_field='currency_id',
    )

    # BRANCH TARGETS
    branch_target_amount = fields.Monetary(
        string='Branch Target Amount',
        currency_field='currency_id',
    )
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
    branch_target_diamond_ct = fields.Float(
        string='Branch Target 18 KTD (grams)',
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

    achieved_diamond_ct = fields.Float(
        string='Achieved 18 KTD (grams',
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

    branch_achieved_diamond_ct = fields.Float(
        string='Branch Achieved 18 KTD (grams)',
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
    inc_18ct = fields.Float(
        string='18CT',
        default=5.0,
    )

    dmd_inc = fields.Float(
        string='18KTD %',
        default=8.0,
    )

    gold_inc = fields.Float(
        string='22KT',
        default=2.0,
    )
    
    # Hidden tracking fields for the report
    mc_amount_18ct = fields.Monetary(
        string='MC Amount 18CT',
        currency_field='currency_id',
        compute='_incentive_add',
        store=True,
    )
    mc_amount_18ktd = fields.Monetary(
        string='MC Amount 18KTD',
        currency_field='currency_id',
        compute='_incentive_add',
        store=True,
    )
    mc_amount_22kt = fields.Monetary(
        string='MC Amount 22KT',
        currency_field='currency_id',
        compute='_incentive_add',
        store=True,
    )

    incentive_add = fields.Float(string='Computed Incentive ',compute='_incentive_add', store=True)

    # EMPLOYEE
    @api.depends('salesman_id')
    def _compute_employee_id(self):
        for rec in self:
            employee = False
            if rec.salesman_id:
                employee = self.env['hr.employee'].search([
                    '|',
                    ('user_id', '=', rec.salesman_id.id),
                    ('name', '=', rec.salesman_id.name)
                ], limit=1)
            rec.employee_id = employee

    @api.depends('branch_id')
    def _compute_branch_salesman_count(self):
        for rec in self:
            if rec.branch_id:
                count = self.env['res.users'].search_count([
                    ('branch_ids', 'in', rec.branch_id.id),
                    ('share', '=', False)
                ])
                rec.branch_salesman_count = count
            else:
                rec.branch_salesman_count = 0

    @api.onchange('branch_target_gms_22k', 'branch_target_gms_18ct', 'branch_target_gms_22kt', 'branch_target_diamond_ct', 'branch_target_amount', 'branch_id')
    def _onchange_branch_targets(self):
        for rec in self:
            count = rec.branch_salesman_count or 1
            if count > 0:
                rec.target_amount = rec.branch_target_amount / count
                rec.target_gms_22k = rec.branch_target_gms_22k / count
                rec.target_gms_18ct = rec.branch_target_gms_18ct / count
                rec.target_gms_22kt = rec.branch_target_gms_22kt / count
                rec.target_diamond_ct = rec.branch_target_diamond_ct / count

    @api.onchange('branch_id')
    def _onchange_fetch_branch_targets(self):
        for rec in self:
            if rec.branch_id:
                existing = self.env['salesman.target'].search([
                    ('branch_id', '=', rec.branch_id.id),
                    ('id', '!=', rec._origin.id if rec._origin else False)
                ], limit=1, order='create_date desc, id desc')

                if existing:
                    rec.branch_target_amount = existing.branch_target_amount
                    rec.branch_target_gms_22k = existing.branch_target_gms_22k
                    rec.branch_target_gms_18ct = existing.branch_target_gms_18ct
                    rec.branch_target_gms_22kt = existing.branch_target_gms_22kt
                    rec.branch_target_diamond_ct = existing.branch_target_diamond_ct
                    rec.target_diamond_ct = existing.target_diamond_ct
                    rec.date_from = existing.date_from
                    rec.date_to = existing.date_to

    def action_view_branch_salesmen(self):
        self.ensure_one()
        return {
            'name': _('Branch Salesmen'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.users',
            'view_mode': 'tree,form',
            'domain': [('branch_ids', 'in', self.branch_id.id), ('share', '=', False)],
            'context': {'default_branch_id': self.branch_id.id},
        }

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
            rec.achieved_diamond_ct = 0.0

            rec.branch_achieved_gms_22k = 0.0
            rec.branch_achieved_gms_18ct = 0.0
            rec.branch_achieved_gms_22kt = 0.0
            rec.branch_achieved_diamond_ct = 0.0

            rec.amount_progress = 0.0
            rec.gms_progress = 0.0

            rec.is_achieved = False
            rec.earned_incentive = 0.0

            if not rec.salesman_id or not rec.date_from or not rec.date_to:
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
            achieved_diamond_ct = 0.0

            for line in salesman_lines:

                if line.display_type:
                    continue

                if not line.purity_id:
                    continue

                purity = (line.purity_id.name or '').strip().upper()

                grams = line.product_uom_qty or 0.0

                amount = line.price_subtotal or 0.0

                if '18KTD' in purity:
                    achieved_diamond_ct += grams
                    achieved_amount += amount
                elif '18CT' in purity:
                    achieved_18ct += grams
                    achieved_amount += amount
                elif '22CT' in purity or '22KT' in purity or '22K' in purity:
                    achieved_22kt += grams
                    achieved_22k += grams
                    achieved_amount += amount
                else:
                    achieved_amount += amount


                # achieved_diamond_ct += line.sale_diamond_weight_ct or 0.0

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
            branch_diamond_ct = 0.0

            for line in branch_lines:

                if line.display_type:
                    continue

                if not line.purity_id:
                    continue

                purity = (line.purity_id.name or '').strip().upper()

                grams = line.product_uom_qty or 0.0

                if '18KTD' in purity:
                    branch_diamond_ct += grams
                elif '18CT' in purity:
                    branch_18ct += grams
                elif '22CT' in purity or '22KT' in purity or '22K' in purity:
                    branch_22kt += grams
                    branch_22k += grams

                # branch_diamond_ct += line.sale_diamond_weight_ct or 0.0

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

            personal_target_hit = True
            if rec.target_gms_18ct > 0:
                personal_target_hit = personal_target_hit and (achieved_18ct >= rec.target_gms_18ct)
            if rec.target_gms_22kt > 0:
                personal_target_hit = personal_target_hit and (achieved_22kt >= rec.target_gms_22kt)
            if rec.target_diamond_ct > 0:
                personal_target_hit = personal_target_hit and (achieved_diamond_ct >= rec.target_diamond_ct)
            if rec.target_gms_22k > 0:
                personal_target_hit = personal_target_hit and (achieved_22k >= rec.target_gms_22k)
            if rec.target_amount > 0:
                personal_target_hit = personal_target_hit and (achieved_amount >= rec.target_amount)

            has_any_target = (rec.target_gms_18ct > 0 or rec.target_gms_22kt > 0 or 
                              rec.target_diamond_ct > 0 or rec.target_gms_22k > 0 or rec.target_amount > 0)
            if not has_any_target:
                personal_target_hit = False

            # IMPORTANT:
            # ONLY PERSONAL TARGET COUNTS

            rec.is_achieved = personal_target_hit

            rec.earned_incentive = (
                rec.incentive_add
                if personal_target_hit
                else 0.0
            )

            # WRITE
            rec.achieved_amount = achieved_amount

            rec.achieved_gms_22k = achieved_22k
            rec.achieved_gms_18ct = achieved_18ct
            rec.achieved_gms_22kt = achieved_22kt
            rec.achieved_diamond_ct = achieved_diamond_ct

            rec.branch_achieved_gms_22k = branch_22k
            rec.branch_achieved_gms_18ct = branch_18ct
            rec.branch_achieved_gms_22kt = branch_22kt
            rec.branch_achieved_diamond_ct = branch_diamond_ct

            rec.achieved_gms = total_achieved

            rec.amount_progress = min(amount_progress, 100.0)
            rec.gms_progress = min(gms_progress, 100.0)

    # VALIDATIONS
    @api.constrains('branch_id','date_from','date_to','target_gms_22k','target_gms_18ct','target_gms_22kt','target_diamond_ct','branch_target_gms_22k','branch_target_gms_18ct','branch_target_gms_22kt','branch_target_diamond_ct')
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
            total_diamond_ct = sum(records.mapped('target_diamond_ct'))

            total_22k += rec.target_gms_22k
            total_18ct += rec.target_gms_18ct
            total_22kt += rec.target_gms_22kt
            total_diamond_ct += rec.target_diamond_ct

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

            if total_diamond_ct > rec.branch_target_diamond_ct:
                raise ValidationError(_(
                    'Total Diamond CT target exceeds Branch Target.\n'
                    'Allowed: %s\n'
                    'Current Total: %s'
                ) % (
                    rec.branch_target_diamond_ct,
                    total_diamond_ct
                ))

    @api.constrains('target_amount', 'target_gms_22k', 'target_gms_18ct', 'target_gms_22kt')
    def _check_positive_targets(self):
        for rec in self:


            if rec.target_gms_22k < 0:
                raise ValidationError(_('22K Target GMS must be positive.'))

            if rec.target_gms_18ct < 0:
                raise ValidationError(_('18CT Target GMS must be positive.'))

            if rec.target_gms_22kt < 0:
                raise ValidationError(_('22KT Target GMS must be positive.'))



            if rec.branch_target_gms_22k < 0:
                raise ValidationError(_('Branch 22K Target must be positive.'))

            if rec.branch_target_gms_18ct < 0:
                raise ValidationError(_('Branch 18CT Target must be positive.'))

            if rec.branch_target_gms_22kt < 0:
                raise ValidationError(_('Branch 22KT Target must be positive.'))

            if rec.branch_target_diamond_ct < 0:
                raise ValidationError(_('Branch Diamond CT Target must be positive.'))

            if rec.target_diamond_ct < 0:
                raise ValidationError(_('Target Diamond CT must be positive.'))

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
        self._incentive_add()
        return True

    @api.depends('is_achieved', 'salesman_id', 'branch_id', 'date_from', 'date_to', 'inc_18ct', 'dmd_inc', 'gold_inc')
    def _incentive_add(self):
        for rec in self:
            rec.incentive_add = 0.0
            rec.mc_amount_18ct = 0.0
            rec.mc_amount_18ktd = 0.0
            rec.mc_amount_22kt = 0.0

            if not (rec.salesman_id and rec.branch_id and rec.date_from and rec.date_to):
                continue

            start_date = fields.Datetime.to_datetime(rec.date_from)
            end_date = fields.Datetime.to_datetime(rec.date_to).replace(hour=23, minute=59, second=59)

            order_lines = self.env['sale.order.line'].search([
                ('order_id.user_id', '=', rec.salesman_id.id),
                ('order_id.branch_id', '=', rec.branch_id.id),
                ('order_id.date_order', '>=', start_date),
                ('order_id.date_order', '<=', end_date),
                ('order_id.state', 'in', ['sale', 'done']),
                ('purity_id', '!=', False),
            ])

            total_additional = 0.0
            mc_18ct = 0.0
            mc_18ktd = 0.0
            mc_22kt = 0.0

            for line in order_lines:
                if line.display_type:
                    continue
                purity = (line.purity_id.name or '').upper().strip()
                mc_amount = getattr(line, 'mc_amount_actual', 0.0) or (
                    line.metal_amount * (line.mc_percent_actual / 100.0)
                    if hasattr(line, 'metal_amount') and hasattr(line, 'mc_percent_actual') and line.metal_amount and line.mc_percent_actual
                    else 0.0
                )

                if '18KTD' in purity:
                    total_additional += mc_amount * (rec.dmd_inc / 100.0)
                    mc_18ktd += mc_amount
                elif '18CT' in purity:
                    total_additional += mc_amount * (rec.inc_18ct / 100.0)
                    mc_18ct += mc_amount
                elif '22CT' in purity or '22KT' in purity or '22K' in purity:
                    total_additional += mc_amount * (rec.gold_inc / 100.0)
                    mc_22kt += mc_amount

            rec.incentive_add = total_additional
            rec.mc_amount_18ct = mc_18ct
            rec.mc_amount_18ktd = mc_18ktd
            rec.mc_amount_22kt = mc_22kt

            if rec.is_achieved:
                rec.earned_incentive = total_additional + (rec.incentive_amount or 0.0)
            else:
                rec.earned_incentive = 0.0

