import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


class ProductLabel(models.Model):
    _inherit = 'product.label'

    is_manufactured = fields.Boolean(
        string="Is Manufactured",
        default=False,
        copy=False,
        help="Indicates whether this label has been manufactured."
    )
    production_id = fields.Many2one(
        'mrp.production',
        string="Manufacturing Order",
        copy=False,
        help="Manufacturing Order created for this label."
    )
    internal_transfer_id = fields.Many2one(
        'stock.picking',
        string="Internal Transfer",
        domain="[('picking_type_code', '=', 'internal'), ('state', 'in', ['assigned', 'done'])]",
        copy=False,
        check_company=True,
        help="Select the internal transfer associated with this label."
    )
    transfer_manufacture_location_ids = fields.Many2many(
        'stock.location',
        string="Transfer Manufacture Locations",
        related='company_id.transfer_manufacture_location_ids',
        readonly=True,
    )
    manufacture_location_id = fields.Many2one(
        'stock.location',
        string="Manufactured Location",
        copy=False,
        check_company=True,
        help="Location where the manufactured product will be placed."
    )
    transfer_move_id = fields.Many2one(
        'stock.move',
        string="Transfer Item",
        domain="[('id', 'in', available_transfer_move_ids)]",
        copy=False,
        check_company=True,
        help="Select the specific transfer item/line."
    )
    available_transfer_move_ids = fields.Many2many(
        'stock.move',
        compute='_compute_available_transfer_move_ids',
        string="Available Transfer Moves",
    )
    transfer_product_id = fields.Many2one(
        'product.product',
        string="Transfer Product",
        related='transfer_move_id.product_id',
        store=True,
        readonly=True,
        help="Product associated with the selected transfer item."
    )
    unlabelled_weight_transfer = fields.Float(
        string="Unlabelled Weight",
        compute="_compute_unlabelled_weight",
        store=False,
        help="Remaining unlabelled weight for the selected item in this internal transfer."
    )

    @api.depends('internal_transfer_id', 'transfer_move_id')
    def _compute_available_transfer_move_ids(self):
        for rec in self:
            if not rec.internal_transfer_id:
                rec.available_transfer_move_ids = [(5, 0, 0)]
                continue

            moves = rec.internal_transfer_id.move_ids.filtered(lambda m: m.state != 'cancel')
            if not moves:
                rec.available_transfer_move_ids = [(5, 0, 0)]
                continue

            rec_origin_id = rec._origin.id or (rec.id if isinstance(rec.id, int) else False)
            all_labels = self.env['product.label'].sudo().with_context(active_test=False).search([
                ('transfer_move_id', 'in', moves.ids),
                '|', ('is_manufactured', '=', True), ('production_id', '!=', False)
            ])
            if rec_origin_id:
                all_labels = all_labels.filtered(lambda l: l.id != rec_origin_id)

            move_mfg_weights = {}
            for l in all_labels:
                m_id = l.transfer_move_id.id
                move_mfg_weights[m_id] = move_mfg_weights.get(m_id, 0.0) + (l.sale_gross_weight or 0.0)

            valid_ids = []
            for move in moves:
                # Keep currently selected move visible on this record
                if rec.transfer_move_id and rec.transfer_move_id.id == move.id:
                    valid_ids.append(move.id)
                    continue

                total_weight = (
                    getattr(move, 'grams', 0.0)
                    or (move.quantity if (rec.internal_transfer_id.state == 'done' and move.quantity) else (move.product_uom_qty or move.quantity or 0.0))
                )
                mfg_weight = move_mfg_weights.get(move.id, 0.0)
                # Only show products whose weight is not yet fully manufactured
                if float_compare(total_weight - mfg_weight, 0.0, precision_digits=3) > 0:
                    valid_ids.append(move.id)

            rec.available_transfer_move_ids = [(6, 0, valid_ids)]

    @api.depends(
        'purchase_id', 'job_work_id', 'production_id',
        'internal_transfer_id', 'transfer_move_id', 'sale_gross_weight'
    )
    def _compute_unlabelled_weight(self):
        super()._compute_unlabelled_weight()
        for rec in self:
            rec.unlabelled_weight_transfer = 0.0
            if rec.internal_transfer_id and rec.transfer_move_id:
                move = rec.transfer_move_id
                move_weight = getattr(move, 'grams', 0.0) or (move.quantity if (rec.internal_transfer_id.state == 'done' and move.quantity) else (move.product_uom_qty or move.quantity or 0.0))
                rec_origin_id = rec._origin.id or (rec.id if isinstance(rec.id, int) else False)
                other_labels = self.env['product.label'].sudo().with_context(active_test=False).search([
                    ('transfer_move_id', '=', move.id),
                ]).filtered(lambda l: l.id != rec_origin_id)
                total_other = sum(other_labels.filtered(lambda l: l.is_manufactured or l.production_id).mapped('sale_gross_weight'))
                rec.unlabelled_weight_transfer = move_weight - total_other - (rec.sale_gross_weight or 0.0)

    @api.onchange('company_id')
    def _onchange_company_id_transfer(self):
        locs = self.company_id.transfer_manufacture_location_ids if self.company_id else self.env['stock.location']
        self.transfer_manufacture_location_ids = locs
        if locs:
            return {'domain': {'internal_transfer_id': [
                ('picking_type_code', '=', 'internal'),
                ('state', 'in', ['assigned', 'done']),
                ('location_dest_id', 'child_of', locs.ids)
            ]}}
        return {'domain': {'internal_transfer_id': [
            ('picking_type_code', '=', 'internal'),
            ('state', 'in', ['assigned', 'done'])
        ]}}

    @api.onchange('internal_transfer_id')
    def _onchange_internal_transfer_id(self):
        if self.internal_transfer_id:
            self._compute_available_transfer_move_ids()
            valid_move_ids = self.available_transfer_move_ids.ids
            if self.transfer_move_id and self.transfer_move_id.id not in valid_move_ids:
                self.transfer_move_id = False
            self._compute_unlabelled_weight()
            return {'domain': {'transfer_move_id': [('id', 'in', valid_move_ids)]}}
        else:
            self.available_transfer_move_ids = [(5, 0, 0)]
            self.transfer_move_id = False
            self.unlabelled_weight_transfer = 0.0
            return {'domain': {'transfer_move_id': [('id', 'in', [])]}}

    @api.onchange('transfer_move_id')
    def _onchange_transfer_move_id(self):
        self._compute_unlabelled_weight()
        return self._onchange_check_unlabelled_weight_limit()

    @api.constrains(
        'sale_gross_weight', 'purchase_id', 'job_work_id',
        'product_id', 'product_tmpl_id', 'internal_transfer_id', 'transfer_move_id'
    )
    def _check_unlabelled_weight_limit(self):
        super()._check_unlabelled_weight_limit()
        for rec in self:
            if rec.internal_transfer_id and rec.transfer_move_id and float_compare(rec.unlabelled_weight_transfer, -1.0, precision_digits=3) <= 0:
                raise ValidationError(_(
                    "Unlabelled weight for Internal Transfer '%s' reached %s g. "
                    "Unlabelled weight cannot be -1 g or less."
                ) % (rec.internal_transfer_id.name, round(rec.unlabelled_weight_transfer, 3)))

    @api.onchange(
        'sale_gross_weight', 'purchase_id', 'job_work_id',
        'product_id', 'product_tmpl_id', 'internal_transfer_id', 'transfer_move_id'
    )
    def _onchange_check_unlabelled_weight_limit(self):
        res = super()._onchange_check_unlabelled_weight_limit()
        if res:
            return res
        if self.internal_transfer_id and self.transfer_move_id and float_compare(self.unlabelled_weight_transfer, -1.0, precision_digits=3) <= 0:
            return {
                'warning': {
                    'title': _("Unlabelled Weight Limit Exceeded"),
                    'message': _(
                        "Unlabelled weight for Internal Transfer '%s' reached %s g. "
                        "Unlabelled weight cannot be -1 g or less! You will not be able to save this record."
                    ) % (self.internal_transfer_id.name, round(self.unlabelled_weight_transfer, 3)),
                }
            }

    def init(self):
        super().init()
        self.env.cr.execute("""
            UPDATE product_label pl
            SET product_template_id = pp.product_tmpl_id
            FROM product_product pp
            WHERE pl.product_id = pp.id AND pl.product_template_id IS NULL;
        """)

    @api.onchange('product_id')
    def _onchange_product_id_sync_template(self):
        if self.product_id and not self.product_template_id:
            self.product_template_id = self.product_id.product_tmpl_id
        self._compute_unlabelled_weight()
        return self._onchange_check_unlabelled_weight_limit()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('product_id') and not vals.get('product_template_id'):
                product = self.env['product.product'].browse(vals['product_id'])
                if product.exists() and product.product_tmpl_id:
                    vals['product_template_id'] = product.product_tmpl_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('product_id') and not vals.get('product_template_id'):
            product = self.env['product.product'].browse(vals['product_id'])
            if product.exists() and product.product_tmpl_id:
                vals['product_template_id'] = product.product_tmpl_id.id
        return super().write(vals)

    def action_create_mrp_production(self):
        self.ensure_one()

        if self.is_stocked_in:
            raise UserError(_("Cannot manufacture a label that has already been transferred."))

        if self.is_manufactured or self.production_id:
            raise UserError(_("This label has already been manufactured."))

        if not self.product_id:
            raise UserError(_("Product Variant is required to create a Manufacturing Order."))

        if not self.purchase_id:
            raise UserError(_("Purchase Order is required to determine the components."))

        if not self.sale_gross_weight or self.sale_gross_weight <= 0:
            raise UserError(_("Sale Gross Weight (g) must be greater than zero."))

        # Sourcing raw components from the matching lines on the Purchase Order
        po_lines = self.purchase_id.order_line.filtered(lambda l: l.product_id == self.product_id)
        if not po_lines:
            target_tmpl = self.product_template_id or self.product_id.product_tmpl_id
            po_lines = self.purchase_id.order_line.filtered(
                lambda l: l.product_id.product_tmpl_id == target_tmpl
            )
        if not po_lines:
            po_lines = self.purchase_id.order_line[:1]

        comp_product = po_lines[0].product_id if po_lines else self.product_id
        comp_uom = po_lines[0].product_uom if po_lines else self.product_id.uom_id

        company = self.company_id or self.env.company
        company_id = company.id

        # Determine picking type for manufacturing
        picking_type_id = self.env['mrp.production']._get_default_picking_type_id(company_id)
        if not picking_type_id:
            pt = self.env['stock.picking.type'].search([
                ('code', '=', 'mrp_operation'),
                ('company_id', '=', company_id)
            ], limit=1)
            picking_type_id = pt.id if pt else False

        mo_vals = {
            'product_id': self.product_id.id,
            'product_qty': self.sale_gross_weight,
            'product_uom_id': self.product_id.uom_id.id,
            'picking_type_id': picking_type_id,
            'company_id': company_id,
            'origin': f"{self.purchase_id.name} / {self.name}",
        }

        # Include custom jewellery fields if available in mrp.production model
        mrp_fields = self.env['mrp.production']._fields
        if 'total_grams' in mrp_fields:
            mo_vals['total_grams'] = self.sale_gross_weight
        if 'purity_id' in mrp_fields and self.purity_id:
            mo_vals['purity_id'] = self.purity_id.id
        if 'branch_id' in mrp_fields and self.branch_id:
            mo_vals['branch_id'] = self.branch_id.id
        if 'product_template_id' in mrp_fields:
            tmpl = self.product_template_id or self.product_id.product_tmpl_id
            if tmpl:
                mo_vals['product_template_id'] = tmpl.id

        mo = self.env['mrp.production'].create(mo_vals)

        # Create raw component consumption move
        move_vals = {
            'raw_material_production_id': mo.id,
            'name': mo.name,
            'product_id': comp_product.id,
            'product_uom': comp_uom.id,
            'product_uom_qty': self.sale_gross_weight,
            'company_id': company_id,
            'location_id': mo.location_src_id.id,
            'location_dest_id': mo.production_location_id.id,
        }
        move_fields = self.env['stock.move']._fields
        if 'total_grams' in move_fields:
            move_vals['total_grams'] = self.sale_gross_weight
        if 'grams' in move_fields:
            move_vals['grams'] = self.sale_gross_weight
        if 'purity_id' in move_fields:
            po_purity = po_lines[0].purity_id if (po_lines and hasattr(po_lines[0], 'purity_id') and po_lines[0].purity_id) else self.purity_id
            if po_purity:
                move_vals['purity_id'] = po_purity.id
        if 'branch_id' in move_fields and (self.branch_id or mo.branch_id):
            move_vals['branch_id'] = (self.branch_id or mo.branch_id).id

        self.env['stock.move'].create(move_vals)

        # Confirm and attempt to finalize the manufacturing order
        mo.action_confirm()

        try:
            mo.qty_producing = self.sale_gross_weight
            for move in mo.move_raw_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
                if 'grams' in move._fields and not move.grams:
                    move.grams = move.product_uom_qty
                if 'purity_id' in move._fields and not move.purity_id and self.purity_id:
                    move.purity_id = self.purity_id.id
            mo.button_mark_done()
        except Exception as e:
            _logger.info("MO %s confirmed; automatic validation skipped: %s", mo.name, e)

        # Mark label as manufactured and link production order
        self.write({
            'production_id': mo.id,
            'is_manufactured': True,
        })

        # Return celebratory interactive animation (Rainbow Man)
        return {
            'effect': {
                'fadeout': 'slow',
                'message': _("🎉 Manufactured Successfully!\nOrder %s created for %s (%s g).") % (
                    mo.name, 
                    self.product_id.display_name, 
                    self.sale_gross_weight
                ),
                'type': 'rainbow_man',
                'img_url': 'https://giphy.com'
            }
        }

    def action_create_mrp_production_transfer(self):
        self.ensure_one()

        if self.is_stocked_in:
            raise UserError(_("Cannot manufacture a label that has already been transferred."))

        if self.is_manufactured or self.production_id:
            raise UserError(_("This label has already been manufactured."))

        if not self.internal_transfer_id:
            raise UserError(_("Internal Transfer is required to create a Manufacturing Order."))

        if not self.product_id:
            raise UserError(_("Product Variant is required to create a Manufacturing Order."))

        if not self.sale_gross_weight or self.sale_gross_weight <= 0:
            raise UserError(_("Sale Gross Weight (g) must be greater than zero."))

        if not self.manufacture_location_id:
            raise UserError(_("Manufactured Location is required to create a Manufacturing Order."))

        # Sourcing raw components from the selected transfer item or matching transfer moves
        comp_product = self.product_id
        comp_uom = self.product_id.uom_id
        comp_purity = self.purity_id
        comp_location = self.internal_transfer_id.location_dest_id or self.internal_transfer_id.location_id

        if self.transfer_move_id:
            comp_product = self.transfer_move_id.product_id or self.product_id
            comp_uom = self.transfer_move_id.product_uom or self.product_id.uom_id
            if hasattr(self.transfer_move_id, 'purity_id') and self.transfer_move_id.purity_id:
                comp_purity = self.transfer_move_id.purity_id
            if self.transfer_move_id.location_dest_id:
                comp_location = self.transfer_move_id.location_dest_id
            elif self.transfer_move_id.location_id:
                comp_location = self.transfer_move_id.location_id
        else:
            matching_moves = self.internal_transfer_id.move_ids.filtered(
                lambda m: m.product_id == self.product_id and m.state != 'cancel'
            )
            if not matching_moves:
                target_tmpl = self.product_template_id or self.product_id.product_tmpl_id
                matching_moves = self.internal_transfer_id.move_ids.filtered(
                    lambda m: m.product_id.product_tmpl_id == target_tmpl and m.state != 'cancel'
                )
            if matching_moves:
                comp_product = matching_moves[0].product_id
                comp_uom = matching_moves[0].product_uom
                if hasattr(matching_moves[0], 'purity_id') and matching_moves[0].purity_id:
                    comp_purity = matching_moves[0].purity_id
                if matching_moves[0].location_dest_id:
                    comp_location = matching_moves[0].location_dest_id
                elif matching_moves[0].location_id:
                    comp_location = matching_moves[0].location_id

        if not comp_location and getattr(self, 'source_location_id', False):
            comp_location = self.source_location_id

        company = self.company_id or self.env.company
        company_id = company.id

        # Determine picking type for manufacturing
        picking_type_id = self.env['mrp.production']._get_default_picking_type_id(company_id)
        if not picking_type_id:
            pt = self.env['stock.picking.type'].search([
                ('code', '=', 'mrp_operation'),
                ('company_id', '=', company_id)
            ], limit=1)
            picking_type_id = pt.id if pt else False

        mo_vals = {
            'product_id': self.product_id.id,
            'product_qty': self.sale_gross_weight,
            'product_uom_id': self.product_id.uom_id.id,
            'picking_type_id': picking_type_id,
            'company_id': company_id,
            'origin': f"{self.internal_transfer_id.name} / {self.name}",
        }
        # Components Location on MO set from the Source
        if comp_location:
            mo_vals['location_src_id'] = comp_location.id

        # Finished Products Location on MO
        if self.manufacture_location_id:
            mo_vals['location_dest_id'] = self.manufacture_location_id.id
        elif self.internal_transfer_id.location_dest_id:
            mo_vals['location_dest_id'] = self.internal_transfer_id.location_dest_id.id
        elif getattr(self, 'destination_location_id', False):
            mo_vals['location_dest_id'] = self.destination_location_id.id
        elif hasattr(company, 'transfer_manufacture_location_ids') and company.transfer_manufacture_location_ids:
            mo_vals['location_dest_id'] = company.transfer_manufacture_location_ids[0].id

        # Include custom jewellery fields if available in mrp.production model
        mrp_fields = self.env['mrp.production']._fields
        if 'total_grams' in mrp_fields:
            mo_vals['total_grams'] = self.sale_gross_weight
        if 'purity_id' in mrp_fields and comp_purity:
            mo_vals['purity_id'] = comp_purity.id
        if 'branch_id' in mrp_fields and (self.branch_id or getattr(self.internal_transfer_id, 'branch_id', False)):
            mo_vals['branch_id'] = (self.branch_id or getattr(self.internal_transfer_id, 'branch_id', False)).id
        if 'product_template_id' in mrp_fields:
            tmpl = self.product_template_id or self.product_id.product_tmpl_id
            if tmpl:
                mo_vals['product_template_id'] = tmpl.id

        mo = self.env['mrp.production'].create(mo_vals)

        # Create raw component consumption move
        src_loc_id = comp_location.id if comp_location else mo.location_src_id.id
        move_vals = {
            'raw_material_production_id': mo.id,
            'name': mo.name,
            'product_id': comp_product.id,
            'product_uom': comp_uom.id,
            'product_uom_qty': self.sale_gross_weight,
            'company_id': company_id,
            'location_id': src_loc_id,
            'location_dest_id': mo.production_location_id.id,
        }
        move_fields = self.env['stock.move']._fields
        if 'total_grams' in move_fields:
            move_vals['total_grams'] = self.sale_gross_weight
        if 'grams' in move_fields:
            move_vals['grams'] = self.sale_gross_weight
        if 'purity_id' in move_fields and comp_purity:
            move_vals['purity_id'] = comp_purity.id
        if 'branch_id' in move_fields and (self.branch_id or mo.branch_id):
            move_vals['branch_id'] = (self.branch_id or mo.branch_id).id

        self.env['stock.move'].create(move_vals)

        # Confirm and attempt to finalize the manufacturing order
        mo.action_confirm()

        try:
            with self.env.cr.savepoint():
                mo.qty_producing = self.sale_gross_weight
                for move in mo.move_raw_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                    if 'grams' in move._fields and not move.grams:
                        move.grams = move.product_uom_qty
                    if 'purity_id' in move._fields and not move.purity_id and comp_purity:
                        move.purity_id = comp_purity.id
                mo.button_mark_done()
        except Exception as e:
            _logger.info("MO %s confirmed; automatic validation skipped: %s", mo.name, e)

        # Mark label as manufactured and link production order
        self.write({
            'production_id': mo.id,
            'is_manufactured': True,
        })

        # Return celebratory interactive animation (Rainbow Man)
        return {
            'effect': {
                'fadeout': 'slow',
                'message': _("🎉 Manufactured Successfully!\nOrder %s created for %s (%s g).") % (
                    mo.name, 
                    self.product_id.display_name, 
                    self.sale_gross_weight
                ),
                'type': 'rainbow_man',
                'img_url': 'https://giphy.com'
            }
        }

    def action_view_production(self):
        self.ensure_one()
        if not self.production_id:
            raise UserError(_("No Manufacturing Order associated with this label."))
        return {
            'name': _("Manufacturing Order"),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'res_id': self.production_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_manufactured_done(self):
        self.ensure_one()
        if self.production_id:
            return self.action_view_production()
        return True

    def action_stock_in(self):
        self.ensure_one()
        if (self.purchase_id or self.internal_transfer_id) and not self.is_manufactured:
            raise UserError(_("Please manufacture the product before transferring."))
        return super().action_stock_in()
