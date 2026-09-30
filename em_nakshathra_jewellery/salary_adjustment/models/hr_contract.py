from odoo import models, fields, api
from datetime import date

class HrContract(models.Model):
    _inherit = 'hr.contract'

    # -------------------------------------------------------------
    # TDS Fields (Income Tax - Union Budget 2025)
    # -------------------------------------------------------------
    apply_tds = fields.Boolean(
        string='Apply TDS (Income Tax)',
        default=True,
        help='If checked, monthly TDS (Tax Deducted at Source) will be calculated based on Union Budget 2025 New Tax Regime slabs.'
    )
    tds_include_cess = fields.Boolean(
        string='Include 4% Cess',
        default=False,
        help='If checked, 4% Health & Education Cess will be included in the monthly TDS deduction.'
    )
    custom_monthly_tds = fields.Float(
        string='Custom Monthly TDS',
        default=0.0,
        help='Specify a fixed monthly TDS amount to override the slab calculation. Leave 0.0 to use the automatic slab calculation.'
    )
    tds_standard_deduction = fields.Float(
        string='Standard Deduction',
        default=0.0,
        help='Standard deduction amount (e.g., 75,000) to deduct from annual gross before slab calculation. Leave 0.0 for pure slab calculation.'
    )

    # -------------------------------------------------------------
    # ESI Fields (Employees' State Insurance)
    # -------------------------------------------------------------
    apply_esi = fields.Boolean(
        string='Apply ESI',
        compute='_compute_apply_esi',
        store=True,
        readonly=False,
        default=False,
        help="Enable/disable Employee State Insurance deduction. Automatically set from Employee's Apply ESI setting."
    )

    @api.depends('employee_id', 'employee_id.apply_esi')
    def _compute_apply_esi(self):
        for contract in self:
            if contract.employee_id:
                contract.apply_esi = contract.employee_id.apply_esi
            else:
                contract.apply_esi = False

    @api.onchange('employee_id')
    def _onchange_employee_id_esi(self):
        if self.employee_id:
            self.apply_esi = self.employee_id.apply_esi
    esi_wage_limit = fields.Float(
        string='ESI Wage Limit (₹)',
        default=21000.0,
        help='Statutory eligibility ceiling for ESI (default ₹21,000/month).'
    )
    esi_employee_rate = fields.Float(
        string='ESI Employee Rate (%)',
        default=0.75,
        help='Employee contribution rate percentage (default 0.75%).'
    )
    esi_employer_rate = fields.Float(
        string='ESI Employer Rate (%)',
        default=3.25,
        help='Employer contribution rate percentage (default 3.25%).'
    )
    esi_contribution_start = fields.Date(
        string='ESI Contribution Period Start',
        help='Start date of current ESI contribution period (e.g. 1st April or 1st October).'
    )
    esi_contribution_end = fields.Date(
        string='ESI Contribution Period End',
        help='End date of current ESI contribution period (e.g. 30th September or 31st March). If salary increases above ₹21,000 during this period, ESI continues until this date.'
    )
    custom_monthly_esi = fields.Float(
        string='Custom Monthly ESI',
        default=0.0,
        help='Specify a fixed monthly ESI amount to override automatic calculation. Leave 0.0 for automatic.'
    )

    # -------------------------------------------------------------
    # PF Fields (Employees' Provident Fund)
    # -------------------------------------------------------------
    apply_pf = fields.Boolean(
        string='Apply PF',
        default=True,
        help='Enable/disable Provident Fund (EPF) deduction.'
    )
    pf_employee_rate = fields.Float(
        string='PF Employee Rate (%)',
        default=12.0,
        help='Employee PF contribution rate percentage (default 12%).'
    )
    pf_employer_rate = fields.Float(
        string='PF Employer Rate (%)',
        default=12.0,
        help='Employer PF contribution rate percentage (default 12%).'
    )
    pf_wage_ceiling = fields.Float(
        string='PF Wage Ceiling (₹)',
        default=15000.0,
        help='Statutory wage ceiling for PF (default ₹15,000/month).'
    )
    pf_enforce_ceiling = fields.Boolean(
        string='Enforce ₹15k Ceiling',
        default=True,
        help='If checked, PF base is capped at the wage ceiling (e.g. min(Basic, ₹15,000)). If unchecked, PF is calculated on full actual Basic Salary.'
    )
    custom_monthly_pf = fields.Float(
        string='Custom Monthly PF',
        default=0.0,
        help='Specify a fixed monthly PF amount to override automatic calculation. Leave 0.0 for automatic.'
    )

    @api.onchange('apply_esi', 'date_start')
    def _onchange_esi_period(self):
        if self.apply_esi and not self.esi_contribution_end:
            ref_date = self.date_start or fields.Date.today()
            year = ref_date.year
            if 4 <= ref_date.month <= 9:
                self.esi_contribution_start = date(year, 4, 1)
                self.esi_contribution_end = date(year, 9, 30)
            elif ref_date.month >= 10:
                self.esi_contribution_start = date(year, 10, 1)
                self.esi_contribution_end = date(year + 1, 3, 31)
            else:
                self.esi_contribution_start = date(year - 1, 10, 1)
                self.esi_contribution_end = date(year, 3, 31)

