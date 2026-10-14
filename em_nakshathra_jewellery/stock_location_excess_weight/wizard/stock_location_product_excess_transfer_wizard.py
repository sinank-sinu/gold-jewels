# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class StockLocationProductExcessTransferWizard(models.TransientModel):
    _name = 'stock.location.product.excess.transfer.wizard'
    _description = 'Transfer Weight for Excess or Shortage'

    transfer_type = fields.Selection([
        ('outbound', 'Transfer Excess Out (From this Location to Another)'),
        ('inbound', 'Transfer Shortage In (From Another Location to this Needed Location)'),
    ], string='Transfer Type', default='outbound', required=True)

    location_id = fields.Many2one(
        'stock.location',
        string='Source Location',
        domain="[('usage', '=', 'internal')]"
    )
    branch_id = fields.Many2one(
        'res.branch',
        string='Source Branch',
        related='location_id.branch_id',
        readonly=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )
    location_dest_id = fields.Many2one(
        'stock.location',
        string='Destination / Needed Location',
        domain="[('usage', '!=', 'view')]"
    )
    dest_branch_id = fields.Many2one(
        'res.branch',
        string='Destination Branch',
        related='location_dest_id.branch_id',
        readonly=True
    )
    picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Operation Type'
    )
    notes = fields.Char(
        string='Transfer Notes / Reason'
    )
    line_ids = fields.One2many(
        'stock.location.product.excess.transfer.wizard.line',
        'wizard_id',
        string='Product Lines to Transfer'
    )
    total_transfer_weight = fields.Float(
        string='Total Transfer Weight (g)',
        compute='_compute_total_transfer_weight',
        digits=(16, 3)
    )

    @api.depends('line_ids.transfer_weight')
    def _compute_total_transfer_weight(self):
        for wiz in self:
            wiz.total_transfer_weight = round(sum(wiz.line_ids.mapped('transfer_weight')), 3)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self._context.get('active_ids')
        active_model = self._context.get('active_model')
        transfer_type = self._context.get('default_transfer_type', res.get('transfer_type', 'outbound'))
        res['transfer_type'] = transfer_type

        if not res.get('notes'):
            if transfer_type == 'inbound':
                res['notes'] = _('Shortage Weight Fulfillment Transfer')
            else:
                res['notes'] = _('Excess Weight Adjustment Transfer')

        if active_model == 'stock.location.product.excess.weight' and active_ids:
            records = self.env['stock.location.product.excess.weight'].browse(active_ids)
            locations = records.mapped('location_id')
            if len(locations) > 1:
                raise UserError(_("All selected product variants must belong to the same stock location."))
            if locations:
                loc = locations[0]
                if transfer_type == 'inbound':
                    # Needed location is the destination
                    res['location_dest_id'] = loc.id
                    # Try to auto-suggest source location with available stock if 1 product
                    if len(records) == 1:
                        candidate_quant = self.env['stock.quant'].search([
                            ('product_id', '=', records[0].product_id.id),
                            ('location_id.usage', '=', 'internal'),
                            ('location_id', '!=', loc.id),
                            ('quantity', '>', 0)
                        ], order='quantity desc', limit=1)
                        if candidate_quant:
                            res['location_id'] = candidate_quant.location_id.id
                            pt = self._find_internal_picking_type(candidate_quant.location_id)
                            if pt:
                                res['picking_type_id'] = pt.id
                else:
                    # Excess: source is the location
                    res['location_id'] = loc.id
                    pt = self._find_internal_picking_type(loc)
                    if pt:
                        res['picking_type_id'] = pt.id

            if not res.get('line_ids'):
                lines = []
                for rec in records:
                    if transfer_type == 'inbound':
                        t_weight = rec.shortage_weight if rec.shortage_weight > 0 else 0.0
                    else:
                        t_weight = rec.excess_weight if rec.excess_weight > 0 else (rec.system_quant_weight if rec.system_quant_weight > 0 else 0.0)
                    lines.append((0, 0, {
                        'excess_weight_id': rec.id,
                        'product_id': rec.product_id.id,
                        'system_quant_weight': rec.system_quant_weight,
                        'physical_weight': rec.physical_weight,
                        'excess_weight': rec.excess_weight,
                        'shortage_weight': rec.shortage_weight,
                        'transfer_weight': round(t_weight, 3),
                    }))
                res['line_ids'] = lines

        return res

    @api.onchange('location_id')
    def _onchange_location_id(self):
        if self.location_id:
            pt = self._find_internal_picking_type(self.location_id)
            if pt:
                self.picking_type_id = pt.id

    def _find_internal_picking_type(self, location):
        """Find the internal picking type corresponding to the location or company."""
        comp = location.company_id or self.env.company
        warehouse = location.warehouse_id or self.env['stock.warehouse'].search([
            ('lot_stock_id', 'parent_of', location.id)
        ], limit=1)
        if not warehouse and location.location_id:
            warehouse = self.env['stock.warehouse'].search([
                ('lot_stock_id', 'parent_of', location.location_id.id)
            ], limit=1)
        if not warehouse and hasattr(location, 'branch_id') and location.branch_id and hasattr(location.branch_id, 'warehouse_id') and location.branch_id.warehouse_id:
            warehouse = location.branch_id.warehouse_id

        if warehouse and warehouse.int_type_id:
            return warehouse.int_type_id
        if warehouse:
            pt = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('warehouse_id', '=', warehouse.id)
            ], limit=1)
            if pt:
                return pt

        pt = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', comp.id)
        ], limit=1)
        if pt:
            return pt

        return self.env.ref('stock.picking_type_internal', raise_if_not_found=False)

    def _create_transfer_picking(self, auto_validate=False):
        self.ensure_one()
        valid_lines = self.line_ids.filtered(lambda l: l.transfer_weight > 0)
        if not valid_lines:
            raise ValidationError(_("Please specify a transfer weight greater than 0 for at least one product."))

        if not self.location_id:
            raise ValidationError(_("Please select a Source Location."))

        if not self.location_dest_id:
            raise ValidationError(_("Please select a Destination / Needed Location."))

        if not self.picking_type_id:
            raise ValidationError(_("Please select an operation type for the transfer."))

        if self.location_id == self.location_dest_id:
            raise ValidationError(_("Source and destination locations cannot be the same."))

        company_id = self.location_id.company_id.id or self.company_id.id or self.env.company.id

        if self.transfer_type == 'inbound':
            origin_desc = _('Shortage Fulfillment for %s') % self.location_dest_id.display_name
        else:
            origin_desc = _('Excess Transfer - %s') % self.location_id.display_name

        picking_vals = {
            'picking_type_id': self.picking_type_id.id,
            'location_id': self.location_id.id,
            'location_dest_id': self.location_dest_id.id,
            'origin': origin_desc,
            'company_id': company_id,
            'note': self.notes or origin_desc,
        }
        if self.branch_id:
            picking_vals['branch_id'] = self.branch_id.id

        picking = self.env['stock.picking'].create(picking_vals)

        for line in valid_lines:
            # Validate source stock availability
            quant = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', self.location_id.id),
            ], limit=1)
            avail_stock = quant.quantity if quant else 0.0

            if round(line.transfer_weight, 3) > round(avail_stock, 3) and avail_stock >= 0:
                raise ValidationError(_(
                    "Transfer weight for '%s' (%.3f g) exceeds available stock (%.3f g) in source location %s."
                ) % (
                    line.product_id.display_name,
                    line.transfer_weight,
                    avail_stock,
                    self.location_id.display_name
                ))

            move_vals = {
                'name': _('%s (%.3fg)') % (line.product_id.display_name, line.transfer_weight),
                'product_id': line.product_id.id,
                'product_uom_qty': line.transfer_weight,
                'product_uom': line.product_id.uom_id.id,
                'location_id': self.location_id.id,
                'location_dest_id': self.location_dest_id.id,
                'picking_id': picking.id,
                'company_id': company_id,
            }
            if hasattr(line.product_id, 'purity_id') and line.product_id.purity_id:
                move_vals['purity_id'] = line.product_id.purity_id.id
            elif hasattr(line.product_id.product_tmpl_id, 'purity_id') and line.product_id.product_tmpl_id.purity_id:
                move_vals['purity_id'] = line.product_id.product_tmpl_id.purity_id.id
            if self.branch_id:
                move_vals['branch_id'] = self.branch_id.id

            self.env['stock.move'].create(move_vals)

        picking.action_confirm()
        picking.action_assign()

        if auto_validate:
            for move in picking.move_ids:
                if move.move_line_ids:
                    for ml in move.move_line_ids:
                        ml.quantity = move.product_uom_qty
                        ml.picked = True
                else:
                    self.env['stock.move.line'].create({
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'quantity': move.product_uom_qty,
                        'picked': True,
                    })
                move.picked = True
                move.quantity = move.product_uom_qty

            picking.with_context(skip_backorder=True, skip_sms=True).button_validate()

            # Refresh weights on affected excess/shortage records
            recs_to_refresh = valid_lines.mapped('excess_weight_id')
            if recs_to_refresh:
                recs_to_refresh._compute_system_weights()
                recs_to_refresh._compute_physical_weight()
                recs_to_refresh._compute_difference()

            # Refresh counterpart location lines if they exist
            counterpart_loc = self.location_id if self.transfer_type == 'inbound' else self.location_dest_id
            counterpart_recs = self.env['stock.location.product.excess.weight'].search([
                ('location_id', '=', counterpart_loc.id),
                ('product_id', 'in', valid_lines.mapped('product_id.id'))
            ])
            if counterpart_recs:
                counterpart_recs._compute_system_weights()
                counterpart_recs._compute_physical_weight()
                counterpart_recs._compute_difference()

            # Refresh location-level weights
            self.location_id._compute_location_weights()
            self.location_id._compute_weight_difference()
            self.location_dest_id._compute_location_weights()
            self.location_dest_id._compute_weight_difference()

        return picking

    def action_transfer_and_validate(self):
        """Execute transfer and validate immediately."""
        picking = self._create_transfer_picking(auto_validate=True)
        if self.transfer_type == 'inbound':
            title = _('Shortage Weight Fulfilled & Validated')
            msg = _('Transfer %s created and validated successfully. Total %.3f g transferred from %s to needed location %s.') % (
                picking.name,
                self.total_transfer_weight,
                self.location_id.display_name,
                self.location_dest_id.display_name
            )
        else:
            title = _('Excess Weight Transferred & Validated')
            msg = _('Transfer %s created and validated successfully. Total %.3f g transferred from %s to %s.') % (
                picking.name,
                self.total_transfer_weight,
                self.location_id.display_name,
                self.location_dest_id.display_name
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_create_draft_transfer(self):
        """Create transfer picking in Ready/Draft state for user review."""
        picking = self._create_transfer_picking(auto_validate=False)
        return {
            'name': _('Transfer: %s') % picking.name,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }


class StockLocationProductExcessTransferWizardLine(models.TransientModel):
    _name = 'stock.location.product.excess.transfer.wizard.line'
    _description = 'Excess/Shortage Weight Transfer Wizard Line'

    wizard_id = fields.Many2one(
        'stock.location.product.excess.transfer.wizard',
        ondelete='cascade',
        required=True
    )
    excess_weight_id = fields.Many2one(
        'stock.location.product.excess.weight',
        string='Weight Record'
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        required=True
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        related='product_id.uom_id',
        readonly=True
    )
    system_quant_weight = fields.Float(
        string='Quant Wt (g)',
        digits=(16, 3)
    )
    physical_weight = fields.Float(
        string='Physical Wt (g)',
        digits=(16, 3)
    )
    excess_weight = fields.Float(
        string='Excess Wt (g)',
        digits=(16, 3)
    )
    shortage_weight = fields.Float(
        string='Shortage Wt (g)',
        digits=(16, 3)
    )
    source_stock_weight = fields.Float(
        string='Available in Source (g)',
        compute='_compute_source_stock_weight',
        digits=(16, 3)
    )
    transfer_weight = fields.Float(
        string='Transfer Wt (g)',
        digits=(16, 3),
        required=True
    )

    @api.depends('wizard_id.location_id', 'product_id')
    def _compute_source_stock_weight(self):
        for line in self:
            if line.wizard_id.location_id and line.product_id:
                quant = self.env['stock.quant'].search([
                    ('location_id', '=', line.wizard_id.location_id.id),
                    ('product_id', '=', line.product_id.id),
                ], limit=1)
                line.source_stock_weight = round(quant.quantity, 3) if quant else 0.0
            else:
                line.source_stock_weight = 0.0
