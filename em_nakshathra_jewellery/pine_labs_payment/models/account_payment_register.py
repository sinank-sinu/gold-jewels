# -*- coding: utf-8 -*-
from odoo import api, fields, models
import logging
_logger = logging.getLogger(__name__)

print("================ LOADING ACCOUNT PAYMENT REGISTER OVERRIDE ================")

class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    is_pine_labs_payment = fields.Boolean(string="Is Pine Labs Payment", default=False)
    pine_labs_amount = fields.Float(string="Pine Labs Amount")

    @api.depends('source_amount', 'source_amount_currency', 'source_currency_id', 'company_id', 'currency_id', 'payment_date')
    def _compute_amount(self):
        super()._compute_amount()
        for wizard in self:
            if wizard.is_pine_labs_payment:
                wizard.amount = wizard.pine_labs_amount
                _logger.info("SET AMOUNT TO %s", wizard.amount)
