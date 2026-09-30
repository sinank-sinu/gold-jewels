# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SchemeApiControl(models.Model):
    _name = 'scheme.api.control'
    _description = 'Gold Scheme API Control'

    name = fields.Char(string="Name", default="Scheme API Control", required=True)
    is_enabled = fields.Boolean(
        string="Scheme API Enabled",
        default=True,
        help="Turn ON to allow Gold Scheme API requests. Turn OFF to disable/stop all Scheme API endpoints."
    )
    disabled_message = fields.Char(
        string="Disabled Notice Message",
        default="Gold Scheme API is currently disabled for maintenance. Please try again later.",
        help="Message returned to external API clients when the Scheme API is disabled."
    )
    status_badge = fields.Char(
        string="API Status",
        compute="_compute_status_badge"
    )
    last_toggled_by = fields.Many2one(
        'res.users',
        string="Last Modified By",
        readonly=True
    )
    last_toggled_date = fields.Datetime(
        string="Last Modified On",
        readonly=True
    )

    @api.depends('is_enabled')
    def _compute_status_badge(self):
        for rec in self:
            rec.status_badge = _("Online / Active") if rec.is_enabled else _("Offline / Disabled")

    def write(self, vals):
        if 'is_enabled' in vals:
            vals['last_toggled_by'] = self.env.user.id
            vals['last_toggled_date'] = fields.Datetime.now()
            self.env['ir.config_parameter'].sudo().set_param(
                'scheme_api.is_enabled',
                str(vals['is_enabled'])
            )
        if 'disabled_message' in vals:
            self.env['ir.config_parameter'].sudo().set_param(
                'scheme_api.disabled_message',
                vals['disabled_message'] or ''
            )
        return super().write(vals)

    def action_enable_api(self):
        """Turn Gold Scheme API ON."""
        self.ensure_one()
        self.write({'is_enabled': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Scheme API Enabled'),
                'message': _('The Gold Scheme API is now ACTIVE and accepting requests.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_disable_api(self):
        """Turn Gold Scheme API OFF."""
        self.ensure_one()
        self.write({'is_enabled': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Scheme API Disabled'),
                'message': _('The Gold Scheme API is now DISABLED. All incoming requests will be rejected.'),
                'type': 'danger',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_toggle_api(self):
        """Toggle API state between enabled and disabled."""
        self.ensure_one()
        if self.is_enabled:
            return self.action_disable_api()
        else:
            return self.action_enable_api()
