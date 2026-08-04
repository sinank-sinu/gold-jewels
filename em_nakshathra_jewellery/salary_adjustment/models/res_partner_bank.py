from odoo import models, fields

class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    routing_code = fields.Char(
        string='Bank Routing / Agent ID Code',
        help='Bank Routing Code, Clearing Code, or Bank/Agent ID (required for WPS file structures)'
    )
