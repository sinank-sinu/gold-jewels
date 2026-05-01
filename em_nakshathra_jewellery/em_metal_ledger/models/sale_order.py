import logging
from collections import defaultdict
from odoo import models, fields

_logger = logging.getLogger(__name__)


class SaleOrderMetalLedger(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            order._create_metal_ledger_on_confirm()
            order._create_replacement_costing_items()
        return res

    def _create_replacement_costing_items(self):
        ReplacementCostingItem = self.env['replacement.costing.item']
        GoldRateUpdateLog = self.env['gold.rate.update.log']
        import datetime

        for order in self:
            for line in order.order_line:
                if line.label_id:
                    label = line.label_id
                    po = label.purchase_id
                    rate_fine_next_day_1pm = 0.0

                    if po and po.date_order:
                        # ensure po_date is a date object
                        po_date = po.date_order.date() if isinstance(po.date_order,
                                                                     datetime.datetime) else po.date_order
                        if po_date:
                            next_day_date = po_date + datetime.timedelta(days=1)
                            target_dt = datetime.datetime.combine(next_day_date, datetime.time(13, 0))
                            end_of_next_day = datetime.datetime.combine(next_day_date, datetime.time(23, 59, 59))

                            log = GoldRateUpdateLog.search([
                                ('rate_datetime', '>=', target_dt),
                                ('rate_datetime', '<=', end_of_next_day),
                                ('purity_id', '=', label.purity_id.id),
                            ], order='rate_datetime asc', limit=1)

                            if log:
                                rate_fine_next_day_1pm = log.rate_per_gram

                    ReplacementCostingItem.create({
                        'date': order.date_order.date() if order.date_order else fields.Date.today(),
                        'branch_id': order.branch_id.id if hasattr(order, 'branch_id') else False,
                        'salesman_id': order.user_id.id,
                        'sales_voucher_name': order.name,
                        'label_id': label.id,
                        'purity_id': label.purity_id.id,
                        'pcs_from_sale': 1,
                        # line.product_uom_qty,
                        'gross_weight_purchase': label.purchase_gross_weight,
                        'net_weight_purchase': label.purchase_net_weight,
                        'diamond_weight_purchase': label.purchase_diamond_weight_gm,
                        'stone_weight_purchase': label.purchase_stone_weight,

                        'purchase_mc_percent_fine': label.purchase_making_charge_value,
                        'purchase_metal_rate': label.purchase_price_per_gram,
                        'diamond_amount_purchase': label.purchase_diamond_rate,
                        'stone_amount_purchase': label.purchase_stone_rate,
                        'purchase_mc_fine': label.mc_fine,
                        'rate_fine_next_day_1pm': rate_fine_next_day_1pm,
                        'sale_metal_rate_manual': line.gold_rate,
                        'sale_mc_percent':line.mc_percent_actual,
                        'metal_amount_sale': line.metal_amount,
                        'mc_amount_sale': line.mc_amount_actual,
                        'diamond_amount_sale': label.sale_diamond_rate,
                        'stone_amount_sale': label.sale_stone_rate,
                    })

    def _create_metal_ledger_on_confirm(self):
        """
        Create 'purchase' and 'sale' metal ledger entries when SO is confirmed,
        if:
          1. SO has a linked Purchase Order (purchase_order_id)
          2. That PO is NOT an old gold purchase (is_old_gold == False)
        """
        self.ensure_one()
        po = self.purchase_order_id
        if not po:
            return
        if po.is_old_gold:
            return

        MetalLedger = self.env['metal.ledger']

        # ---------------------------------------------------------
        # 1. Create PURCHASE Ledger Entries (from PO lines)
        # ---------------------------------------------------------
        existing_purchase = MetalLedger.search_count([
            ('purchase_order_id', '=', po.id),
            ('sale_order_id', '=', self.id),
            ('transaction_type', '=', 'purchase'),
        ])
        if not existing_purchase:
            purity_data_po = defaultdict(lambda: {'metal_fine': 0.0, 'mc_fine': 0.0, 'gross_weight': 0.0})
            for line in po.order_line:
                purity = line.purity_id
                if not purity:
                    continue
                fine = line.fine_weight or 0.0
                mc = line.mc_fine or 0.0
                gross = line.gross_weight or line.qty_received or 0.0
                purity_data_po[purity]['metal_fine'] += fine
                purity_data_po[purity]['mc_fine'] += mc

            for purity, vals in purity_data_po.items():
                total_fine = vals['metal_fine'] + vals['mc_fine']
                MetalLedger.create({
                    'date': fields.Date.today(),
                    'voucher_name': po.name,
                    'transaction_type': 'purchase',
                    'metal_id': purity.id,
                    'metal_fine': vals['metal_fine'],
                    'mc_fine': vals['mc_fine'],
                    'fine_weight': total_fine,
                    'stock_in': vals['metal_fine'],
                    'stock_out': 0.0,
                    'purchase_order_id': po.id,
                    'sale_order_id': self.id,
                    'partner_id': po.partner_id.id,
                    'branch_id': self.branch_id.id if self.branch_id else False,
                })
                _logger.info("Created purchase metal ledger entry for SO %s / PO %s / Purity %s", self.name, po.name, purity.name)
        else:
            _logger.info("Metal Ledger purchase entry already exists for PO %s / SO %s – skipping.", po.name, self.name)

        # ---------------------------------------------------------
        # 2. Create SALE Ledger Entries (from SO lines)
        # ---------------------------------------------------------
        existing_sale = MetalLedger.search_count([
            ('sale_order_id', '=', self.id),
            ('transaction_type', '=', 'sale'),
        ])
        if not existing_sale:
            purity_data_so = defaultdict(lambda: {'metal_fine': 0.0, 'gross_weight': 0.0})
            for line in self.order_line:
                purity = line.purity_id
                if not purity:
                    continue
                
                # Use fine_weight from sale order line
                # If 0, try to compute from net_weight and purity percentage
                metal_fine = line.fine_weight
                if not metal_fine and line.net_weight and line.purity_id.percentage:
                    metal_fine = line.net_weight * (line.purity_id.percentage / 100.0)
                
                gross = line.sale_gross_weight or line.product_uom_qty or 0.0
                purity_data_so[purity]['metal_fine'] += (metal_fine or 0.0)

            for purity, vals in purity_data_so.items():
                MetalLedger.create({
                    'date': fields.Date.today(),
                    'voucher_name': self.name,
                    'transaction_type': 'sale',
                    'metal_id': purity.id,
                    'metal_fine': vals['metal_fine'],
                    'mc_fine': 0.0,
                    'fine_weight': vals['metal_fine'],
                    'stock_in': 0.0,
                    'stock_out': vals['metal_fine'],
                    'purchase_order_id': po.id,
                    'sale_order_id': self.id,
                    'partner_id': self.partner_id.id,
                    'branch_id': self.branch_id.id if self.branch_id else False,
                })
                _logger.info("Created sale metal ledger entry for SO %s / Purity %s", self.name, purity.name)
        else:
            _logger.info("Metal Ledger sale entry already exists for SO %s – skipping.", self.name)
