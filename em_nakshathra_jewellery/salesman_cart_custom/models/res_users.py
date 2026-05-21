from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta

class ResUsers(models.Model):
    _inherit = 'res.users'

    salesman_location_id = fields.Many2one(
        'stock.location', 
        string='Salesman Tray/Location',
        domain=[('usage', '=', 'internal')]
    )