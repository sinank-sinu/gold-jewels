# -*- coding: utf-8 -*-
from odoo import fields, models


class PoPurityUpdateLog(models.Model):
    """One row per purity-update attempt (PO line or Vendor Bill line),
    success or failure, so every run leaves a permanent, browsable audit
    trail instead of only a message on the result web page / server log."""
    _name = 'po.purity.update.log'
    _description = 'PO Purity Update Log'
    _order = 'create_date desc, id desc'
    _rec_name = 'sales_voucher_no'

    sales_voucher_no = fields.Char(string='Sales Voucher No', index=True)
    purchase_voucher_no = fields.Char(string='Purchase Voucher No')
    row_number = fields.Integer(string='Excel Row #')

    target = fields.Selection(
        [('po_line', 'Purchase Order Line'), ('bill_line', 'Vendor Bill Line')],
        string='Target', required=True, index=True)
    status = fields.Selection(
        [('success', 'Updated'), ('failed', 'Failed')],
        string='Status', required=True, index=True)

    purity_value = fields.Float(string='Purity Value', digits=(16, 3))
    message = fields.Char(string='Detail / Reason')

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order')
    purchase_order_line_id = fields.Many2one('purchase.order.line', string='PO Line')
    vendor_bill_id = fields.Many2one('account.move', string='Vendor Bill')
    vendor_bill_line_id = fields.Many2one('account.move.line', string='Vendor Bill Line')

    upload_user_id = fields.Many2one(
        'res.users', string='Uploaded By', default=lambda self: self.env.user)
