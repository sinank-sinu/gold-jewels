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

    
    @api.onchange('phone')
    def _onchange_phone_autofill(self):
        if self.phone:
            # Search for an existing partner with the same phone number
            partner = self.env['res.partner'].search([('phone', '=', self.phone)], limit=1)
            if partner and partner.id != getattr(self, '_origin', self).id:
                self.name = partner.name
                self.email = partner.email
                self.mobile = partner.mobile
                self.street = partner.street
                self.street2 = partner.street2
                self.city = partner.city
                self.zip = partner.zip
                self.state_id = partner.state_id
                self.country_id = partner.country_id
                self.vat = partner.vat
                # Notify the user that details were autofilled
                return {
                    'warning': {
                        'title': 'Contact Found',
                        'message': f'An existing contact ({partner.name}) was found with this phone number. The form has been autofilled.'
                    }
                }
