# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    xpresssms_api_url = fields.Char(
        string='XpressSMS API URL',
        default='https://api.xpresssms.in/api/v2/SendBulkSMS',
        config_parameter='em_otp_login.xpresssms_api_url'
    )
    xpresssms_api_key = fields.Char(
        string='XpressSMS API Key',
        default='nUvKhbmpknZTeVr8WzjBKx180Qd6p/pQ6smsMv0e6Y8=',
        config_parameter='em_otp_login.xpresssms_api_key'
    )
    xpresssms_client_id = fields.Char(
        string='XpressSMS Client ID',
        default='fd4e0c95-91f6-40d1-80d0-eab5d913a4e3',
        config_parameter='em_otp_login.xpresssms_client_id'
    )
    xpresssms_sender_id = fields.Char(
        string='XpressSMS Sender ID',
        default='NAKGND',
        config_parameter='em_otp_login.xpresssms_sender_id'
    )
    xpresssms_message_template = fields.Char(
        string='XpressSMS OTP Template',
        default='{otp} is your OTP to login to the NAKSHATHRA GOLD AND DIAMOND LLP application. OTP is valid for 5 minutes. Please do not share the OTP.',
        config_parameter='em_otp_login.xpresssms_message_template'
    )
    xpresssms_peid = fields.Char(
        string='XpressSMS PEID (Entity ID)',
        config_parameter='em_otp_login.xpresssms_peid'
    )
    xpresssms_otp_template_id = fields.Char(
        string='XpressSMS OTP DLT Template ID',
        config_parameter='em_otp_login.xpresssms_otp_template_id'
    )

