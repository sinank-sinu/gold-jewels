# -*- coding: utf-8 -*-
from odoo import models, fields

class SmsTemplate(models.Model):
    _inherit = 'sms.template'

    xpresssms_template_id = fields.Char(string='XpressSMS DLT Template ID')
