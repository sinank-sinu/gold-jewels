# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class SmsSms(models.Model):
    _inherit = 'sms.sms'

    template_id = fields.Many2one('sms.template', string='SMS Template', readonly=True)
    xpresssms_template_id = fields.Char(
        string='XpressSMS DLT Template ID',
        compute='_compute_xpresssms_template_id',
        store=True,
        readonly=False
    )

    @api.depends('template_id')
    def _compute_xpresssms_template_id(self):
        for sms in self:
            if sms.template_id and sms.template_id.xpresssms_template_id:
                sms.xpresssms_template_id = sms.template_id.xpresssms_template_id
            else:
                sms.xpresssms_template_id = False

    def _send(self, unlink_failed=False, unlink_sent=True, raise_exception=False):
        """Override to route SMS through XpressSMS if configured."""
        api_url = self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_api_url', 'https://api.xpresssms.in/api/v2/SendBulkSMS')
        api_key = self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_api_key', 'nUvKhbmpknZTeVr8WzjBKx180Qd6p/pQ6smsMv0e6Y8=')
        client_id = self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_client_id', 'fd4e0c95-91f6-40d1-80d0-eab5d913a4e3')
        sender_id = self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_sender_id', 'NAKGND')

        api_key = (api_key or 'nUvKhbmpknZTeVr8WzjBKx180Qd6p/pQ6smsMv0e6Y8=').strip()
        client_id = (client_id or 'fd4e0c95-91f6-40d1-80d0-eab5d913a4e3').strip()

        if not (api_key and client_id):
            _logger.info("XpressSMS is not configured. Falling back to default Odoo SMS sending.")
            return super(SmsSms, self)._send(unlink_failed=unlink_failed, unlink_sent=unlink_sent, raise_exception=raise_exception)

        peid = (self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_peid') or '1601764169804801352').strip()
        otp_template_id = (self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_otp_template_id') or '1607100000000289598').strip()

        def normalize_phone(phone):
            if not phone:
                return False
            digits = ''.join(c for c in phone if c.isdigit())
            if len(digits) == 11 and digits.startswith('0'):
                digits = digits[1:]
            if len(digits) == 10:
                digits = '91' + digits
            return digits

        import requests
        for sms in self:
            if sms.state != 'outgoing' or sms.to_delete:
                continue
            
            formatted_mobile = normalize_phone(sms.number)
            if not formatted_mobile:
                _logger.error("SMS send failed: Invalid mobile number format '%s'", sms.number)
                sms.write({
                    'state': 'error',
                    'failure_type': 'sms_number_format',
                    'to_delete': unlink_failed
                })
                sms.sms_tracker_id._action_update_from_sms_state('error', failure_type='sms_number_format')
                continue

            dlt_template_id = (sms.xpresssms_template_id or '').strip()
            if not dlt_template_id:
                if 'verification code' in (sms.body or '').lower() or 'otp' in (sms.body or '').lower():
                    dlt_template_id = otp_template_id

            payload = {
                'SenderId': sender_id or 'NAKGND',
                'templateId': dlt_template_id or '1607100000000289598',
                'principleEntityId': peid or '1601764169804801352',
                'MessageParameters': [
                    {
                        'Number': formatted_mobile,
                        'Text': sms.body
                    }
                ],
                'ApiKey': api_key,
                'ClientId': client_id,
            }

            _logger.info("Routing SMS ID %s via XpressSMS Bulk to %s with PEID %s and TemplateId %s", 
                         sms.id, formatted_mobile, peid, dlt_template_id)
            try:
                response = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
                if response.status_code == 200:
                    res_json = response.json()
                    if res_json.get('ErrorCode') == 0:
                        _logger.info("XpressSMS sent successfully. Response: %s", response.text)
                        sms.write({
                            'state': 'pending',
                            'failure_type': False,
                            'to_delete': unlink_sent
                        })
                        sms.sms_tracker_id._action_update_from_sms_state('pending')
                    else:
                        _logger.error("XpressSMS API Error: %s, Description: %s", res_json.get('ErrorCode'), res_json.get('ErrorDescription'))
                        sms.write({
                            'state': 'error',
                            'failure_type': 'sms_server',
                            'to_delete': unlink_failed
                        })
                        sms.sms_tracker_id._action_update_from_sms_state('error', failure_type='sms_server')
                else:
                    _logger.error("XpressSMS HTTP Error: %s, Response: %s", response.status_code, response.text)
                    sms.write({
                        'state': 'error',
                        'failure_type': 'sms_server',
                        'to_delete': unlink_failed
                    })
                    sms.sms_tracker_id._action_update_from_sms_state('error', failure_type='sms_server')
            except Exception as api_err:
                _logger.error("Failed to send SMS via XpressSMS: %s", api_err)
                sms.write({
                    'state': 'error',
                    'failure_type': 'sms_server',
                    'to_delete': unlink_failed
                })
                sms.sms_tracker_id._action_update_from_sms_state('error', failure_type='sms_server')

            sms.mail_message_id._notify_message_notification_update()
