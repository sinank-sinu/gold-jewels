from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    mol_est_id = fields.Char(
        string='Ministry of Labour Establishment ID',
        help='Employer Unique ID / Ministry of Human Resources & Emiratisation (MoHRE) Establishment ID'
    )
    cr_number = fields.Char(
        string='Commercial Registration (CR) Number',
        help='Company Commercial Registration Number (used in Oman, Bahrain)'
    )
    employer_civil_id = fields.Char(
        string='Employer Civil ID',
        help='Employer Civil ID (used in Kuwait)'
    )
    company_bank_code = fields.Char(
        string='Company Bank Code',
        help='Company Bank Routing or Clearing Agent ID'
    )
