from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    national_id = fields.Char(
        string='National / Iqama / Civil ID / QID / CPR',
        groups="hr.group_hr_user",
        help='Employee national identification number across GCC and Malaysia'
    )
    labor_card_no = fields.Char(
        string='Labour Card / Employee ID Card',
        groups="hr.group_hr_user",
        help='Labour Card or Employee Card Number (used in UAE, Oman)'
    )
    epf_no = fields.Char(
        string='EPF Account Number',
        groups="hr.group_hr_user",
        help='KWSP / Employee Provident Fund Account Number (Malaysia)'
    )
    socso_no = fields.Char(
        string='SOCSO Account Number',
        groups="hr.group_hr_user",
        help='PERKESO / Social Security Organisation Account Number (Malaysia)'
    )
    tax_no = fields.Char(
        string='Tax Identification Number (TIN)',
        groups="hr.group_hr_user",
        help='LHDN / Income Tax Number (Malaysia)'
    )
    apply_esi = fields.Boolean(
        string='Apply ESI',
        default=False,
        groups="hr.group_hr_user",
        tracking=True,
        help="If ticked, Employees' State Insurance (ESI) will be applied for this employee."
    )
    esi_no = fields.Char(
        string='ESI Insurance Number',
        groups="hr.group_hr_user",
        help='Employees State Insurance (ESI) IP / Insurance Number (India)'
    )
    pf_uan_no = fields.Char(
        string='PF UAN Number',
        groups="hr.group_hr_user",
        help='Employees Provident Fund (EPF) Universal Account Number (UAN) (India)'
    )
    company_experience = fields.Char(
        string='Company Experience',
        compute='_compute_company_experience',
        groups="hr.group_hr_user",
        help='Employee experience inside the company calculated from their joining date.'
    )
    experience_in_months = fields.Integer(
        string='Experience (in months)',
        compute='_compute_experience_in_months',
        groups="hr.group_hr_user",
        help="Employee's experience inside the company in months, calculated on a month-wise basis."
    )

    @api.depends('joining_date')
    def _compute_company_experience(self):
        today = fields.Date.today()
        for rec in self:
            if rec.joining_date:
                diff = relativedelta(today, rec.joining_date)
                years = diff.years
                months = diff.months
                
                parts = []
                if years > 0:
                    parts.append(f"{years} Year{'s' if years > 1 else ''}")
                if months > 0 or not parts:
                    parts.append(f"{months} Month{'s' if months > 1 else ''}")
                rec.company_experience = ", ".join(parts)
            else:
                rec.company_experience = "N/A"

    @api.depends('joining_date')
    def _compute_experience_in_months(self):
        today = fields.Date.today()
        for rec in self:
            if rec.joining_date:
                diff = relativedelta(today, rec.joining_date)
                rec.experience_in_months = diff.years * 12 + diff.months
            else:
                rec.experience_in_months = 0

    def action_empty(self):
        return True

