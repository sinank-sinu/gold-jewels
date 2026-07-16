import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class ResUsers(models.Model):
    _inherit = 'res.users'

    login_otp = fields.Char(string='Login OTP', copy=False)
    login_otp_expiry = fields.Datetime(string='Login OTP Expiry', copy=False)
    is_otp_required = fields.Boolean(string='Is OTP Required', default=True)

    def _send_login_otp_sms(self, otp):
        self.ensure_one()
        mobile = self.partner_id.mobile or self.partner_id.phone
        if not mobile and hasattr(self, 'employee_id') and self.employee_id:
            mobile = self.employee_id.mobile_phone or self.employee_id.work_phone
        
        _logger.info("\n=== OTP LOGIN DEMO LOG ===")
        _logger.info("USER: %s", self.login)
        _logger.info("PHONE: %s", mobile)
        _logger.info("OTP CODE: %s", otp)
        _logger.info("==========================\n")
        
        if mobile:
            api_url = self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_api_url', 'https://api.xpresssms.in/api/v2/SendBulkSMS')
            api_key = self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_api_key', 'nUvKhbmpknZTeVr8WzjBKx180Qd6p/pQ6smsMv0e6Y8=')
            client_id = self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_client_id', 'fd4e0c95-91f6-40d1-80d0-eab5d913a4e3')
            sender_id = self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_sender_id', 'NAKGND')
            msg_template = self.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_message_template', '{otp} is your OTP to login to the NAKSHATHRA GOLD AND DIAMOND LLP application. OTP is valid for 1 minutes. Please do not share the OTP.')
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

            sent_via_xpress = False
            if api_key and client_id:
                formatted_mobile = normalize_phone(mobile)
                if formatted_mobile:
                    body = msg_template.format(otp=otp) if msg_template else _("Your verification code is %s. It is valid for 5 minutes.") % otp
                    payload = {
                        'SenderId': sender_id or 'NAKGND',
                        'templateId': otp_template_id or '1607100000000289598',
                        'principleEntityId': peid or '1601764169804801352',
                        'MessageParameters': [
                            {
                                'Number': formatted_mobile,
                                'Text': body
                            }
                        ],
                        'ApiKey': api_key,
                        'ClientId': client_id
                    }
                    _logger.info("Sending OTP via XpressSMS Bulk to %s with PEID %s and TemplateId %s", 
                                 formatted_mobile, peid, otp_template_id)
                    try:
                        import requests
                        response = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
                        if response.status_code == 200:
                            res_json = response.json()
                            if res_json.get('ErrorCode') == 0:
                                _logger.info("XpressSMS sent successfully. Response: %s", response.text)
                                sent_via_xpress = True
                                try:
                                    template = self.env.ref('em_otp_login.sms_template_otp', raise_if_not_found=False)
                                    sms_vals = {
                                        'number': mobile,
                                        'body': body,
                                        'partner_id': self.partner_id.id,
                                        'state': 'sent',
                                    }
                                    if template:
                                        sms_vals['template_id'] = template.id
                                    self.env['sms.sms'].sudo().create(sms_vals)
                                except Exception as db_err:
                                    _logger.warning("Failed to create sms.sms record: %s", db_err)
                            else:
                                _logger.error("XpressSMS API Error: %s, Description: %s", res_json.get('ErrorCode'), res_json.get('ErrorDescription'))
                        else:
                            _logger.error("XpressSMS HTTP Error: %s, Response: %s", response.status_code, response.text)
                    except Exception as api_err:
                        _logger.error("Failed to send OTP via XpressSMS: %s", api_err)

            if not sent_via_xpress:
                _logger.info("Falling back to default Odoo SMS gateway for OTP.")
                try:
                    template = self.env.ref('em_otp_login.sms_template_otp', raise_if_not_found=False)
                    if template:
                        body = template._render_field('body', [self.id], compute_lang=True)[self.id]
                    else:
                        body = _("Your verification code is %s. It is valid for 5 minutes.") % otp
                    
                    sms_vals = {
                        'number': mobile,
                        'body': body,
                        'partner_id': self.partner_id.id,
                    }
                    if template:
                        sms_vals['template_id'] = template.id
                    
                    sms_sms = self.env['sms.sms'].sudo().create(sms_vals)
                    sms_sms.send()
                except Exception as e:
                    _logger.warning("Could not create/send SMS via template: %s. OTP logged in console.", e)

        try:
            with open('/home/sinan/odoo/otp_debug.txt', 'w') as f:
                f.write(f"USER: {self.login}\nPHONE: {mobile}\nOTP CODE: {otp}\nSENT AT: {fields.Datetime.now()}\n")
        except Exception as e:
            _logger.warning("Could not write OTP to debug file: %s", e)


