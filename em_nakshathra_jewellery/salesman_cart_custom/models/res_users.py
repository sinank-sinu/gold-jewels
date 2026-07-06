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

    @api.constrains('salesman_location_id', 'groups_id')
    def _check_salesman_location(self):
        for user in self:
            if user.has_group('em_jewellery_management.group_jewellery_salesman') and not user.salesman_location_id:
                raise UserError(_("Salesman Tray/Location is mandatory for Salesman users."))