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
    target_gms = fields.Float(
        string='Target GMS (grams)',
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
    @api.depends('salesman_id', 'date_from', 'date_to', 'target_amount', 'target_gms', 'incentive_amount')
    def _compute_achievements(self):
        SaleOrder = self.env['sale.order']
        # GMS UoM reference
        gram_uom = self.env.ref('uom.product_uom_gram', raise_if_not_found=False)

        for rec in self:
            if not rec.salesman_id or not rec.date_from or not rec.date_to:
                rec.achieved_amount = 0.0
                rec.achieved_gms = 0.0
                rec.is_achieved = False
                rec.earned_incentive = 0.0
                rec.amount_progress = 0.0
                rec.gms_progress = 0.0
                continue

            # Fetch all confirmed / done sale orders for this salesman in the period
            domain = [
                ('user_id', '=', rec.salesman_id.id),
                ('state', 'in', ['sale', 'done']),
                ('date_order', '>=', fields.Datetime.to_datetime(rec.date_from)),
                ('date_order', '<=', fields.Datetime.to_datetime(rec.date_to).replace(
                    hour=23, minute=59, second=59
                )),
            ]
            orders = SaleOrder.search(domain)

            # Achieved Amount: sum of order totals
            achieved_amount = sum(orders.mapped('amount_total'))

            # Achieved GMS: sum of quantities on lines where UoM is grams
            achieved_gms = 0.0
            for line in orders.mapped('order_line'):
                uom = line.product_uom
                if gram_uom and uom:
                    if uom.id == gram_uom.id or uom.category_id == gram_uom.category_id:
                        # Convert to grams if it's in the weight/mass category
                        try:
                            gms = uom._compute_quantity(line.product_uom_qty, gram_uom)
                        except Exception:
                            gms = 0.0
                        achieved_gms += gms

            # Progress %
            amount_progress = (achieved_amount / rec.target_amount * 100.0) if rec.target_amount else 0.0
            gms_progress = (achieved_gms / rec.target_gms * 100.0) if rec.target_gms else 0.0

            # Achievement check: BOTH targets must be hit
            is_achieved = (achieved_amount >= rec.target_amount and achieved_gms >= rec.target_gms)

            rec.achieved_amount = achieved_amount
            rec.achieved_gms = achieved_gms
            rec.amount_progress = min(amount_progress, 100.0)
            rec.gms_progress = min(gms_progress, 100.0)
            rec.is_achieved = is_achieved
            rec.earned_incentive = rec.incentive_amount if is_achieved else 0.0

    # -------------------------------------------------------------------------
    # Constraints
    # -------------------------------------------------------------------------
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_('Period From must be before Period To.'))

    @api.constrains('target_amount', 'target_gms', 'incentive_amount')
    def _check_positive_targets(self):
        for rec in self:
            if rec.target_amount <= 0:
                raise ValidationError(_('Target Amount must be greater than zero.'))
            if rec.target_gms <= 0:
                raise ValidationError(_('Target GMS must be greater than zero.'))
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
