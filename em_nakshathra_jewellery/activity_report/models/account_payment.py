# -*- coding: utf-8 -*-

from odoo import models, fields, api


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    partner_phone = fields.Char(
        string='Phone',
        related='partner_id.phone',
        readonly=True,
        store=True
    )
