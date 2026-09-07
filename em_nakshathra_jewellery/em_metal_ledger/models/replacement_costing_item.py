from odoo import models, fields, api
import datetime
from collections import defaultdict

class ReplacementCostingItem(models.Model):
    _name = 'replacement.costing.item'
    _description = 'Replacement Costing Item Wise'
    _order = 'sale_date desc'

    date = fields.Date(string="Date")
    sale_order_id = fields.Many2one('sale.order', string="Sale Order")
    sale_date = fields.Date(string="Sale Date", compute="_compute_sale_date", store=True)

    @api.depends('sale_order_id', 'sale_order_id.date_order', 'sales_voucher_name', 'date')
    def _compute_sale_date(self):
        for rec in self:
            so = rec.sale_order_id
            if not so and rec.sales_voucher_name:
                so = self.env['sale.order'].sudo().search([('name', '=', rec.sales_voucher_name)], limit=1)
                if so:
                    rec.sale_order_id = so
            if so and so.date_order:
                rec.sale_date = so.date_order.date()
            else:
                rec.sale_date = rec.date or fields.Date.today()
    salesman_id = fields.Many2one('res.users', string="Salesman")
    sales_voucher_name = fields.Char(string="Voucher")
    label_id = fields.Many2one('product.label', string="Label")
    product_id = fields.Many2one(
        'product.product',
        string="Product Name"
    )
    # product_id = fields.Many2one('product.product', related='label_id.product_id', string="Product Name", store=True)
    purity_id = fields.Many2one('gold.purity', string="Caret")
    purity = fields.Float(string="Purity", compute="_compute_all_fields", store=True)
    
    pcs_from_sale = fields.Float(string="PCS")
    
    gross_weight_purchase = fields.Float(string="PO GW (g)", digits=(16, 3))
    net_weight_purchase = fields.Float(string="PO NW (g)", digits=(16, 3))
    diamond_weight_purchase = fields.Float(string="PO Dia Wt (g)", digits=(16, 3))
    stone_weight_purchase = fields.Float(string="PO Stone Wt (g)", digits=(16, 3))
    
    purchase_making_charge_type = fields.Selection([
        ('percent', 'Percentage'),
        ('amount', 'Amount'),
        ('rate_per_gram', 'Rate per Gram'),
    ], string="PO MC Type")
    purchase_mc_percent_fine = fields.Float(string="PO MC %")
    purchase_mc_amount = fields.Float(string="PO MC Amount")
    purchase_metal_rate = fields.Float(string="PO Metal Rate")
    diamond_amount_purchase = fields.Float(string="PO Dia Amt")
    stone_amount_purchase = fields.Float(string="PO Stone Amt")
    purchase_mc_fine = fields.Float(string="PO MC Fine", digits=(16, 3))
    
    rate_fine_next_day_1pm = fields.Float(string="Next Day 1PM Rate")
    
    sale_metal_rate_manual = fields.Float(string="Sale Metal Rate")
    
    metal_amount_sale = fields.Float(string="Sale Metal Amt")
    mc_amount_sale = fields.Float(string="Sale MC Amt")
    diamond_amount_sale = fields.Float(string="Sale Dia Amt")
    stone_amount_sale = fields.Float(string="Sale Stone Amt")

    branch_id = fields.Many2one('res.branch', string="Branch")

    # Computed fields
    metal_qty_on_fine = fields.Float(string="Metal Qty On Fine", compute="_compute_all_fields", store=True, digits=(16, 3))
    metal_amount_purchase = fields.Float(string="PO Metal Amt", compute="_compute_all_fields", store=True)
    purchase_mc_on_fine_qty = fields.Float(string="PO MC On Fine Qty", compute="_compute_all_fields", store=True, digits=(16, 3))
    purchase_mc_value = fields.Float(string="PO MC Value", compute="_compute_all_fields", store=True)
    taxable_amount_purchase = fields.Float(string="PO Taxable Amt", compute="_compute_all_fields", store=True)
    purchase_metal_amount_on_fine = fields.Float(string="PO Metal Amt On Fine", compute="_compute_all_fields", store=True)
    purchase_mc_amount_on_fine = fields.Float(string="PO MC Amt On Fine", compute="_compute_all_fields", store=True)
    sale_mc_percent = fields.Float(string="Sale MC %", store=True)
    sale_taxable_amount = fields.Float(string="Sale Taxable Amt", compute="_compute_all_fields", store=True)
    metal_profit = fields.Float(string="Metal Profit", compute="_compute_all_fields", store=True)
    mc_profit = fields.Float(string="MC Profit", compute="_compute_all_fields", store=True)
    diamond_profit = fields.Float(string="Diamond Profit", compute="_compute_all_fields", store=True)
    stone_profit = fields.Float(string="Stone Profit", compute="_compute_all_fields", store=True)
    total_gp = fields.Float(string="Total GP", compute="_compute_all_fields", store=True)

    @api.depends('net_weight_purchase', 'purity_id', 'purchase_metal_rate', 'purchase_mc_percent_fine',
                 'purchase_making_charge_type', 'purchase_mc_amount',
                 'diamond_amount_purchase', 'stone_amount_purchase', 'rate_fine_next_day_1pm',
                 'metal_amount_sale', 'mc_amount_sale', 'diamond_amount_sale', 'stone_amount_sale')
    def _compute_all_fields(self):
        for rec in self:
            purity_pct = rec.purity_id.percentage / 100.0 if rec.purity_id and rec.purity_id.percentage else 0.0
            rec.purity = purity_pct
            rec.metal_qty_on_fine = rec.net_weight_purchase * purity_pct
            rec.metal_amount_purchase = rec.metal_qty_on_fine * rec.purchase_metal_rate
            
            # Purchase MC on fine qty: net weight * purchase mc percent
            if rec.purchase_making_charge_type == 'percent':
                rec.purchase_mc_on_fine_qty = rec.net_weight_purchase * (rec.purchase_mc_percent_fine / 100.0)
                rec.purchase_mc_value = rec.purchase_mc_on_fine_qty * rec.purchase_metal_rate

            else:  # amount or rate_per_gram
                rec.purchase_mc_on_fine_qty = 0.0
                rec.purchase_mc_value = rec.purchase_mc_amount
            # rec.purchase_mc_on_fine_qty = rec.net_weight_purchase * (rec.purchase_mc_percent_fine / 100.0)
            # rec.purchase_mc_value = rec.purchase_mc_on_fine_qty * rec.purchase_metal_rate
            
            rec.taxable_amount_purchase = rec.metal_amount_purchase + rec.purchase_mc_value + rec.diamond_amount_purchase + rec.stone_amount_purchase
            
            rec.purchase_metal_amount_on_fine = rec.rate_fine_next_day_1pm * rec.metal_qty_on_fine
            if rec.purchase_making_charge_type in ('amount', 'rate_per_gram'):
                rec.purchase_mc_amount_on_fine = rec.purchase_mc_value
            else:
                rec.purchase_mc_amount_on_fine = rec.purchase_mc_on_fine_qty * rec.rate_fine_next_day_1pm

            # rec.sale_mc_percent = (rec.mc_amount_sale / rec.metal_amount_sale * 100.0) if rec.metal_amount_sale else 0.0
            rec.sale_taxable_amount = rec.metal_amount_sale + rec.mc_amount_sale + rec.diamond_amount_sale + rec.stone_amount_sale
            
            rec.metal_profit = rec.metal_amount_sale - rec.purchase_metal_amount_on_fine
            rec.mc_profit = rec.mc_amount_sale - rec.purchase_mc_amount_on_fine
            rec.diamond_profit = rec.diamond_amount_sale - rec.diamond_amount_purchase
            rec.stone_profit = rec.stone_amount_sale - rec.stone_amount_purchase
            rec.total_gp = rec.metal_profit + rec.mc_profit + rec.diamond_profit + rec.stone_profit

    def _update_rates_next_day_1pm(self):
        """Update rate_fine_next_day_1pm based on sale_date + 1 day efficiently in bulk."""
        all_sale_dates = {rec.sale_date or rec.date for rec in self if (rec.sale_date or rec.date)}
        if not all_sale_dates:
            return

        date_map = {}
        for sale_dt in all_sale_dates:
            next_day = sale_dt + datetime.timedelta(days=1)
            rate_master = self.env['fine.rate.master'].sudo().search([('date', '=', next_day)], limit=1)
            if not rate_master:
                rate_master = self.env['fine.rate.master'].sudo().search([('date', '<=', next_day)], order='date desc', limit=1)
            history = self.env['fine.rate.history'].sudo().search([
                ('master_id', '=', rate_master.id),
                ('fine_rate', '>', 0)
            ], order='update_datetime desc', limit=1) if rate_master else False
            rate = 0.0
            if history and history.fine_rate:
                rate = history.fine_rate
            elif rate_master and rate_master.fine_rate:
                rate = rate_master.fine_rate
            date_map[sale_dt] = rate

        to_update = defaultdict(list)
        for rec in self:
            s_dt = rec.sale_date or rec.date
            rate = date_map.get(s_dt, 0.0)
            if rate and rec.rate_fine_next_day_1pm != rate:
                to_update[rate].append(rec.id)

        for rate, ids in to_update.items():
            self.browse(ids).write({'rate_fine_next_day_1pm': rate})

    def _update_vault_po_details(self):
        """For vault items, populate purchase fields from the latest Purchase Order of the product and weight fields from Sale Order line."""
        for item in self:
            is_vault = item.product_id and (
                getattr(item.product_id, 'is_vault_item', False) or
                getattr(item.product_id.product_tmpl_id, 'is_vault_item', False)
            )
            if is_vault and item.product_id:
                so_line = False
                if item.sale_order_id:
                    if item.label_id:
                        so_line = item.sale_order_id.order_line.filtered(lambda l: l.label_id == item.label_id)[:1]
                    if not so_line and item.product_id:
                        so_line = item.sale_order_id.order_line.filtered(lambda l: l.product_id == item.product_id)[:1]

                gross_wt = item.gross_weight_purchase
                net_wt = item.net_weight_purchase
                dia_wt = item.diamond_weight_purchase
                stone_wt = item.stone_weight_purchase

                if so_line:
                    gross_wt = getattr(so_line, 'sale_gross_weight', 0.0) or so_line.product_uom_qty or 0.0
                    net_wt = so_line.net_weight or 0.0
                    dia_wt = getattr(so_line, 'sale_diamond_weight_gm', 0.0)
                    stone_wt = getattr(so_line, 'sale_stone_weight', 0.0)

                po_line = self.env['purchase.order.line'].sudo().search([
                    ('product_id', '=', item.product_id.id),
                    ('order_id.state', 'in', ['purchase', 'done']),
                ], order='id desc', limit=1)

                sale_dt = item.sale_date or item.date or fields.Date.today()
                next_day_date = sale_dt + datetime.timedelta(days=1)
                rate_master = self.env['fine.rate.master'].sudo().search([('date', '=', next_day_date)], limit=1)
                if not rate_master:
                    rate_master = self.env['fine.rate.master'].sudo().search([('date', '<=', next_day_date)], order='date desc', limit=1)
                history = self.env['fine.rate.history'].sudo().search([
                    ('master_id', '=', rate_master.id),
                    ('fine_rate', '>', 0)
                ], order='update_datetime desc', limit=1) if rate_master else False

                rate_fine_next_day_1pm = 0.0
                if history and history.fine_rate:
                    rate_fine_next_day_1pm = history.fine_rate
                elif rate_master and rate_master.fine_rate:
                    rate_fine_next_day_1pm = rate_master.fine_rate

                mc_type = False
                mc_percent = 0.0
                if po_line:
                    mc_type = po_line.purchase_making_charge_type
                    mc_percent = po_line.mc_percent if mc_type == 'percent' else 0.0

                mc_fine = (net_wt * (mc_percent / 100.0)) if mc_type == 'percent' else 0.0

                item.write({
                    'gross_weight_purchase': gross_wt,
                    'net_weight_purchase': net_wt,
                    'diamond_weight_purchase': dia_wt,
                    'stone_weight_purchase': stone_wt,
                    'purchase_making_charge_type': mc_type,
                    'purchase_mc_percent_fine': mc_percent,
                    'purchase_mc_amount': 0.0,
                    'purchase_metal_rate': 0.0,
                    'diamond_amount_purchase': 0.0,
                    'stone_amount_purchase': 0.0,
                    'purchase_mc_fine': mc_fine,
                    'rate_fine_next_day_1pm': rate_fine_next_day_1pm,
                })