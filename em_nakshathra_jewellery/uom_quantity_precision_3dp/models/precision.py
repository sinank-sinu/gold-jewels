from odoo import models, fields

class PurchaseOrderLine(models.Model):
    _inherit='purchase.order.line'
    product_qty=fields.Float(digits=(16,3))

class StockMove(models.Model):
    _inherit='stock.move'
    product_uom_qty=fields.Float(digits=(16,3))
    quantity=fields.Float(digits=(16,3))

class StockMoveLine(models.Model):
    _inherit='stock.move.line'
    quantity=fields.Float(digits=(16,3))
    quantity_product_uom=fields.Float(digits=(16,3))

class AccountMoveLine(models.Model):
    _inherit='account.move.line'
    quantity=fields.Float(digits=(16,3))
