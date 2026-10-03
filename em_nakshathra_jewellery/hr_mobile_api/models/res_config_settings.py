# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    scheme_api_enabled = fields.Boolean(
        string="Scheme API Enabled",
        help="Turn ON to allow Gold Scheme API requests. Turn OFF to disable all Scheme API endpoints."
    )
    scheme_api_disabled_message = fields.Char(
        string="Disabled Notice Message",
        default="Gold Scheme API is currently disabled for maintenance. Please try again later.",
        help="Message returned to external API clients when the Scheme API is disabled."
    )

    task_manager_api_enabled = fields.Boolean(
        string="Task Manager API Enabled",
        help="Turn ON to allow Task Manager API requests. Turn OFF to disable all Task Manager API endpoints."
    )
    task_manager_api_disabled_message = fields.Char(
        string="Task Manager Disabled Notice Message",
        default="Task Manager API is currently disabled for maintenance. Please try again later.",
        help="Message returned to external API clients when the Task Manager API is disabled."
    )

    hrms_api_enabled = fields.Boolean(
        string="HRMS API Enabled",
        help="Turn ON to allow HRMS API requests. Turn OFF to disable all HRMS API endpoints."
    )
    hrms_api_disabled_message = fields.Char(
        string="HRMS Disabled Notice Message",
        default="HRMS API is currently disabled for maintenance. Please try again later.",
        help="Message returned to external API clients when the HRMS API is disabled."
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICP = self.env['ir.config_parameter'].sudo()

        scheme_val = ICP.get_param('scheme_api.is_enabled', default='True')
        task_val = ICP.get_param('task_manager_api.is_enabled', default='True')
        hrms_val = ICP.get_param('hrms_api.is_enabled', default='True')

        res.update(
            scheme_api_enabled=str(scheme_val).strip().lower() not in ('false', '0', 'off', 'no'),
            scheme_api_disabled_message=ICP.get_param(
                'scheme_api.disabled_message',
                default="Gold Scheme API is currently disabled for maintenance. Please try again later."
            ),
            task_manager_api_enabled=str(task_val).strip().lower() not in ('false', '0', 'off', 'no'),
            task_manager_api_disabled_message=ICP.get_param(
                'task_manager_api.disabled_message',
                default="Task Manager API is currently disabled for maintenance. Please try again later."
            ),
            hrms_api_enabled=str(hrms_val).strip().lower() not in ('false', '0', 'off', 'no'),
            hrms_api_disabled_message=ICP.get_param(
                'hrms_api.disabled_message',
                default="HRMS API is currently disabled for maintenance. Please try again later."
            ),
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICP = self.env['ir.config_parameter'].sudo()

        # Always store as string 'True' or 'False' to prevent Odoo unlinking False boolean config params
        ICP.set_param('scheme_api.is_enabled', 'True' if self.scheme_api_enabled else 'False')
        ICP.set_param(
            'scheme_api.disabled_message',
            self.scheme_api_disabled_message or "Gold Scheme API is currently disabled for maintenance. Please try again later."
        )

        ICP.set_param('task_manager_api.is_enabled', 'True' if self.task_manager_api_enabled else 'False')
        ICP.set_param(
            'task_manager_api.disabled_message',
            self.task_manager_api_disabled_message or "Task Manager API is currently disabled for maintenance. Please try again later."
        )

        ICP.set_param('hrms_api.is_enabled', 'True' if self.hrms_api_enabled else 'False')
        ICP.set_param(
            'hrms_api.disabled_message',
            self.hrms_api_disabled_message or "HRMS API is currently disabled for maintenance. Please try again later."
        )

        control = self.env['scheme.api.control'].sudo().search([], limit=1)
        if control:
            control.write({
                'is_enabled': self.scheme_api_enabled,
                'disabled_message': self.scheme_api_disabled_message or "Gold Scheme API is currently disabled for maintenance. Please try again later.",
                'last_toggled_by': self.env.user.id,
                'last_toggled_date': fields.Datetime.now(),
            })
