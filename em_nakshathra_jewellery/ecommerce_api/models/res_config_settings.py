# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ecommerce_api_enabled = fields.Boolean(
        string="eCommerce API Enabled",
        help="Turn ON to allow eCommerce API requests. Turn OFF to disable all eCommerce API requests."
    )
    ecommerce_api_disabled_message = fields.Char(
        string="Disabled Notice Message",
        default="eCommerce API is currently disabled for maintenance. Please try again later.",
        help="Message returned to external API clients when the API is disabled."
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        val = ICP.get_param('ecommerce_api.is_enabled', default='True')
        is_enabled = str(val).strip().lower() not in ('false', '0', 'off', 'no')
        disabled_msg = ICP.get_param(
            'ecommerce_api.disabled_message',
            default="eCommerce API is currently disabled for maintenance. Please try again later."
        )
        res.update(
            ecommerce_api_enabled=is_enabled,
            ecommerce_api_disabled_message=disabled_msg,
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        # Always store as string 'True' or 'False' to prevent Odoo from unlinking False boolean config params
        ICP.set_param('ecommerce_api.is_enabled', 'True' if self.ecommerce_api_enabled else 'False')
        ICP.set_param(
            'ecommerce_api.disabled_message',
            self.ecommerce_api_disabled_message or "eCommerce API is currently disabled for maintenance. Please try again later."
        )

        control = self.env['ecommerce.api.control'].sudo().search([], limit=1)
        if control:
            control.write({
                'is_enabled': self.ecommerce_api_enabled,
                'disabled_message': self.ecommerce_api_disabled_message or "eCommerce API is currently disabled for maintenance. Please try again later.",
                'last_toggled_by': self.env.user.id,
                'last_toggled_date': fields.Datetime.now(),
            })
