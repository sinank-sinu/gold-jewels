# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta


class SalesmanIncentiveDeduction(models.Model):
    _name = 'salesman.incentive.deduction'
    _description = 'Sales Return Incentive Deduction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'deduction_month_start desc, id desc'
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
        tracking=True,
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
        tracking=True,
    )
    sale_order_ids = fields.Many2many(
        'sale.order',
        'salesman_incentive_deduction_sale_order_rel',
        'deduction_id',
        'order_id',
        string='Original / Return Sale Orders',
        tracking=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Original / Return Sale Order',
        compute='_compute_sale_order_id',
        inverse='_inverse_sale_order_id',
        store=True,
        tracking=True,
    )
    return_date = fields.Date(
        string='Return Date',
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    return_amount = fields.Monetary(
        string='Return Order Amount',
        currency_field='currency_id',
    )
    return_grams = fields.Float(
        string='Returned Weight (GMS)',
        digits=(16, 3),
    )
    deduction_amount = fields.Monetary(
        string='Incentive Deduction Amount',
        currency_field='currency_id',
        required=True,
        tracking=True,
        help="The amount to be deducted from the salesman's next month incentive."
    )
    deduction_month_start = fields.Date(
        string='Deduction Month From',
        required=True,
        tracking=True,
        help="Start date of the target period (next month) where deduction applies."
    )
    deduction_month_end = fields.Date(
        string='Deduction Month To',
        required=True,
        tracking=True,
        help="End date of the target period where deduction applies."
    )
    target_id = fields.Many2one(
        'salesman.target',
        string='Applied Target',
        readonly=True,
        tracking=True,
        help="The specific salesman target period in which this deduction was absorbed."
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Next Month'),
        ('applied', 'Deducted / Applied'),
        ('cancelled', 'Cancelled'),
    ], default='pending', tracking=True)
    notes = fields.Text(string='Notes')

    @api.depends('sale_order_ids')
    def _compute_sale_order_id(self):
        for rec in self:
            rec.sale_order_id = rec.sale_order_ids[:1].id if rec.sale_order_ids else False

    def _inverse_sale_order_id(self):
        for rec in self:
            if rec.sale_order_id and rec.sale_order_id not in rec.sale_order_ids:
                rec.sale_order_ids = [(4, rec.sale_order_id.id)]
            elif not rec.sale_order_id and rec.sale_order_ids:
                rec.sale_order_ids = [(5, 0, 0)]

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

    def _recompute_deduction_details(self):
        for rec in self:
            if not rec.sale_order_ids:
                rec.return_amount = 0.0
                rec.return_grams = 0.0
                rec.deduction_amount = 0.0
                continue

            target = False
            if rec.salesman_id:
                target = self.env['salesman.target'].search([
                    ('salesman_id', '=', rec.salesman_id.id),
                    ('state', 'in', ['draft', 'confirmed', 'transferred', 'closed']),
                ], limit=1, order='date_to desc, id desc')

            dmd_rate = target.dmd_inc if target and target.dmd_inc else 8.0
            ct18_rate = target.inc_18ct if target and target.inc_18ct else 5.0
            kt22_rate = target.gold_inc if target and target.gold_inc else 2.0

            total_return_amount = 0.0
            total_return_grams = 0.0
            total_deduction_amount = 0.0
            latest_date = False

            for order in rec.sale_order_ids:
                if order.date_order:
                    o_date = order.date_order.date()
                    if not latest_date or o_date > latest_date:
                        latest_date = o_date

                return_lines = getattr(order, 'sale_return_line_ids', False)
                if return_lines:
                    for r_line in return_lines:
                        grams = r_line.net_weight or r_line.gross_weight or 0.0
                        amt = r_line.amount or (grams * (r_line.rate or 0.0))
                        purity_name = (r_line.purity_id.name or '').upper().strip() if r_line.purity_id else ''

                        total_return_amount += amt
                        total_return_grams += grams

                        if '18KTD' in purity_name:
                            rate_pct = dmd_rate
                        elif '18CT' in purity_name:
                            rate_pct = ct18_rate
                        elif any(k in purity_name for k in ['22CT', '22KT', '22K']):
                            rate_pct = kt22_rate
                        else:
                            rate_pct = 2.0

                        line_mc = getattr(r_line, 'mc_amount', 0.0) or (amt * 0.10)
                        total_deduction_amount += line_mc * (rate_pct / 100.0)
                elif order.order_line:
                    for line in order.order_line:
                        if line.display_type:
                            continue
                        grams = line.product_uom_qty or 0.0
                        amt = line.price_subtotal or 0.0
                        purity_name = (line.purity_id.name or '').upper().strip() if line.purity_id else ''

                        total_return_amount += amt
                        total_return_grams += grams

                        if '18KTD' in purity_name:
                            rate_pct = dmd_rate
                        elif '18CT' in purity_name:
                            rate_pct = ct18_rate
                        elif any(k in purity_name for k in ['22CT', '22KT', '22K']):
                            rate_pct = kt22_rate
                        else:
                            rate_pct = 2.0

                        mc_amount = getattr(line, 'mc_amount_actual', 0.0) or (
                            line.metal_amount * (line.mc_percent_actual / 100.0)
                            if hasattr(line, 'metal_amount') and hasattr(line, 'mc_percent_actual') and line.metal_amount and line.mc_percent_actual
                            else 0.0
                        )
                        if mc_amount <= 0.0 and amt > 0.0:
                            mc_amount = amt * 0.10

                        total_deduction_amount += mc_amount * (rate_pct / 100.0)
                else:
                    amt = abs(order.amount_total or 0.0)
                    total_return_amount += amt
                    total_deduction_amount += amt * 0.02

            rec.return_amount = round(total_return_amount, 2)
            rec.return_grams = round(total_return_grams, 3)
            rec.deduction_amount = round(total_deduction_amount, 2)

            if latest_date and rec.state in ['draft', 'pending']:
                rec.return_date = latest_date
                next_month_start = (latest_date + relativedelta(months=1)).replace(day=1)
                next_month_end = next_month_start + relativedelta(months=1, days=-1)
                rec.deduction_month_start = next_month_start
                rec.deduction_month_end = next_month_end

    @api.onchange('salesman_id')
    def _onchange_salesman_id(self):
        if not self.salesman_id:
            self.employee_id = False
            self.sale_order_ids = False
            return {'domain': {'sale_order_ids': [('id', '=', False)]}}

        # 1. Update Employee
        employee = self.env['hr.employee'].search([
            '|',
            ('user_id', '=', self.salesman_id.id),
            ('name', '=', self.salesman_id.name)
        ], limit=1)
        self.employee_id = employee

        # 2. Update Branch if not set
        if not self.branch_id:
            if self.salesman_id.branch_id:
                self.branch_id = self.salesman_id.branch_id
            elif self.salesman_id.branch_ids:
                self.branch_id = self.salesman_id.branch_ids[0]

        # 3. Automatically find and add return sales for this salesman
        domain = [
            ('state', '!=', 'cancel'),
            '|', ('user_id', '=', self.salesman_id.id), ('order_line.salesman_id', '=', self.salesman_id.id),
            '|', ('is_sale_return', '=', True), '|', ('sale_return_line_ids', '!=', False), ('name', 'ilike', 'RET')
        ]
        if self.branch_id:
            domain.append(('branch_id', '=', self.branch_id.id))

        return_sos = self.env['sale.order'].search(domain, order='date_order desc, id desc')

        # Exclude return orders already in active deductions
        active_deductions = self.search([
            ('id', '!=', self._origin.id if self._origin else False),
            ('state', 'in', ['pending', 'applied']),
        ])
        already_linked_order_ids = active_deductions.mapped('sale_order_ids.id')
        available_return_sos = return_sos.filtered(lambda s: s.id not in already_linked_order_ids)

        if available_return_sos:
            self.sale_order_ids = [(6, 0, available_return_sos.ids)]
        else:
            self.sale_order_ids = False

        self._recompute_deduction_details()

        order_domain = [
            '|', ('user_id', '=', self.salesman_id.id), ('order_line.salesman_id', '=', self.salesman_id.id)
        ]
        if self.branch_id:
            order_domain.append(('branch_id', '=', self.branch_id.id))
        return {'domain': {'sale_order_ids': order_domain}}

    @api.onchange('sale_order_ids')
    def _onchange_sale_order_ids(self):
        self._recompute_deduction_details()

    @api.onchange('branch_id')
    def _onchange_branch_id(self):
        domain = {}
        if self.branch_id:
            domain['salesman_id'] = [('branch_ids', 'in', self.branch_id.id), ('share', '=', False)]
            if self.salesman_id and self.branch_id not in self.salesman_id.branch_ids and self.branch_id != self.salesman_id.branch_id:
                self.salesman_id = False
                self.sale_order_ids = False
                self.return_amount = 0.0
                self.return_grams = 0.0
                self.deduction_amount = 0.0
        else:
            domain['salesman_id'] = [('share', '=', False)]

        if self.salesman_id:
            order_domain = [
                '|', ('user_id', '=', self.salesman_id.id), ('order_line.salesman_id', '=', self.salesman_id.id)
            ]
            if self.branch_id:
                order_domain.append(('branch_id', '=', self.branch_id.id))
            domain['sale_order_ids'] = order_domain

        return {'domain': domain}

    @api.onchange('return_date')
    def _onchange_return_date(self):
        if self.return_date:
            next_month_start = (self.return_date + relativedelta(months=1)).replace(day=1)
            next_month_end = next_month_start + relativedelta(months=1, days=-1)
            self.deduction_month_start = next_month_start
            self.deduction_month_end = next_month_end

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('salesman.incentive.deduction') or _('New')

            # Sync Many2one sale_order_id and Many2many sale_order_ids if one is missing
            if 'sale_order_id' in vals and vals['sale_order_id'] and not vals.get('sale_order_ids'):
                vals['sale_order_ids'] = [(4, vals['sale_order_id'])]
            elif 'sale_order_ids' in vals and vals['sale_order_ids'] and not vals.get('sale_order_id'):
                for cmd in vals['sale_order_ids']:
                    if isinstance(cmd, (list, tuple)) and len(cmd) >= 3 and cmd[0] == 6 and cmd[2]:
                        vals['sale_order_id'] = cmd[2][0]
                        break
                    elif isinstance(cmd, (list, tuple)) and len(cmd) >= 2 and cmd[0] == 4 and cmd[1]:
                        vals['sale_order_id'] = cmd[1]
                        break

            # Auto compute next month range if not provided
            if 'return_date' in vals and ('deduction_month_start' not in vals or not vals.get('deduction_month_start')):
                ret_date = fields.Date.to_date(vals['return_date']) if vals.get('return_date') else fields.Date.today()
                next_month_start = (ret_date + relativedelta(months=1)).replace(day=1)
                next_month_end = next_month_start + relativedelta(months=1, days=-1)
                vals['deduction_month_start'] = next_month_start
                vals['deduction_month_end'] = next_month_end

        records = super().create(vals_list)
        for rec in records:
            if rec.sale_order_ids and not rec.deduction_amount:
                rec._recompute_deduction_details()
        return records

    def action_confirm(self):
        for rec in self:
            rec.state = 'pending'

    def action_apply(self):
        for rec in self:
            rec.state = 'applied'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def action_reset_draft(self):
        for rec in self:
            rec.state = 'draft'
