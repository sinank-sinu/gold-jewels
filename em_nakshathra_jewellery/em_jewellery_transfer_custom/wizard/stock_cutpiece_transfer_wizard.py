# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class StockCutpieceTransferWizard(models.TransientModel):
    _name = 'stock.cutpiece.transfer.wizard'
    _description = 'Cutpiece Stock Internal Transfer Wizard'

    location_id = fields.Many2one(
        'stock.location',
        string="Source Location",
        required=True,
        readonly=True,
        domain="[('usage', '=', 'internal')]"
    )
    branch_id = fields.Many2one(
        'res.branch',
        string="Source Branch",
        readonly=True
    )
    company_id = fields.Many2one(
        'res.company',
        string="Company",
        required=True,
        default=lambda self: self.env.company
    )
    location_dest_id = fields.Many2one(
        'stock.location',
        string="Destination Location",
        required=True,
        domain="[('usage', '=', 'internal'), ('id', '!=', location_id), ('company_id', 'in', [company_id, False])]"
    )
    dest_branch_id = fields.Many2one(
        'res.branch',
        string="Destination Branch",
        related='location_dest_id.branch_id',
        readonly=True
    )
    picking_type_id = fields.Many2one(
        'stock.picking.type',
        string="Operation Type",
        required=True
    )
    transfer_date = fields.Datetime(
        string="Transfer Date",
        default=fields.Datetime.now,
        required=True
    )
    notes = fields.Char(
        string="Transfer Notes / Reason"
    )
    purity_summary = fields.Char(
        string="Purity",
        compute='_compute_purity_summary',
        readonly=True
    )
    line_ids = fields.One2many(
        'stock.cutpiece.transfer.wizard.line',
        'wizard_id',
        string="Items to Transfer"
    )
    total_quantity = fields.Float(
        string="Total Transfer Quantity (g)",
        compute='_compute_total_quantity',
        digits=(16, 3)
    )

    @api.depends('line_ids.quantity')
    def _compute_total_quantity(self):
        for wiz in self:
            wiz.total_quantity = round(sum(wiz.line_ids.mapped('quantity')), 3)

    @api.depends('line_ids.purity_id')
    def _compute_purity_summary(self):
        for wiz in self:
            names = [line.purity_id.name for line in wiz.line_ids if line.purity_id and line.purity_id.name]
            unique_names = sorted(set(names))
            wiz.purity_summary = ", ".join(unique_names) if unique_names else _("N/A")

    @api.model
    def _find_internal_picking_type(self, source_loc, company):
        warehouse = source_loc.warehouse_id
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
            ('company_id', '=', company.id)
        ], limit=1)
        if pt:
            return pt
        return self.env.ref('stock.picking_type_internal', raise_if_not_found=False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self._context.get('active_ids', [])
        active_model = self._context.get('active_model')

        if active_model == 'stock.quant' and active_ids:
            quants = self.env['stock.quant'].browse(active_ids)
            valid_quants = quants.filtered(lambda q: q.quantity > 0)
            if not valid_quants:
                raise UserError(_("None of the selected cut piece records have available stock to transfer."))

            locations = valid_quants.mapped('location_id')
            if len(locations) > 1:
                raise UserError(_("All selected cut pieces must belong to the same source location."))

            source_loc = locations[0]
            comp = source_loc.company_id or self.env.company
            branch = source_loc.branch_id or self.env.user.branch_id

            res['location_id'] = source_loc.id
            res['company_id'] = comp.id
            if branch:
                res['branch_id'] = branch.id

            pt = self._find_internal_picking_type(source_loc, comp)
            if pt:
                res['picking_type_id'] = pt.id

            # Smart default for destination location:
            # 1. Main branch location if configured and distinct from source
            # 2. Warehouse lot_stock_id if distinct from source
            if branch and branch.branch_location_id and branch.branch_location_id.id != source_loc.id:
                res['location_dest_id'] = branch.branch_location_id.id
            elif source_loc.warehouse_id and source_loc.warehouse_id.lot_stock_id and source_loc.warehouse_id.lot_stock_id.id != source_loc.id:
                res['location_dest_id'] = source_loc.warehouse_id.lot_stock_id.id

            lines = []
            for quant in valid_quants:
                purity = (
                    quant.purity_id or
                    (quant.product_id.purity_id if hasattr(quant.product_id, 'purity_id') else False) or
                    (quant.product_id.product_tmpl_id.purity_id if hasattr(quant.product_id.product_tmpl_id, 'purity_id') else False)
                )
                lines.append((0, 0, {
                    'quant_id': quant.id,
                    'product_id': quant.product_id.id,
                    'purity_id': purity.id if purity else False,
                    'available_qty': quant.quantity,
                    'quantity': quant.quantity,
                    'product_uom_id': quant.product_uom_id.id,
                }))
            res['line_ids'] = lines

            # Summary note default
            purities = sorted(set([l[2].get('purity_id') for l in lines if l[2].get('purity_id')]))
            if purities:
                purity_names = self.env['gold.purity'].browse(purities).mapped('name')
                res['notes'] = _("Cutpiece Transfer - %s") % (", ".join(purity_names))
            else:
                res['notes'] = _("Cutpiece Stock Transfer")

        return res

    def _create_transfer_picking(self):
        self.ensure_one()
        valid_lines = self.line_ids.filtered(lambda l: l.quantity > 0)
        if not valid_lines:
            raise ValidationError(_("Please specify a transfer quantity greater than 0 for at least one item."))

        if not self.location_id:
            raise ValidationError(_("Please select a Source Location."))

        if not self.location_dest_id:
            raise ValidationError(_("Please select a Destination Location."))

        if self.location_id == self.location_dest_id:
            raise ValidationError(_("Source Location and Destination Location cannot be the same."))

        if not self.picking_type_id:
            raise ValidationError(_("Please select an Operation Type for the transfer."))

        company_id = self.company_id.id or self.location_id.company_id.id or self.env.company.id

        # Determine origin description with purity if uniform
        purities = valid_lines.mapped('purity_id.name')
        purities_clean = [p for p in purities if p]
        if purities_clean and len(set(purities_clean)) == 1:
            origin_desc = _("Cutpiece Transfer - %s") % purities_clean[0]
        elif purities_clean:
            origin_desc = _("Cutpiece Transfer - %s") % (", ".join(sorted(set(purities_clean))))
        else:
            origin_desc = _("Cutpiece Stock Transfer")

        picking_vals = {
            'picking_type_id': self.picking_type_id.id,
            'location_id': self.location_id.id,
            'location_dest_id': self.location_dest_id.id,
            'origin': self.notes or origin_desc,
            'company_id': company_id,
            'scheduled_date': self.transfer_date or fields.Datetime.now(),
        }
        if self.branch_id:
            picking_vals['branch_id'] = self.branch_id.id

        picking = self.env['stock.picking'].create(picking_vals)

        for line in valid_lines:
            if round(line.quantity, 3) > round(line.available_qty, 3) and line.available_qty > 0:
                raise ValidationError(_(
                    "Transfer quantity for '%(prod)s' (%(qty).3f g) exceeds available stock (%(avail).3f g)."
                ) % {
                    'prod': line.product_id.display_name,
                    'qty': line.quantity,
                    'avail': line.available_qty,
                })

            move_vals = {
                'name': line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.product_uom_id.id,
                'location_id': self.location_id.id,
                'location_dest_id': self.location_dest_id.id,
                'picking_id': picking.id,
                'company_id': company_id,
            }
            if 'purity_id' in self.env['stock.move']._fields and line.purity_id:
                move_vals['purity_id'] = line.purity_id.id
            if self.branch_id:
                move_vals['branch_id'] = self.branch_id.id

            self.env['stock.move'].create(move_vals)

        picking.action_confirm()
        picking.action_assign()
        return picking

    def action_create_transfer(self):
        """Creates the internal transfer and opens it in form view."""
        picking = self._create_transfer_picking()
        return {
            'name': _('Internal Transfer: %s') % picking.name,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }


class StockCutpieceTransferWizardLine(models.TransientModel):
    _name = 'stock.cutpiece.transfer.wizard.line'
    _description = 'Cutpiece Stock Internal Transfer Wizard Line'

    wizard_id = fields.Many2one(
        'stock.cutpiece.transfer.wizard',
        string="Wizard",
        required=True,
        ondelete='cascade'
    )
    quant_id = fields.Many2one(
        'stock.quant',
        string="Stock Quant"
    )
    product_id = fields.Many2one(
        'product.product',
        string="Product",
        required=True,
        readonly=True
    )
    purity_id = fields.Many2one(
        'gold.purity',
        string="Purity",
        readonly=True
    )
    available_qty = fields.Float(
        string="On Hand Qty (g)",
        digits=(16, 3),
        readonly=True
    )
    quantity = fields.Float(
        string="Transfer Qty (g)",
        digits=(16, 3),
        required=True
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string="Unit of Measure",
        readonly=True
    )

