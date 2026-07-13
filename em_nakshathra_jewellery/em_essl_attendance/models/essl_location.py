# -*- coding: utf-8 -*-
from odoo import models, fields

class EsslLocation(models.Model):
    _name = 'essl.location'
    _description = 'eSSL Location'

    name = fields.Char(string='Location', required=True)
    serial_number = fields.Char(string='Serial Number', required=True)
    active = fields.Boolean(string='Active', default=True)
