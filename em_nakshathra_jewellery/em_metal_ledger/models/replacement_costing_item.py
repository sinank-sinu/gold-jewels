from odoo import models, fields, api
import datetime

class ReplacementCostingItem(models.Model):
    _name = 'replacement.costing.item'
    _description = 'Replacement Costing Item Wise'
    _order = 'date desc'

    date = fields.Date(string="Date", default=fields.Date.context_today)
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
            rec.purchase_mc_amount_on_fine = rec.purchase_mc_on_fine_qty * rec.rate_fine_next_day_1pm
            
            # rec.sale_mc_percent = (rec.mc_amount_sale / rec.metal_amount_sale * 100.0) if rec.metal_amount_sale else 0.0
            rec.sale_taxable_amount = rec.metal_amount_sale + rec.mc_amount_sale + rec.diamond_amount_sale + rec.stone_amount_sale
            
            rec.metal_profit = rec.metal_amount_sale - rec.purchase_metal_amount_on_fine
            rec.mc_profit = rec.mc_amount_sale - rec.purchase_mc_amount_on_fine
            rec.diamond_profit = rec.diamond_amount_sale - rec.diamond_amount_purchase
            rec.stone_profit = rec.stone_amount_sale - rec.stone_amount_purchase
            rec.total_gp = rec.metal_profit + rec.mc_profit + rec.diamond_profit + rec.stone_profit
