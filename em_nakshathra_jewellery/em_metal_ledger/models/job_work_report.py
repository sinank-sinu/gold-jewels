from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class JobWorkReport(models.Model):
    _name = 'job.work.report'
    _description = 'Job Work Report'
    _order = 'date asc, id asc'

    date = fields.Date(string='Date', default=fields.Date.today, required=True)
    voucher_name = fields.Char(string='Voucher Name', required=True)
    type = fields.Selection([
        ('issue', 'Issue'),
        ('receive', 'Receive')
    ], string='Type', required=True)
    
    partner_id = fields.Many2one('res.partner', string='Job Worker')
    job_type = fields.Selection([
        ('gold_only', 'Gold Only'),
        ('gold_alloy', 'Gold + Alloy')
    ], string='Job Type')
    
    gross_weight = fields.Float(string='Gross Weight', digits=(16, 3))
    
    # Matching Metal Ledger field names
    stock_in = fields.Float(string='Fine Issue', digits=(16, 3))
    stock_out = fields.Float(string='Fine Receipt', digits=(16, 3))
    balance_weight = fields.Float(string='Balance', digits=(16, 3), store=True)
    
    purity_id = fields.Many2one('gold.purity', string='Purity')

    # ------------------------------------------------------------------
    # Running-balance helper (GLOBAL, exactly like Metal Ledger)
    # ------------------------------------------------------------------
    def action_recompute_balances(self):
        """Recompute the running balance for Job Work Report GLOBALLY."""
        records = self.search([], order='date asc, id asc')
        balance = 0.0
        for rec in records:
            # Balance = Previous - Issue + Receipt
            balance = balance - rec.stock_in + rec.stock_out
            rec.write({'balance_weight': balance})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.action_recompute_balances()
        return records

    def write(self, vals):
        res = super().write(vals)
        trigger_fields = {'date', 'stock_in', 'stock_out', 'type'}
        if trigger_fields.intersection(vals.keys()):
            self.action_recompute_balances()
        return res

    def unlink(self):
        res = super().unlink()
        self.action_recompute_balances()
        return res
