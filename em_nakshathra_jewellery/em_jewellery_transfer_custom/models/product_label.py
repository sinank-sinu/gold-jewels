# -*- coding: utf-8 -*-
from odoo import models, api, _
from odoo.exceptions import UserError


class ProductLabel(models.Model):
    _inherit = 'product.label'

    @api.constrains('sale_gross_weight', 'purchase_id', 'job_work_id', 'product_id', 'product_tmpl_id')
    def _check_unlabelled_weight_limit(self):
        """Bypass PO/JW unlabelled weight check when updating label gross weight during cut piece transfers."""
        if self.env.context.get('cutpiece_weight_update') or self.env.context.get('skip_unlabelled_weight_check'):
            return
        return super()._check_unlabelled_weight_limit()

    @api.model
    def _find_internal_picking_type(self, source_loc, company):
        """Find the internal transfer operation type for the source location's warehouse or company."""
        warehouse = source_loc.warehouse_id or self.env['stock.warehouse'].search([
            ('lot_stock_id', 'parent_of', source_loc.id)
        ], limit=1)
        if not warehouse and source_loc.location_id:
            warehouse = self.env['stock.warehouse'].search([
                ('lot_stock_id', 'parent_of', source_loc.location_id.id)
            ], limit=1)

        if warehouse and warehouse.int_type_id:
            return warehouse.int_type_id
        if warehouse:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('warehouse_id', '=', warehouse.id),
            ], limit=1)
            if picking_type:
                return picking_type

        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', company.id),
        ], limit=1)
        if picking_type:
            return picking_type

        return self.env.ref('stock.picking_type_internal', raise_if_not_found=False)

    def _validate_for_internal_transfer(self):
        """Validate selected labels before creating a draft internal transfer."""
        if not self:
            raise UserError(_("Please select at least one label to transfer."))

        inactive_labels = self.filtered(lambda l: not l.active)
        if inactive_labels:
            raise UserError(_(
                "Inactive labels cannot be transferred: %s"
            ) % ", ".join(inactive_labels.mapped('name')))

        if 'is_transferred' in self._fields:
            transferred_labels = self.filtered(lambda l: l.is_transferred)
            if transferred_labels:
                raise UserError(_(
                    "Labels already transferred to another company cannot be transferred: %s"
                ) % ", ".join(transferred_labels.mapped('name')))

        not_stocked = self.filtered(lambda l: not l.is_stocked_in)
        if not_stocked:
            raise UserError(_(
                "Only stocked-in labels can be transferred. Not stocked in: %s"
            ) % ", ".join(not_stocked.mapped('name')))

        missing_product = self.filtered(lambda l: not l.product_id)
        if missing_product:
            raise UserError(_(
                "The following labels are missing a product: %s"
            ) % ", ".join(missing_product.mapped('name')))

        missing_location = self.filtered(lambda l: not l.branch_location_id)
        if missing_location:
            raise UserError(_(
                "The following labels have no current branch location: %s"
            ) % ", ".join(missing_location.mapped('name')))

        current_company = self.env.company
        other_company = self.filtered(lambda l: l.company_id and l.company_id != current_company)
        if other_company:
            raise UserError(_(
                "Some selected labels do not belong to the current company (%s): %s"
            ) % (current_company.name, ", ".join(other_company.mapped('name'))))

        locations = self.mapped('branch_location_id')
        if len(locations) > 1:
            loc_names = ", ".join(sorted(set(locations.mapped('display_name'))))
            raise UserError(_(
                "All selected labels must be in the same current location. Found multiple locations: %s"
            ) % loc_names)

        conflicting_moves = self.env['stock.move'].sudo().search([
            ('label_id', 'in', self.ids),
            ('state', 'not in', ('done', 'cancel')),
        ])
        if conflicting_moves:
            conflicts = ", ".join(
                f"{m.label_id.name} ({m.picking_id.name or m.reference or _('active transfer')})"
                for m in conflicting_moves
            )
            raise UserError(_(
                "The following labels are already reserved in an active transfer: %s"
            ) % conflicts)

    def action_create_internal_transfer(self):
        """Create a draft internal transfer picking populated with the selected labels and open it."""
        self._validate_for_internal_transfer()

        source_loc = self.mapped('branch_location_id')[0]
        company = source_loc.company_id or self.env.company
        branch = source_loc.branch_id or self.env.user.branch_id

        picking_type = self._find_internal_picking_type(source_loc, company)
        if not picking_type:
            raise UserError(_("No internal transfer operation type found for company %s.") % company.name)

        dest_loc = picking_type.default_location_dest_id
        if not dest_loc or (dest_loc.company_id and dest_loc.company_id != company):
            dest_loc = (source_loc.warehouse_id.lot_stock_id if source_loc.warehouse_id else False) or source_loc

        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': source_loc.id,
            'location_dest_id': dest_loc.id,
            'company_id': company.id,
        }
        if branch:
            picking_vals['branch_id'] = branch.id

        picking = self.env['stock.picking'].with_context(
            skip_label_location_overwrite=True
        ).create(picking_vals)

        move_fields = self.env['stock.move']._fields
        move_vals_list = []
        for label in self:
            move_vals = {
                'name': label.product_id.display_name or label.name,
                'product_id': label.product_id.id,
                'product_uom_qty': label.purchase_gross_weight or label.sale_gross_weight or 1.0,
                'product_uom': label.product_id.uom_id.id,
                'location_id': source_loc.id,
                'location_dest_id': dest_loc.id,
                'picking_id': picking.id,
                'company_id': company.id,
                'label_id': label.id,
                'barcode': label.barcode or label.barcode2 or label.product_id.barcode or '',
            }
            if 'purity_id' in move_fields and label.purity_id:
                move_vals['purity_id'] = label.purity_id.id
            if 'branch_id' in move_fields and branch:
                move_vals['branch_id'] = branch.id
            move_vals_list.append(move_vals)

        self.env['stock.move'].with_context(
            skip_label_location_overwrite=True
        ).create(move_vals_list)

        return {
            'name': _('Internal Transfer: %s') % picking.name,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }


