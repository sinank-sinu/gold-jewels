from odoo import models, fields, api


class ResPartnerInherit(models.Model):
    _inherit = 'res.partner'

    wedding_anniversary = fields.Date(string='Wedding Anniversary')
    birthday = fields.Date(string='Birthday')
    instagram_id = fields.Char(string='Instagram ID')

    @api.onchange('wedding_anniversary', 'birthday')
    def _onchange_dates_sync(self):
        """ Bidirectional synchronization of dates """
        if self.child_ids:
            for child in self.child_ids:
                child.update({
                    'wedding_anniversary': self.wedding_anniversary,
                })