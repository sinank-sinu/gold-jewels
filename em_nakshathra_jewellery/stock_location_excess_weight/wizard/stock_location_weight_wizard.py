# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockLocationWeightWizard(models.TransientModel):
    _name = 'stock.location.weight.wizard'
    _description = 'Record Physical Location Weight'

    location_id = fields.Many2one(
        'stock.location',
        string='Stock Location',
        required=True
    )
    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        related='location_id.branch_id',
        readonly=True
    )
    system_label_weight = fields.Float(
        string='Labels Gross Weight (g)',
        related='location_id.system_label_weight',
        readonly=True
    )
    system_quant_weight = fields.Float(
        string='Stock Quant Weight (g)',
        related='location_id.system_quant_weight',
        readonly=True
    )
    system_weight = fields.Float(
        string='System Weight (g)',
        required=True,
        readonly=True
    )
    physical_weight = fields.Float(
        string='Physical Measured Weight (g)',
        digits=(16, 3),
        required=True
    )
    weight_tolerance = fields.Float(
        string='Tolerance (±g)',
        digits=(16, 3),
        default=0.0
    )
    difference_weight = fields.Float(
        string='Difference Weight (g)',
        compute='_compute_calculations',
        digits=(16, 3)
    )
    excess_weight = fields.Float(
        string='Excess Weight (g)',
        compute='_compute_calculations',
        digits=(16, 3)
    )
    shortage_weight = fields.Float(
        string='Shortage Weight (g)',
        compute='_compute_calculations',
        digits=(16, 3)
    )
    status = fields.Selection([
        ('balanced', 'Balanced (Matched)'),
        ('excess', 'Excess Weight (Surplus)'),
        ('shortage', 'Shortage Weight (Deficit)'),
    ], string='Status', compute='_compute_calculations')

    notes = fields.Text(string='Notes / Scale Identification')

    @api.onchange('location_id')
    def _onchange_location_id(self):
        if self.location_id:
            self.location_id.action_refresh_location_weights()
            self.system_weight = self.location_id.system_weight
            self.physical_weight = self.location_id.physical_weight or self.location_id.system_weight
            self.weight_tolerance = self.location_id.weight_tolerance

    @api.depends('physical_weight', 'system_weight', 'weight_tolerance')
    def _compute_calculations(self):
        for rec in self:
            diff = round((rec.physical_weight or 0.0) - (rec.system_weight or 0.0), 3)
            rec.difference_weight = diff
            tol = abs(rec.weight_tolerance or 0.0)

            if abs(diff) <= tol:
                rec.excess_weight = 0.0
                rec.shortage_weight = 0.0
                rec.status = 'balanced'
            elif diff > tol:
                rec.excess_weight = round(diff, 3)
                rec.shortage_weight = 0.0
                rec.status = 'excess'
            else:
                rec.excess_weight = 0.0
                rec.shortage_weight = round(abs(diff), 3)
                rec.status = 'shortage'

    def action_confirm(self):
        self.ensure_one()
        now = fields.Datetime.now()
        user = self.env.user

        # Create audit entry
        self.env['stock.location.weight.check'].create({
            'location_id': self.location_id.id,
            'date': now,
            'user_id': user.id,
            'system_weight': self.system_weight,
            'physical_weight': self.physical_weight,
            'difference_weight': self.difference_weight,
            'excess_weight': self.excess_weight,
            'shortage_weight': self.shortage_weight,
            'status': self.status,
            'notes': self.notes,
        })

        # Update location with context flag to prevent duplicate audit record
        self.location_id.with_context(skip_weight_audit=True).write({
            'physical_weight': self.physical_weight,
            'weight_tolerance': self.weight_tolerance,
            'last_weight_check_date': now,
            'last_weight_check_user_id': user.id,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Physical Weight Recorded'),
                'message': _('Weight verification for %s recorded successfully (Status: %s).') % (
                    self.location_id.display_name, dict(self._fields['status'].selection).get(self.status)
                ),
                'type': 'success',
                'sticky': False,
            }
        }
