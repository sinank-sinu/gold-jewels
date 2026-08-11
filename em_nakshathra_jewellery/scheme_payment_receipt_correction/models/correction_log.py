from odoo import api, fields, models

class SchemePaymentCorrectionLog(models.Model):
    _name = 'scheme.payment.correction.log'
    _description = 'Scheme Payment Correction Log'
    _order = 'processed_at desc'

    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    move_name = fields.Char(string='Move Name', readonly=True)
    scheme_payment_reference = fields.Char(string='Scheme Payment Reference', readonly=True)
    scheme_name = fields.Char(string='Scheme Name', readonly=True)
    journal_id = fields.Many2one('account.journal', string='Move Journal', readonly=True)
    payment_journal_id = fields.Many2one('account.journal', string='Payment Journal', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True)
    old_account_id = fields.Many2one('account.account', string='Old Account', readonly=True)
    new_account_id = fields.Many2one('account.account', string='New Account', readonly=True)
    amount = fields.Monetary(string='Amount', currency_field='currency_id', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    previous_state = fields.Char(string='Previous State', readonly=True)
    final_state = fields.Char(string='Final State', readonly=True)
    status = fields.Selection([
        ('corrected', 'Corrected'),
        ('already_correct', 'Already Correct'),
        ('missing_payment_journal', 'Missing Journal'),
        ('missing_outstanding_account', 'Missing Outstanding Account'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
    ], string='Status', readonly=True)
    error_message = fields.Text(string='Error Message', readonly=True)
    processed_at = fields.Datetime(string='Processed At', default=fields.Datetime.now, readonly=True)
