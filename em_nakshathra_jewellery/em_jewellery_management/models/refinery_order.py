from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class OldGoldRefineryIssue(models.Model):
    _name = 'old.gold.refinery.issue'
    _description = 'Old Gold Refinery Issue'

    def _get_branch_domain(self):
        """methode to get branch domain"""
        company = self.env.company
        branch_ids = self.env.user.branch_ids
        branch = branch_ids.filtered(
            lambda branch: branch.company_id == company)
        return [('id', 'in', branch.ids)]

    branch_id = fields.Many2one('res.branch', string='Branch', store=True,
                                domain=_get_branch_domain,
                                help='Leave this field empty if this account is'
                                     ' shared between all branches',
                                default=lambda self: self.env.user.branch_id.id, )

    name = fields.Char(default='New', readonly=True)
    # verification_id = fields.Many2one('old.gold.ho.verification', required=True)
    refinery_partner_id = fields.Many2one('res.partner')
    issue_date = fields.Date(default=fields.Date.today)
    source_location_id = fields.Many2one('stock.location')
    received_location_id = fields.Many2one('stock.location', domain="[('usage', '=', 'internal')]")
    picking_id = fields.Many2one('stock.picking', readonly=True)
    line_ids = fields.One2many(
    'old.gold.refinery.issue.line',
    'issue_id'
    )


    picking_id = fields.Many2one('stock.picking', readonly=True)
    state = fields.Selection([
    ('draft', 'Draft'),
    ('to_melting', 'To Melting'),
    ('melting', 'Melting Completed'),
    ('issued', 'Issued'),
    ('received', 'Received'),

    ], default='draft')
    total_issued_weight = fields.Float(compute='_compute_total_issued_weight',
        store=True)
    melting_loss = fields.Float(digits=(16, 3))
    output_weight = fields.Float(compute='_compute_output', store=True,digits=(16, 3),string="Melted weight")
    mo_id = fields.Many2one('mrp.production', string="Manufacturing Order")
    bullion_receipt_id = fields.Many2one("old.gold.bullion.receipt")
    bullion_issue_id = fields.Many2one("old.gold.bullion.issue")
    # 🔹 Batch Tracking
    batch_ids = fields.One2many('old.gold.batch', 'refinery_issue_id', string='Batches')


    total_fine = fields.Float(
        compute='_compute_totals',
        store=True,
        string="Total Fine",
        digits=(16, 3)
    )
    expected_purity = fields.Float(
        compute='_compute_totals',
        store=True,
        string="Expected Purity (%)",
        digits=(5, 2)
    )
    lab_sample_weight = fields.Float(
        string='Lab Sample Weight (g)'
    )

    lab_purity_percent = fields.Float(string="Lab Purity (%)")
    lab_purity_id = fields.Many2one('lab.purity', string="Lab Purity Result", readonly=True)

    @api.onchange('lab_purity_percent')
    def _onchange_lab_purity_percent(self):
        if self.lab_purity_percent > 0:
            if not self.lab_purity_id:
                self.lab_purity_id = self.env['lab.purity'].create({
                    'name': f"Result: {self.name or 'New'} ({self.lab_purity_percent}%)",
                    'percentage': self.lab_purity_percent,
                    'refinery_issue_id': self._origin.id or self.id,
                    'picking_id':self.picking_id.id,
                })
            else:
                self.lab_purity_id.write({
                    'name': f"Result: {self.name or 'New'} ({self.lab_purity_percent}%)",
                    'percentage': self.lab_purity_percent,
                })
        else:
            self.lab_purity_id = False

    balance_weight = fields.Float(
        string='Balance Weight (g)',
        compute='_compute_balance_weight',
        store=True
    )
    expected_purity_id = fields.Many2one(
        'gold.purity',
        string="Expected Purity",
        compute="_compute_expected_purity_master",
        store=True
    )
    total_purchase_amount =fields.Float(compute='_compute_total_purchase_amount', store=True)
    purchase_per_rate = fields.Float(string="Purchase/gram", compute="_compute_per_gram", store=True)
    scrap_bar_unit_rate = fields.Float(string="Scrap Bar Rate", compute='_compute_scrap_bar_rate', store=True)

    @api.depends('name','state') # Dependencies can be minimal if it's a fixed product cost
    def _compute_scrap_bar_rate(self):
        product_scrap = self.env.ref('em_jewellery_management.product_scrap')
        scrap_variant = product_scrap if product_scrap._name == 'product.product' else product_scrap.product_variant_id
        for record in self:
            record.scrap_bar_unit_rate = scrap_variant.standard_price

    @api.depends('total_purchase_amount')
    def _compute_per_gram(self):
        for record in self:
            print(record,'record')
            record.purchase_per_rate = (
                record.total_purchase_amount / record.total_issued_weight
                if record.total_issued_weight
                else 0.0
            )

    @api.onchange('refinery_partner_id')
    def _onchange_partner_set_location(self):
        if self.refinery_partner_id.property_stock_supplier:
            self.received_location_id = self.refinery_partner_id.property_stock_supplier.id

    @api.depends('expected_purity')
    def _compute_expected_purity_master(self):
        Purity = self.env['gold.purity']

        for rec in self:
            if rec.expected_purity <= 0:
                rec.expected_purity_id = False
                continue

            purity_value = round(rec.expected_purity, 2)

            # Search existing purity
            existing = Purity.search([
                ('percentage', '=', purity_value)
            ], limit=1)

            if existing:
                rec.expected_purity_id = existing.id
            else:
                new_purity = Purity.create({
                    'name': f"{purity_value}%",
                    'percentage': purity_value,
                })
                rec.expected_purity_id = new_purity.id

    @api.depends('output_weight', 'lab_sample_weight')
    def _compute_balance_weight(self):
        for rec in self:
            rec.balance_weight = (
                rec.output_weight - rec.lab_sample_weight
                if rec.output_weight and rec.lab_sample_weight
                else rec.output_weight or 0.0
            )

    @api.depends( 'line_ids.purchase_amount')
    def _compute_total_purchase_amount(self):
        for rec in self:
            rec.total_purchase_amount = sum(rec.line_ids.mapped('purchase_amount'))


    @api.depends('output_weight', 'line_ids.fine')
    def _compute_totals(self):
        for rec in self:
            rec.total_issued_weight = sum(rec.line_ids.mapped('issue_weight'))
            rec.total_fine = sum(rec.line_ids.mapped('fine'))
            if rec.output_weight > 0:
                rec.expected_purity = ((rec.total_fine - rec.melting_loss) / rec.output_weight) * 100
            else:
                rec.expected_purity = 0

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('jewellery.refinery')
        return super().create(vals)

    @api.depends('line_ids.issue_weight')
    def _compute_total_issued_weight(self):
        for rec in self:
            rec.total_issued_weight = sum(
                rec.line_ids.mapped('issue_weight')
            )

    @api.depends('total_issued_weight', 'melting_loss')
    def _compute_output(self):
        for r in self:
            r.output_weight = r.total_issued_weight - r.melting_loss

    # def action_issue(self):
    #     self.ensure_one()
    #
    #     if self.state != 'melting':
    #         raise ValidationError(_("Melting must be completed first."))
    #
    #     Bullion = self.env['old.gold.bullion.issue']
    #
    #     # Prevent duplicate bullion creation
    #     existing = Bullion.search([
    #         ('issue_id', '=', self.id),
    #     ], limit=1)
    #
    #     if existing:
    #         return {
    #             'type': 'ir.actions.act_window',
    #             'name': _('Bullion Receipt'),
    #             'res_model': 'old.gold.bullion.issue',
    #             'res_id': existing.id,
    #             'view_mode': 'form',
    #             'target': 'current',
    #         }
    #
    #     # Total melting output (sum of issue_weight)
    #     total_weight = self.balance_weight
    #
    #     if total_weight <= 0:
    #         raise ValidationError(_("Melting output weight must be greater than zero."))
    #
    #     bullion = Bullion.create({
    #         'issue_id': self.id,
    #         'issued_weight': total_weight,
    #         'source_location_id': self.received_location_id.id,
    #         'refinery_partner_id': self.refinery_partner_id.id,
    #         'purity_id': self.expected_purity_id.id,
    #         'received_location_id': self.source_location_id.id,
    #         'purchase_per_rate': self.purchase_per_rate,
    #     })
    #     self.bullion_issue_id = bullion.id
    #
    #     # self._create_issue_mo()
    #
    #     # Update Gold Details tab: Replace Scrap Bar with Gold Bullion
    #     bullion_product = self.env.ref('em_jewellery_management.product_bullion_gold')
    #     scrap_product = self.env.ref('em_jewellery_management.product_scrap')
    #     scrap_variant = scrap_product if scrap_product._name == 'product.product' else scrap_product.product_variant_id
    #
    #     # Find scrap line and capture its details
    #     scrap_line = self.line_ids.filtered(lambda l: l.product_id.id == scrap_variant.id)
    #     if scrap_line:
    #         purity_id = scrap_line.purity_id.id
    #         weight = scrap_line.issue_weight
    #         scrap_line.unlink()
    #
    #         # Add Bullion line
    #         self.env['old.gold.refinery.issue.line'].create({
    #             'issue_id': self.id,
    #             'product_id': scrap_variant.id,
    #             'purity_id': purity_id,
    #             'issue_weight': weight,
    #             'purchase_amount': 0.0,
    #         })
    #
    #     self.state = 'issued'


    def action_melting(self):
        # picking = self.env['stock.picking'].create({
        #     'picking_type_id': self.env.ref('stock.picking_type_internal').id,
        #     'location_id': self.received_location_id.id,
        #     'location_dest_id': self.source_location_id.id,
        #     'origin': self.name,
        #     'is_old_gold': True,
        #     'old_gold_issue_id': self.id,
        #     'lab_purity_id': self.lab_purity_id.id,
        # })

        # Use scrap bar product (MO finished product) for the melting return transfer
        product_scrap = self.env.ref('em_jewellery_management.product_scrap')
        scrap_variant = product_scrap if product_scrap._name == 'product.product' \
            else product_scrap.product_variant_id
        purity = self.expected_purity_id or (self.line_ids[0].purity_id if self.line_ids else False)

        # self.env['stock.move'].create({
        #     'product_id': scrap_variant.id,
        #     'product_uom_qty': self.output_weight,
        #     'name': scrap_variant.name,
        #     'product_uom': self.env.ref('uom.product_uom_gram').id,
        #     'location_id': picking.location_id.id,
        #     'location_dest_id': picking.location_dest_id.id,
        #     'picking_id': picking.id,
        #     'purity_id': self.expected_purity_id.id,
        # })
        #
        # for move_line in picking.move_line_ids:
        #     move_line.qty_done = move_line.product_uom_qty
        #
        # picking.button_validate()
        self.state = 'melting'

        # Produce finished product in MO if linked
        if self.mo_id:
            self.mo_id.write({
                'product_qty': self.output_weight,
                'total_grams': self.output_weight,
            })
            for move in self.mo_id.move_finished_ids:
                move.product_uom_qty = self.output_weight

            if self.mo_id.state == 'draft':
                self.mo_id.action_confirm()

            self.mo_id.button_mark_done()

        # Replace old gold lines with scrap bar in Gold Details tab after melting done
        product_scrap = self.env.ref('em_jewellery_management.product_scrap')
        scrap_variant = product_scrap if product_scrap._name == 'product.product' \
            else product_scrap.product_variant_id

        # Capture values BEFORE deleting lines — computed fields recompute to 0 once lines are gone
        scrap_weight = self.output_weight  # total_issued_weight - melting_loss - lab_sample
        purity = self.expected_purity_id
        if not purity and self.line_ids:
            purity = self.line_ids[0].purity_id
            
        total_purchase_amount = sum(self.line_ids.mapped('purchase_amount'))

        # Remove existing old gold lines (all lines except any existing scrap bar)
        old_lines = self.line_ids.filtered(
            lambda l: l.product_id.id != scrap_variant.id
        )
        if old_lines:
            old_lines.unlink()
        # except Exception:
        #     # If lines are referenced by another model, zero them out instead
        #     old_lines.write({'issue_weight': 0.0, 'purchase_amount': 0.0})

        # Add scrap bar line if not already present
        already_exists = self.line_ids.filtered(
            lambda l: l.product_id.id == scrap_variant.id
        )
        if not already_exists:
            self.env['old.gold.refinery.issue.line'].create({
                'issue_id': self.id,
                'product_id': scrap_variant.id,
                'purity_id': purity.id if purity else False,
                'issue_weight': scrap_weight,
                'purchase_amount': total_purchase_amount,
            })
        else:
            already_exists.purchase_amount = total_purchase_amount



    def action_to_melting(self):
        # picking = self.env['stock.picking'].create({
        #     'picking_type_id': self.env.ref('stock.picking_type_internal').id,
        #     'location_id': self.source_location_id.id,
        #     'location_dest_id': self.received_location_id.id,
        #     'origin': self.name,
        #     'is_old_gold': True,
        #     'old_gold_issue_id': self.id,
        #     'lab_purity_id': self.lab_purity_id.id,
        # })
        #
        # # Create one stock move per gold details line — mirrors MO raw material components
        # product_old_gold = self.env.ref('em_jewellery_management.product_old_gold')
        # uom_gram = self.env.ref('uom.product_uom_gram')
        # for line in self.line_ids:
        #     self.env['stock.move'].create({
        #         'product_id': line.product_id.id or product_old_gold.id,
        #         'product_uom_qty': line.issue_weight,
        #         'name': line.product_id.name or product_old_gold.name,
        #         'product_uom': uom_gram.id,
        #         'location_id': picking.location_id.id,
        #         'location_dest_id': picking.location_dest_id.id,
        #         'picking_id': picking.id,
        #         'purity_id': self.expected_purity_id.id,
        #     })
        #
        # for move_line in picking.move_line_ids:
        #     move_line.qty_done = move_line.product_uom_qty

        # picking.button_validate()

        if not self.source_location_id:
           raise ValidationError(_("Choose source location"))
        if not self.received_location_id:
            raise ValidationError(_("Choose Received location"))

        self.state = 'to_melting'
        
        # Create Manufacturing Order when moving to melting
        self._create_manufacturing_order()

    def _create_manufacturing_order(self):
        """Create a single MO for the refinery issue.
        
        Finished product (IN): Gold Bullion — produced from melting
        Component (OUT): Old Gold — consumed in the melting process
        """
        MRP = self.env['mrp.production']
        product_scrap = self.env.ref('em_jewellery_management.product_scrap')
        product_old_gold = self.env.ref('em_jewellery_management.product_old_gold')
        uom_gram = self.env.ref('uom.product_uom_gram')

        if not self.line_ids:
            return False

        # Old Gold is consumed from source_location_id
        # Bullion is produced into the same location
        mo_location = self.source_location_id
        if not mo_location or mo_location.usage != 'internal':
            mo_location = self.env.ref('em_jewellery_management.loc_refinery')

        # Build raw material lines — one per purity line (Old Gold consumed)
        move_raw_ids = []
        for line in self.line_ids:
            move_raw_ids.append((0, 0, {
                'product_id': line.product_id.id or product_old_gold.id,
                'product_uom': uom_gram.id,
                'product_uom_qty': line.issue_weight,
                'grams': line.issue_weight,
                'purity_id': line.purity_id.id,
                'name': f"{line.product_id.name or 'Old Gold'} {line.purity_id.name}",
            }))

        # Finished product qty = balance_weight (melted output - lab sample)
        finished_qty = self.output_weight or sum(self.line_ids.mapped('issue_weight'))

        mo = MRP.create({
            'product_id': product_scrap.id,
            'product_uom_id': uom_gram.id,
            'product_qty': finished_qty,
            'total_grams': finished_qty,
            'purity_id': self.expected_purity_id.id or self.line_ids[0].purity_id.id,
            'move_raw_ids': move_raw_ids,
            'date_start': fields.Datetime.now(),
            'location_src_id': self.source_location_id.id,
            'location_dest_id': self.received_location_id.id,
            'origin': self.name,
        })

        mo.action_confirm()
        self.mo_id = mo.id

        # Link back to batches
        batches = self.env['old.gold.batch'].search([('refinery_issue_id', '=', self.id)])
        if batches:
            batches.write({'mo_id': mo.id})

        return mo

    def _create_issue_mo(self):
        """Create MO when issuing to refinery.

        Finished product : Gold Bullion
        Component        : Scrap Bar (from Gold Details scrap bar line)
        """
        MRP = self.env['mrp.production']
        product_bullion = self.env.ref('em_jewellery_management.product_bullion_gold')
        product_scrap = self.env.ref('em_jewellery_management.product_scrap')
        scrap_variant = product_scrap if product_scrap._name == 'product.product' \
            else product_scrap.product_variant_id
        uom_gram = self.env.ref('uom.product_uom_gram')

        mo_location = self.source_location_id
        if not mo_location or mo_location.usage != 'internal':
            mo_location = self.env.ref('em_jewellery_management.loc_refinery')

        # Use balance weight for MO quantity
        scrap_line = self.line_ids.filtered(
            lambda l: l.product_id.id == scrap_variant.id
        )
        scrap_weight = self.balance_weight
        purity = self.expected_purity_id or (scrap_line.purity_id if scrap_line else False)

        move_raw_ids = [(0, 0, {
            'product_id': scrap_variant.id,
            'product_uom': uom_gram.id,
            'product_uom_qty': scrap_weight,
            'grams': scrap_weight,
            'purity_id': purity.id if purity else False,
            'name': f'Scrap Bar {purity.name if purity else ""}',
        })]

        issue_mo = MRP.create({
            'product_id': product_bullion.id,
            'product_uom_id': uom_gram.id,
            'product_qty': scrap_weight,
            'total_grams': scrap_weight,
            'purity_id': purity.id if purity else False,
            'move_raw_ids': move_raw_ids,
            'date_start': fields.Datetime.now(),
            'location_src_id': self.source_location_id.id,
            'location_dest_id': self.received_location_id.id,
            'origin': self.name,
        })

        issue_mo.action_confirm()
        self.mo_id = issue_mo.id

        return issue_mo

    def action_view_transfers(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Transfers',
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('old_gold_issue_id', '=', self.id)],
        }

    # def action_bullion_reciept(self):
    #     self.ensure_one()
    #
    #     if self.state != 'melting':
    #         raise ValidationError(_("Melting must be completed first."))
    #
    #     Bullion = self.env['old.gold.bullion.receipt']
    #
    #     # Prevent duplicate bullion creation
    #     existing = Bullion.search([
    #         ('issue_id', '=', self.id),
    #     ], limit=1)
    #
    #     if existing:
    #         return {
    #             'type': 'ir.actions.act_window',
    #             'name': _('Bullion Receipt'),
    #             'res_model': 'old.gold.bullion.receipt',
    #             'res_id': existing.id,
    #             'view_mode': 'form',
    #             'target': 'current',
    #         }
    #
    #     # Total melting output (sum of issue_weight)
    #     total_weight = self.output_weight
    #
    #     if total_weight <= 0:
    #         raise ValidationError(_("Melting output weight must be greater than zero."))
    #
    #     bullion = Bullion.create({
    #         'issue_id': self.id,
    #         'received_weight': total_weight,
    #         'source_location_id': self.source_location_id.id,
    #     })
    #     self.bullion_receipt_id = bullion.id
    #
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'name': _('Bullion Receipt'),
    #         'res_model': 'old.gold.bullion.receipt',
    #         'res_id': bullion.id,
    #         'view_mode': 'form',
    #         'target': 'current',
    #     }
    def action_view_receipt(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Receipt'),
            'res_model': 'old.gold.bullion.receipt',
            'view_mode': 'tree,form',
            'domain': [
                ('issue_id', '=', self.id),
            ],
        }
    def action_view_issue(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('issue'),
            'res_model': 'old.gold.bullion.issue',
            'view_mode': 'tree,form',
            'domain': [
                ('issue_id', '=', self.id),
            ],
        }
    def action_view_transfers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Transfers',
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('old_gold_issue_id', '=', self.id)],
        }


class OldGoldRefineryIssueLine(models.Model):
    _name = 'old.gold.refinery.issue.line'

    issue_id = fields.Many2one(
        'old.gold.refinery.issue',
        ondelete='cascade'
    )

    purity_id = fields.Many2one('gold.purity', required=True)
    product_id = fields.Many2one(
        'product.product',
        string="Product",
        default=lambda self: self.env.ref(
            'em_jewellery_management.product_old_gold', raise_if_not_found=False
        ),
    )
    issue_weight = fields.Float(required=True,digits=(16, 3))
    fine = fields.Float(
        string="Fine Weight",
        compute="_compute_fine",
        store=True,
        digits=(16, 3)
    )
    purchase_amount =fields.Float()

    @api.depends('issue_weight', 'purity_id')
    def _compute_fine(self):
        for line in self:
            if line.purity_id and line.purity_id.percentage:
                line.fine = line.issue_weight * line.purity_id.percentage / 100
