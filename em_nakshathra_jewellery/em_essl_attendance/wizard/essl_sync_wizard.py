import pytz
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class EsslSyncWizard(models.TransientModel):
    _name = 'essl.sync.wizard'
    _description = 'eSSL Attendance Sync Wizard'

    from_date = fields.Datetime(string='From Date', required=True, default=fields.Datetime.now)
    to_date = fields.Datetime(string='To Date', required=True, default=fields.Datetime.now)

    def action_sync(self):
        self.ensure_one()
        if self.from_date > self.to_date:
            raise UserError(_("From Date cannot be later than To Date."))

        # Convert UTC datetimes to local timezone string format for eSSL API
        timezone_name = self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.timezone') or 'Asia/Kolkata'
        try:
            local_tz = pytz.timezone(timezone_name)
        except Exception:
            local_tz = pytz.timezone('Asia/Kolkata')
            
        # Odoo stores datetimes in UTC, convert them to the timezone of the device
        from_dt_local = pytz.utc.localize(self.from_date).astimezone(local_tz)
        to_dt_local = pytz.utc.localize(self.to_date).astimezone(local_tz)
        
        from_date_str = from_dt_local.strftime('%d-%m-%Y %H:%M:%S')
        to_date_str = to_dt_local.strftime('%d-%m-%Y %H:%M:%S')
        
        try:
            res = self.env['hr.attendance'].fetch_and_parse_essl_logs(
                from_date_str=from_date_str,
                to_date_str=to_date_str,
                do_sync=True
            )
            synced_count = res.get('synced_count', 0)
            
            # Return an action to view the attendances
            action = self.env["ir.actions.actions"]._for_xml_id("hr_attendance.hr_attendance_action")
            action['domain'] = [
                ('check_in', '>=', self.from_date),
                ('check_in', '<=', self.to_date)
            ]
            action['context'] = {'search_default_today': 0}
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Complete'),
                    'message': _('Successfully synced %s attendance records.') % synced_count,
                    'type': 'success',
                    'sticky': False,
                    'next': action,
                }
            }
        except Exception as e:
            raise UserError(_("Failed to sync attendance: %s") % str(e))
