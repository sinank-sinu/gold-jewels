# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ecommerce_api_enabled = fields.Boolean(
        string="eCommerce API Enabled",
        config_parameter="ecommerce_api.is_enabled",
        default=True,
        help="Turn ON to allow eCommerce API requests. Turn OFF to disable all eCommerce API requests."
    )
    ecommerce_api_disabled_message = fields.Char(
        string="Disabled Notice Message",
        config_parameter="ecommerce_api.disabled_message",
        default="eCommerce API is currently disabled for maintenance. Please try again later.",
        help="Message returned to external API clients when the API is disabled."
    )

    def set_values(self):
        super().set_values()
        control = self.env['ecommerce.api.control'].sudo().search([], limit=1)
        if control:
            control.write({
                'is_enabled': self.ecommerce_api_enabled,
                'disabled_message': self.ecommerce_api_disabled_message,
                'last_toggled_by': self.env.user.id,
                'last_toggled_date': fields.Datetime.now(),
            })
