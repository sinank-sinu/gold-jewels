from odoo import models, fields, api

class RefineryLabReport(models.Model):
    _name = 'refinery.lab.report'
    _description = 'Refinery Lab Report'
    _order = 'date asc, id asc'

    date = fields.Date(string='Date', default=fields.Date.today)
    voucher_name = fields.Char(string='Voucher Name')
    type = fields.Selection([
        ('issue', 'Issue'),
        ('receive', 'Receive')
    ], string='Type')
    branch_id = fields.Many2one('res.branch', string='Branch')
    refinery_id = fields.Many2one('res.partner', string='Refinery')
    purity_id = fields.Many2one('gold.purity', string='Purity')
    issued_weight = fields.Float(string='Issued Weight', digits=(16, 3))
    net_weight = fields.Float(string='Net Weight', digits=(16, 3))
    lab_weight = fields.Float(string='Lab Weight', digits=(16, 3))
    lab_purity = fields.Float(string='Lab Purity (%)')
    lab_fine_weight = fields.Float(
        string='UPD Fine Weight',
        digits=(16, 3),
        compute='_compute_lab_fine_weight',
        store=True,
    )
    fine_weight = fields.Float(string='Fine Weight', digits=(16, 3))
    fine_amount = fields.Float(string='Fine Amount', digits=(16, 3))
    fine_gms_price = fields.Float(string='Fine GMS Price', digits=(16, 3))
    balance = fields.Float(string='Balance', digits=(16, 3), store=True)

    @api.depends('lab_weight', 'lab_purity','net_weight')
    def _compute_lab_fine_weight(self):
        for rec in self:
            rec.lab_fine_weight = rec.net_weight * (rec.lab_purity / 100.0) if rec.lab_purity else 0.0

    def action_recompute_balances(self):
        """Recompute the running balance for Refinery Lab Report GLOBALLY."""
        records = self.search([], order='date asc, id asc')
        balance = 0.0
        for rec in records:
            # Balance = Previous - Issue Weight + Receive Weight
            if rec.type == 'issue':
                balance -= rec.fine_weight
            elif rec.type == 'receive':
                balance += rec.fine_weight
            rec.write({'balance': balance})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.action_recompute_balances()
        return records

    def write(self, vals):
        res = super().write(vals)
        trigger_fields = {'date', 'fine_weight', 'type', 'lab_purity', 'lab_fine_weight'}
        if trigger_fields.intersection(vals.keys()):
            self.action_recompute_balances()
        return res

    def unlink(self):
        res = super().unlink()
        self.action_recompute_balances()
        return res
