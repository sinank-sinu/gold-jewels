import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class MetalLedger(models.Model):
    _name = 'metal.ledger'
    _description = 'Metal Ledger'
    _order = 'date asc, id asc'

    date = fields.Date(string='Date', required=True, default=fields.Date.today)
    voucher_name = fields.Char(string='Voucher / Reference')
    transaction_type = fields.Selection([
        ('purchase', 'Purchase'),
        ('sale', 'Sale'),
    ], string='Transaction Type', required=True)

    metal_id = fields.Many2one('gold.purity', string='Metal / Purity', required=True)

    metal_fine = fields.Float(string='Metal Fine', digits=(16, 3))
    mc_fine = fields.Float(string='MC Fine', digits=(16, 3))
    fine_weight = fields.Float(string='Fine Weight', digits=(16, 3))

    stock_in = fields.Float(string='Stock In', digits=(16, 3))
    stock_out = fields.Float(string='Stock Out', digits=(16, 3))
    balance_weight = fields.Float(string='Balance Weight', digits=(16, 3), store=True)

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)
    picking_id = fields.Many2one('stock.picking', string='Picking', readonly=True)
    branch_id = fields.Many2one('res.branch', string='Branch', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True)


    def action_recompute_balances(self):
        """Recompute the running balance for ALL metal.ledger records ordered
        by date asc, id asc.  Uses a single bulk write to minimise DB IO."""
        records = self.search([], order='date asc, id asc')
        balance = 0.0
        updates = []
        for rec in records:
            balance = balance + rec.stock_in - rec.stock_out
            updates.append((rec.id, balance))

        _logger.info("Recomputing balances for %s records", len(updates))
        for rec_id, bal in updates:
            self.browse(rec_id).write({'balance_weight': bal})
        return True

    # ------------------------------------------------------------------
    # Override create / write / unlink so balances are always fresh
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.action_recompute_balances()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Only recompute if fields affecting balance changed
        trigger_fields = {'date', 'stock_in', 'stock_out', 'id'}
        if trigger_fields.intersection(vals.keys()):
            self.action_recompute_balances()
        return res

    def unlink(self):
        res = super().unlink()
        self.action_recompute_balances()
        return res
