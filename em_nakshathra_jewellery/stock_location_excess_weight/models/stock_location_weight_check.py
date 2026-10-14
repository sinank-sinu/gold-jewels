# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class StockLocationWeightCheck(models.Model):
    _name = 'stock.location.weight.check'
    _description = 'Stock Location Weight Verification Audit'
    _order = 'date desc, id desc'

    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        required=True,
        ondelete='cascade',
        index=True
    )
    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        related='location_id.branch_id',
        store=True,
        readonly=True
    )
    date = fields.Datetime(
        string='Verification Date',
        default=fields.Datetime.now,
        required=True,
        index=True
    )
    user_id = fields.Many2one(
        'res.users',
        string='Verified By',
        default=lambda self: self.env.user,
        required=True
    )
    system_weight = fields.Float(
        string='System Weight (g)',
        digits=(16, 3),
        readonly=True
    )
    physical_weight = fields.Float(
        string='Physical Weight (g)',
        digits=(16, 3),
        required=True
    )
    difference_weight = fields.Float(
        string='Difference Weight (g)',
        digits=(16, 3),
        readonly=True
    )
    excess_weight = fields.Float(
        string='Excess Weight (g)',
        digits=(16, 3),
        readonly=True
    )
    shortage_weight = fields.Float(
        string='Shortage Weight (g)',
        digits=(16, 3),
        readonly=True
    )
    status = fields.Selection([
        ('unverified', 'Unverified'),
        ('balanced', 'Balanced (Matched)'),
        ('excess', 'Excess Weight (Surplus)'),
        ('shortage', 'Shortage Weight (Deficit)'),
    ], string='Status', readonly=True)

    notes = fields.Text(string='Verification Notes / Remarks')
