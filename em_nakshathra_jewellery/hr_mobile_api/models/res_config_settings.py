# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    scheme_api_enabled = fields.Boolean(
        string="Scheme API Enabled",
        config_parameter="scheme_api.is_enabled",
        default=True,
        help="Turn ON to allow Gold Scheme API requests. Turn OFF to disable all Scheme API endpoints."
    )
    scheme_api_disabled_message = fields.Char(
        string="Disabled Notice Message",
        config_parameter="scheme_api.disabled_message",
        default="Gold Scheme API is currently disabled for maintenance. Please try again later.",
        help="Message returned to external API clients when the Scheme API is disabled."
    )

    task_manager_api_enabled = fields.Boolean(
        string="Task Manager API Enabled",
        config_parameter="task_manager_api.is_enabled",
        default=True,
        help="Turn ON to allow Task Manager API requests. Turn OFF to disable all Task Manager API endpoints."
    )
    task_manager_api_disabled_message = fields.Char(
        string="Task Manager Disabled Notice Message",
        config_parameter="task_manager_api.disabled_message",
        default="Task Manager API is currently disabled for maintenance. Please try again later.",
        help="Message returned to external API clients when the Task Manager API is disabled."
    )

    hrms_api_enabled = fields.Boolean(
        string="HRMS API Enabled",
        config_parameter="hrms_api.is_enabled",
        default=True,
        help="Turn ON to allow HRMS API requests. Turn OFF to disable all HRMS API endpoints."
    )
    hrms_api_disabled_message = fields.Char(
        string="HRMS Disabled Notice Message",
        config_parameter="hrms_api.disabled_message",
        default="HRMS API is currently disabled for maintenance. Please try again later.",
        help="Message returned to external API clients when the HRMS API is disabled."
    )

    def set_values(self):
        super().set_values()
        control = self.env['scheme.api.control'].sudo().search([], limit=1)
        if control:
            control.write({
                'is_enabled': self.scheme_api_enabled,
                'disabled_message': self.scheme_api_disabled_message,
                'last_toggled_by': self.env.user.id,
                'last_toggled_date': fields.Datetime.now(),
            })
