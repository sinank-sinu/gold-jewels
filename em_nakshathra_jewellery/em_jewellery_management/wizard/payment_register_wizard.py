from odoo import models, api, fields

class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'


    old_gold_price = fields.Monetary(string="Old Gold Price")
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        readonly=False,
        help="The payment's currency.")


    def _get_wizard_values_from_batch(self, batch_result):
        res = super()._get_wizard_values_from_batch(batch_result)

        moves = batch_result['lines'].mapped('move_id')
        move = moves[0]

        if move.old_gold_price:
            self.old_gold_price = move.old_gold_price
            self.amount = move.amount_residual
            # self.currency_id = move.currency_id.id

        return res
    # #
    # @api.depends('can_edit_wizard', 'source_amount', 'source_amount_currency', 'source_currency_id', 'company_id',
    #              'currency_id', 'payment_date')
    # def _compute_amount(self):
    #     res = super()._compute_amount()
    #     for wizard in self:
    #         if wizard.amount and wizard.old_gold_price:
    #             wizard.amount = wizard.amount-wizard.old_gold_price
    #


    @api.depends('can_edit_wizard', 'amount')
    def _compute_payment_difference(self):
        res = super()._compute_payment_difference()

        for wizard in self:
            if wizard.amount and wizard.old_gold_price:
                if wizard.can_edit_wizard and wizard.payment_date:
                    batch_result = wizard._get_batches()[0]
                    total_amount_residual_in_wizard_currency = wizard\
                        ._get_total_amount_in_wizard_currency_to_full_reconcile(batch_result, early_payment_discount=False)[0]
                    wizard.payment_difference = (total_amount_residual_in_wizard_currency-wizard.old_gold_price) - wizard.amount
            else:
                wizard.payment_difference = 0.0