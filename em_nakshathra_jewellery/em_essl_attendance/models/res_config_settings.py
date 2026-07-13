from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    essl_api_url = fields.Char(string='eSSL API URL', config_parameter='em_essl_attendance.api_url')
    essl_api_key = fields.Char(string='eSSL API Key', config_parameter='em_essl_attendance.api_key')
    essl_username = fields.Char(string='eSSL Username', config_parameter='em_essl_attendance.username', default='essl')
    essl_password = fields.Char(string='eSSL Password', config_parameter='em_essl_attendance.password', default='essl')
    essl_serial_number = fields.Char(string='eSSL Serial Number', config_parameter='em_essl_attendance.serial_number')
    essl_timezone = fields.Selection([
        ('Asia/Kolkata', 'Asia/Kolkata'),
        ('UTC', 'UTC')
    ], string='eSSL Timezone', config_parameter='em_essl_attendance.timezone', default='Asia/Kolkata')

