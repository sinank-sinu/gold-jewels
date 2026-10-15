import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

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
                    mo.name, self.product_id.display_name, self.sale_gross_weight
                ),
                'type': 'rainbow_man',
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
        if self.purchase_id and not self.is_manufactured:
            raise UserError(_("Please manufacture the product before transferring."))
        return super().action_stock_in()
