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
    date_from = fields.Date(string='Period From', required=True)
    date_to = fields.Date(string='Period To', required=True)

    # Targets
    target_amount = fields.Monetary(
        string='Target Amount',
        currency_field='currency_id',
        required=True,
    )
    # target_gms = fields.Float(
    #     string='Target GMS (grams)',
    #     digits=(16, 3),
    #     required=True,
    # )
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
        help='Fixed bonus to be paid when both targets (amount + GMS) are achieved.',
    )

    # Achievements (computed)
    achieved_amount = fields.Monetary(
        string='Achieved Amount',
        currency_field='currency_id',
        compute='_compute_achievements',
        store=True,
    )
    achieved_gms = fields.Float(
        string='Achieved GMS (grams)',
        digits=(16, 3),
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
        digits=(5, 2),
    )
    gms_progress = fields.Float(
        string='GMS Progress (%)',
        compute='_compute_achievements',
        store=True,
        digits=(5, 2),
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
    ], string='Status', default='draft', tracking=True)

    notes = fields.Text(string='Notes')

    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Payslip',
        readonly=True,
    )

    payment_date = fields.Date(
        string='Payment Date',
        readonly=True,
    )
    # -------------------------------------------------------------------------
    # Compute: link to employee record
    # -------------------------------------------------------------------------
    @api.depends('salesman_id')
    def _compute_employee_id(self):
        Employee = self.env['hr.employee']
        for rec in self:
            if rec.salesman_id:
                employee = Employee.search(
                    [('user_id', '=', rec.salesman_id.id)], limit=1
                )
                rec.employee_id = employee
            else:
                rec.employee_id = False

    # -------------------------------------------------------------------------
    # Compute: achievements from confirmed sale orders
    # -------------------------------------------------------------------------

    @api.depends('salesman_id', 'date_from', 'date_to', 'target_amount', 'target_gms_22k', 'target_gms_18ct', 'target_gms_22kt', 'incentive_amount')
    def _compute_achievements(self):

        SaleOrderLine = self.env['sale.order.line']

        for rec in self:

            achieved_amount = 0.0

            achieved_22k = 0.0
            achieved_18ct = 0.0
            achieved_22kt = 0.0

            rec.achieved_amount = 0.0

            rec.achieved_gms_22k = 0.0
            rec.achieved_gms_18ct = 0.0
            rec.achieved_gms_22kt = 0.0

            rec.amount_progress = 0.0
            rec.gms_progress = 0.0

            rec.is_achieved = False
            rec.earned_incentive = 0.0

            if not rec.salesman_id or not rec.date_from or not rec.date_to:
                continue
            
            domain = [
                ('order_id.user_id', '=', rec.salesman_id.id),
                ('order_id.state', 'in', ['sale', 'done']),
                ('order_id.date_order', '>=', fields.Datetime.to_datetime(rec.date_from)),
                ('order_id.date_order', '<=', fields.Datetime.to_datetime(rec.date_to).replace(
                    hour=23,
                    minute=59,
                    second=59
                )),
            ]

            lines = SaleOrderLine.search(domain)

            for line in lines:

                # Skip section/note
                if line.display_type:
                    continue

                # Skip if no purity
                if not line.purity_id:
                    continue

                purity_name = line.purity_id.name.strip().upper()

                grams = line.product_uom_qty or 0.0

                if purity_name == '22K':
                    achieved_22k += grams
                    achieved_amount += line.price_subtotal

                elif purity_name == '18CT':
                    achieved_18ct += grams
                    achieved_amount += line.price_subtotal

                elif purity_name == '22KT':
                    achieved_22kt += grams
                    achieved_amount += line.price_subtotal


            amount_progress = 0.0

            if rec.target_amount:
                amount_progress = (
                    achieved_amount / rec.target_amount
                ) * 100


            total_target_gms = (
                rec.target_gms_22k
                + rec.target_gms_18ct
                + rec.target_gms_22kt
            )

            total_achieved_gms = (
                achieved_22k
                + achieved_18ct
                + achieved_22kt
            )

            gms_progress = 0.0

            if total_target_gms:
                gms_progress = (
                    total_achieved_gms / total_target_gms
                ) * 100


            is_achieved = (
                achieved_amount >= rec.target_amount
                and achieved_22k >= rec.target_gms_22k
                and achieved_18ct >= rec.target_gms_18ct
                and achieved_22kt >= rec.target_gms_22kt
            )


            rec.achieved_amount = achieved_amount

            rec.achieved_gms_22k = achieved_22k
            rec.achieved_gms_18ct = achieved_18ct
            rec.achieved_gms_22kt = achieved_22kt

            rec.amount_progress = min(amount_progress, 100.0)
            rec.gms_progress = min(gms_progress, 100.0)

            rec.is_achieved = is_achieved

            rec.earned_incentive = (
                rec.incentive_amount
                if is_achieved
                else 0.0
            )

    # -------------------------------------------------------------------------
    # Constraints
    # -------------------------------------------------------------------------
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_('Period From must be before Period To.'))


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

    # -------------------------------------------------------------------------
    # Sequence on create
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('salesman.target') or _('New')
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # Button actions
    # -------------------------------------------------------------------------
    def action_confirm(self):
        for rec in self:
            rec.state = 'confirmed'

    def action_mark_paid(self):
        for rec in self:
            if not rec.is_achieved:
                raise ValidationError(
                    _('Incentive cannot be marked as paid because both targets have not been achieved yet.')
                )
            rec.state = 'paid'

    def action_reset_draft(self):
        for rec in self:
            rec.state = 'draft'

    def action_refresh_achievements(self):
        """Manual refresh button to recompute achievements."""
        self._compute_achievements()
        return True
