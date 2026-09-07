import logging
from collections import defaultdict
from odoo import models, fields

_logger = logging.getLogger(__name__)


class SaleOrderMetalLedger(models.Model):
    _inherit = 'sale.order'

    from_invoice = fields.Boolean(
        string="Created From Invoice",
        default=False,
    )

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            order._create_metal_ledger_on_confirm()
            order._create_replacement_costing_items()
        return res

    def _create_replacement_costing_items(self):
        ReplacementCostingItem = self.env['replacement.costing.item']
        FineRateHistory = self.env['fine.rate.history']
        # GoldRateUpdateLog = self.env['gold.rate.update.log']
        import datetime

        for order in self:
            po = order.purchase_order_id
            sale_dt = order.date_order.date() if order.date_order else fields.Date.today()
            next_day_date = sale_dt + datetime.timedelta(days=1)
            rate_master = self.env['fine.rate.master'].search([('date', '=', next_day_date)], limit=1)
            if not rate_master:
                rate_master = self.env['fine.rate.master'].search([('date', '<=', next_day_date)], order='date desc', limit=1)
            history = self.env['fine.rate.history'].search([
                ('master_id', '=', rate_master.id),
                ('fine_rate', '>', 0)
            ], order='update_datetime desc', limit=1) if rate_master else False

            rate_fine_next_day_1pm = 0.0
            if history and history.fine_rate:
                rate_fine_next_day_1pm = history.fine_rate
            elif rate_master and rate_master.fine_rate:
                rate_fine_next_day_1pm = rate_master.fine_rate

            for line in order.order_line:
                if not line.product_id:
                    continue

                is_vault = (
                    getattr(line.product_id, 'is_vault_item', False) or
                    getattr(line.product_id.product_tmpl_id, 'is_vault_item', False)
                )

                if line.label_id and not is_vault:
                    label = line.label_id
                    po_ref = label.purchase_id

                    ReplacementCostingItem.create({
                        'sale_order_id': order.id,
                        'date': order.date_order.date() if order.date_order else fields.Date.today(),
                        'branch_id': order.branch_id.id if hasattr(order, 'branch_id') else False,
                        'salesman_id': order.user_id.id,
                        'sales_voucher_name': order.name,
                        'label_id': label.id,
                        'purity_id': label.purity_id.id,
                        'pcs_from_sale': 1,
                        'product_id': label.product_id.id,
                        'gross_weight_purchase': label.purchase_gross_weight,
                        'net_weight_purchase': label.purchase_net_weight,
                        'diamond_weight_purchase': label.purchase_diamond_weight_gm,
                        'stone_weight_purchase': label.purchase_stone_weight,
                        'purchase_making_charge_type': label.purchase_making_charge_type,
                        'purchase_mc_percent_fine': (
                            label.purchase_making_charge_value
                            if label.purchase_making_charge_type == 'percent'
                            else 0.0
                        ),
                        'purchase_mc_amount': (
                            label.purchase_making_charge_amount
                            if label.purchase_making_charge_type in ('amount', 'rate_per_gram')
                            else 0.0
                        ),
                        'purchase_metal_rate': label.purchase_price_per_gram,
                        'diamond_amount_purchase': label.purchase_diamond_rate,
                        'stone_amount_purchase': label.purchase_stone_rate,
                        'purchase_mc_fine': label.mc_fine,
                        'rate_fine_next_day_1pm': rate_fine_next_day_1pm,
                        'sale_metal_rate_manual': line.gold_rate,
                        'sale_mc_percent': line.mc_percent_actual,
                        'metal_amount_sale': line.metal_amount,
                        'mc_amount_sale': line.mc_amount_actual,
                        'diamond_amount_sale': label.sale_diamond_rate,
                        'stone_amount_sale': label.sale_stone_rate,
                    })
                else:
                    po_line = self.env['purchase.order.line'].search([
                        ('product_id', '=', line.product_id.id),
                        ('order_id.state', 'in', ['purchase', 'done']),
                    ], order='id desc', limit=1)
                   
                    po_ref = po_line.order_id if po_line else False

                    _logger.info(
                        "Product=%s (Is Vault=%s), Latest PO=%s",
                        line.product_id.display_name,
                        is_vault,
                        po_ref.name if po_ref else False
                    )

                    net_wt = line.net_weight or 0.0
                    mc_type = po_line.purchase_making_charge_type if po_line else False
                    mc_percent = po_line.mc_percent if po_line and mc_type == 'percent' else 0.0
                    mc_amount = 0.0 if is_vault else (
                        (po_line.rate_value * net_wt) if po_line and mc_type == 'rate_per_gram'
                        else po_line.mc_amount if po_line and mc_type == 'amount'
                        else 0.0
                    )
                    mc_fine = (net_wt * (po_line.mc_percent / 100.0)) if po_line and mc_type == 'percent' else 0.0

                    ReplacementCostingItem.create({
                        'sale_order_id': order.id,
                        'date': order.date_order.date() if order.date_order else fields.Date.today(),
                        'branch_id': order.branch_id.id if hasattr(order, 'branch_id') else False,
                        'salesman_id': order.user_id.id,
                        'sales_voucher_name': order.name,
                        'label_id': line.label_id.id if line.label_id else False,
                        'product_id': line.product_id.id,
                        'purity_id': line.purity_id.id if line.purity_id else (po_line.purity_id.id if po_line and po_line.purity_id else False),
                        'pcs_from_sale': line.product_uom_qty or 1,
                        'gross_weight_purchase': getattr(line, 'sale_gross_weight', 0.0) or line.product_uom_qty or 0.0,
                        'net_weight_purchase': line.net_weight or 0.0,
                        'diamond_weight_purchase': getattr(line, 'sale_diamond_weight_gm', 0.0),
                        'stone_weight_purchase': getattr(line, 'sale_stone_weight', 0.0),
                        'purchase_making_charge_type': mc_type,
                        'purchase_mc_percent_fine': mc_percent,
                        'purchase_mc_amount': mc_amount,
                        'purchase_metal_rate': 0.0 if is_vault else (po_line.gold_rate if po_line else 0.0),
                        'diamond_amount_purchase': 0.0 if is_vault else (po_line.diamond_rate if po_line else 0.0),
                        'stone_amount_purchase': 0.0 if is_vault else (po_line.stone_rate if po_line else 0.0),
                        'purchase_mc_fine': mc_fine,
                        'rate_fine_next_day_1pm': rate_fine_next_day_1pm,
                        'sale_metal_rate_manual': line.gold_rate,
                        'sale_mc_percent': line.mc_percent_actual,
                        'metal_amount_sale': line.metal_amount,
                        'mc_amount_sale': line.mc_amount_actual,
                        'diamond_amount_sale': line.sale_diamond_rate if hasattr(line, 'sale_diamond_rate') and line.sale_diamond_rate else (line.label_id.sale_diamond_rate if line.label_id else 0.0),
                        'stone_amount_sale': line.sale_stone_rate if hasattr(line, 'sale_stone_rate') and line.sale_stone_rate else (line.label_id.sale_stone_rate if line.label_id else 0.0),
                    })

    def _create_metal_ledger_on_confirm(self):
        """
        Create metal ledger entries when SO is confirmed.

        Purchase Order -> Sale Order:
            - Purchase Entry
            - Sale Entry

        Invoice -> Sale Order:
            - Sale Entry only
        """
        self.ensure_one()

        po = self.purchase_order_id

        if self.origin and not self.unfix:
            return
        # Skip only if linked PO is old gold
        if po and po.is_old_gold:
            return

        MetalLedger = self.env['metal.ledger']

        # ---------------------------------------------------------
        # 1. Create PURCHASE Ledger Entries (ONLY if PO exists)
        # ---------------------------------------------------------
        # if po:
        if po and not self.from_invoice:
            existing_purchase = MetalLedger.search_count([
                ('purchase_order_id', '=', po.id),
                ('sale_order_id', '=', self.id),
                ('transaction_type', '=', 'purchase'),
            ])

            if not existing_purchase:
                purity_data_po = defaultdict(
                    lambda: {
                        'metal_fine': 0.0,
                        'mc_fine': 0.0,
                        'gross_weight': 0.0,
                    }
                )

                for line in po.order_line:
                    purity = line.purity_id
                    if not purity:
                        continue

                    fine = line.fine_weight or 0.0
                    mc = line.mc_fine or 0.0
                    gross = line.gross_weight or line.qty_received or 0.0

                    purity_data_po[purity]['metal_fine'] += fine
                    purity_data_po[purity]['mc_fine'] += mc
                    purity_data_po[purity]['gross_weight'] += gross

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
                        'stock_in': total_fine,
                        'stock_out': 0.0,
                        'purchase_order_id': po.id,
                        'sale_order_id': self.id,
                        'partner_id': po.partner_id.id,
                        'branch_id': self.branch_id.id if self.branch_id else False,
                    })

                    _logger.info(
                        "Created purchase metal ledger entry for SO %s / PO %s / Purity %s",
                        self.name,
                        po.name,
                        purity.name,
                    )
            else:
                _logger.info(
                    "Metal Ledger purchase entry already exists for PO %s / SO %s – skipping.",
                    po.name,
                    self.name,
                )

        # ---------------------------------------------------------
        # 2. Create SALE Ledger Entries (ALWAYS)
        # ---------------------------------------------------------
        existing_sale = MetalLedger.search_count([
            ('sale_order_id', '=', self.id),
            ('transaction_type', '=', 'sale'),
        ])

        if not existing_sale:
            purity_data_so = defaultdict(
                lambda: {
                    'metal_fine': 0.0,
                    'gross_weight': 0.0,
                }
            )

            for line in self.order_line:
                purity = line.purity_id
                if not purity:
                    continue

                metal_fine = line.fine_weight

                if not metal_fine and line.net_weight and line.purity_id.percentage:
                    metal_fine = (
                        line.net_weight *
                        (line.purity_id.percentage / 100.0)
                    )

                gross = line.sale_gross_weight or line.product_uom_qty or 0.0

                purity_data_so[purity]['metal_fine'] += (metal_fine or 0.0)
                purity_data_so[purity]['gross_weight'] += gross

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
                    'purchase_order_id': po.id if po else False,
                    'sale_order_id': self.id,
                    'partner_id': self.partner_id.id,
                    'branch_id': self.branch_id.id if self.branch_id else False,
                })

                _logger.info(
                    "Created sale metal ledger entry for SO %s / Purity %s",
                    self.name,
                    purity.name,
                )
        else:
            _logger.info(
                "Metal Ledger sale entry already exists for SO %s – skipping.",
                self.name,
            )

    # def _create_metal_ledger_on_confirm(self):
    #     """
    #     Create 'purchase' and 'sale' metal ledger entries when SO is confirmed,
    #     if:
    #       1. SO has a linked Purchase Order (purchase_order_id)
    #       2. That PO is NOT an old gold purchase (is_old_gold == False)
    #     """
    #     self.ensure_one()
    #     po = self.purchase_order_id
    #     if not po:
    #         return
    #     if po.is_old_gold:
    #         return

    #     MetalLedger = self.env['metal.ledger']

    #     # ---------------------------------------------------------
    #     # 1. Create PURCHASE Ledger Entries (from PO lines)
    #     # ---------------------------------------------------------
    #     existing_purchase = MetalLedger.search_count([
    #         ('purchase_order_id', '=', po.id),
    #         ('sale_order_id', '=', self.id),
    #         ('transaction_type', '=', 'purchase'),
    #     ])
    #     if not existing_purchase:
    #         purity_data_po = defaultdict(lambda: {'metal_fine': 0.0, 'mc_fine': 0.0, 'gross_weight': 0.0})
    #         for line in po.order_line:
    #             purity = line.purity_id
    #             if not purity:
    #                 continue
    #             fine = line.fine_weight or 0.0
    #             mc = line.mc_fine or 0.0
    #             gross = line.gross_weight or line.qty_received or 0.0
    #             purity_data_po[purity]['metal_fine'] += fine
    #             purity_data_po[purity]['mc_fine'] += mc

    #         for purity, vals in purity_data_po.items():
    #             total_fine = vals['metal_fine'] + vals['mc_fine']
    #             MetalLedger.create({
    #                 'date': fields.Date.today(),
    #                 'voucher_name': po.name,
    #                 'transaction_type': 'purchase',
    #                 'metal_id': purity.id,
    #                 'metal_fine': vals['metal_fine'],
    #                 'mc_fine': vals['mc_fine'],
    #                 'fine_weight': total_fine,
    #                 'stock_in': total_fine,
    #                 'stock_out': 0.0,
    #                 'purchase_order_id': po.id,
    #                 'sale_order_id': self.id,
    #                 'partner_id': po.partner_id.id,
    #                 'branch_id': self.branch_id.id if self.branch_id else False,
    #             })
    #             _logger.info("Created purchase metal ledger entry for SO %s / PO %s / Purity %s", self.name, po.name, purity.name)
    #     else:
    #         _logger.info("Metal Ledger purchase entry already exists for PO %s / SO %s – skipping.", po.name, self.name)

    #     # ---------------------------------------------------------
    #     # 2. Create SALE Ledger Entries (from SO lines)
    #     # ---------------------------------------------------------
    #     existing_sale = MetalLedger.search_count([
    #         ('sale_order_id', '=', self.id),
    #         ('transaction_type', '=', 'sale'),
    #     ])
    #     if not existing_sale:
    #         purity_data_so = defaultdict(lambda: {'metal_fine': 0.0, 'gross_weight': 0.0})
    #         for line in self.order_line:
    #             purity = line.purity_id
    #             if not purity:
    #                 continue
                
    #             # Use fine_weight from sale order line
    #             # If 0, try to compute from net_weight and purity percentage
    #             metal_fine = line.fine_weight
    #             if not metal_fine and line.net_weight and line.purity_id.percentage:
    #                 metal_fine = line.net_weight * (line.purity_id.percentage / 100.0)
                
    #             gross = line.sale_gross_weight or line.product_uom_qty or 0.0
    #             purity_data_so[purity]['metal_fine'] += (metal_fine or 0.0)

    #         for purity, vals in purity_data_so.items():
    #             MetalLedger.create({
    #                 'date': fields.Date.today(),
    #                 'voucher_name': self.name,
    #                 'transaction_type': 'sale',
    #                 'metal_id': purity.id,
    #                 'metal_fine': vals['metal_fine'],
    #                 'mc_fine': 0.0,
    #                 'fine_weight': vals['metal_fine'],
    #                 'stock_in': 0.0,
    #                 'stock_out': vals['metal_fine'],
    #                 'purchase_order_id': po.id,
    #                 'sale_order_id': self.id,
    #                 'partner_id': self.partner_id.id,
    #                 'branch_id': self.branch_id.id if self.branch_id else False,
    #             })
    #             _logger.info("Created sale metal ledger entry for SO %s / Purity %s", self.name, purity.name)
    #     else:
    #         _logger.info("Metal Ledger sale entry already exists for SO %s – skipping.", self.name)
