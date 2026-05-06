from odoo import models, fields, api

class RefineryMarginReport(models.Model):
    _name = 'refinery.margin.report'
    _description = 'Refinery Margin Report'
    _order = 'date asc, id asc'

    date = fields.Date(string='Date', default=fields.Date.today)
    issue_id = fields.Many2one('old.gold.refinery.issue', string='Refinery Issue')
    name = fields.Char(string='Refinery Report Name', related='issue_id.name', store=True)
    type = fields.Selection([('issue', 'Issue'), ('receive', 'Receive')], string='Type', default='issue')
    batches = fields.Char(string='Batches')
    partner_id = fields.Many2one('res.partner', string="Partner")
    amount = fields.Float(string='Amount', digits=(16, 2))
    gross_weight = fields.Float(string='Gross Weight', digits=(16, 3))
    net_weight = fields.Float(string='Net Weight', digits=(16, 3))
    purity_id = fields.Many2one('gold.purity', string='Purity')
    expected_fine = fields.Float(string='Expected Fine', digits=(16, 3))
    melting_loss = fields.Float(string='Melting Loss', digits=(16, 3))
    lab_weight = fields.Float(string='Lab Weight', digits=(16, 3))
    refinery_issue_weight = fields.Float(string='Refinery Issue Weight', digits=(16, 3))
    scrap_bar_fine_weight = fields.Float(string='Scrap Bar Fine Weight', digits=(16, 3))
    total_fine_weight = fields.Float(string='Total Fine Weight', digits=(16, 3))
    balance = fields.Float(string='Balance', digits=(16, 3), store=True)
    fine_rate = fields.Float(string='Fine Rate', digits=(16, 2))

    def action_recompute_balances(self):
        """Recompute the running balance for Refinery Margin Report GLOBALLY."""
        records = self.search([], order='date asc, id asc')
        current_balance = 0.0
        for rec in records:
            # -Issue (expected_fine) +Receive (total_fine_weight)
            if rec.type == 'issue':
                current_balance -= rec.expected_fine
            elif rec.type == 'receive':
                current_balance += rec.total_fine_weight
            rec.write({'balance': current_balance})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.action_recompute_balances()
        return records

    def write(self, vals):
        res = super().write(vals)
        trigger_fields = {'date', 'expected_fine', 'total_fine_weight', 'type'}
        if trigger_fields.intersection(vals.keys()):
            self.action_recompute_balances()
        return res

    def unlink(self):
        res = super().unlink()
        self.action_recompute_balances()
        return res
