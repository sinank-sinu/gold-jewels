# -*- coding: utf-8 -*-
from odoo import models, fields

class ResBranch(models.Model):
    _inherit = 'res.branch'

    essl_serial_number = fields.Char(string='eSSL Serial Number', tracking=True)
