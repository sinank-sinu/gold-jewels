from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class JewelleryIssueVoucher(models.Model):
    _name = 'jewellery.issue.voucher'
    _description = 'Issue Voucher'
    _order = 'create_date desc'

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

    name = fields.Char(string='Issue Voucher Number', copy=False, readonly=True, default='New')
    job_work_id = fields.Many2one('jewellery.job.work', string="Job Work")
    job_worker_id = fields.Many2one('res.partner', string="Job Worker")
    refinery_id = fields.Many2one('res.partner', string="Refinery")
    line_ids = fields.One2many('jewellery.issue.voucher.line', 'voucher_id')
    state = fields.Selection([
        ('draft', 'Draft'),
        ("waiting_department_approval", "Waiting Department Approval"),
        ("waiting_ir_approval", "Waiting IR Approval"),
        ("approved", "Approved"),
        ('done', 'Done')
    ], default='draft')
    total_net_weight = fields.Float(
        string="Total Net Weight (g)",
        compute="_compute_total_net_weight",
        digits=(16, 3)
        # store=True
    )
    source_location_id = fields.Many2one('stock.location',
                                         default=lambda self: self.env.user.branch_id.branch_location_id.id)
    received_location_id = fields.Many2one('stock.location', string="Vendor Location",
                                         compute="_compute_received_location_id", store=True, readonly=False)
    picking_id = fields.Many2one('stock.picking', readonly=True)
    confirmed_by_id = fields.Many2one("res.users", string="Confirmation Person")
    department_manager_id = fields.Many2one("res.users", string="Department Head")
    approved_id = fields.Many2one("res.users", string="Approval Authority")
    confirmed_date = fields.Date(string="Confirmation Date")
    department_approval_date = fields.Date(string="Department Approval Date")
    approved_date = fields.Date(string="Approved Date")
    total_fine_weight = fields.Float(string="Total Fine Weight", digits=(16, 3), compute="_compute_total_fine_weight", store=True)
    used_fine_weight = fields.Float(
        string="Used Fine Weight",
        compute="_compute_fine_weights",
        store=True,
        digits=(16, 3)
    )

    remaining_fine_weight = fields.Float(
        string="Remaining Fine Weight",
        compute="_compute_fine_weights",
        store=True,
        digits=(16, 3)
    )

    is_refinery = fields.Boolean(string="Is Refinery")

    order_date = fields.Date(
        string="Order Date",
        default=fields.Date.today
    )
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('is_refinery', 'job_worker_id', 'refinery_id')
    def _compute_received_location_id(self):
        for rec in self:
            if not rec.is_refinery:
                rec.received_location_id = rec.job_worker_id.property_stock_supplier.id
            elif not rec.received_location_id:
                rec.received_location_id = rec.refinery_id.property_stock_supplier.id


    @api.depends('line_ids.fine_weight', 'is_refinery', 'job_work_id.total_fine_weight')
    def _compute_total_fine_weight(self):
        for rec in self:
            if rec.is_refinery:
                rec.total_fine_weight = sum(rec.line_ids.mapped('fine_weight'))
            elif rec.job_work_id:
                rec.total_fine_weight = rec.job_work_id.total_fine_weight
            else:
                rec.total_fine_weight = 0.0

    @api.depends('line_ids.remaining_fine_weight', 'line_ids.received_fine_weight', 'line_ids.remaining_lab_fine_weight', 'line_ids.received_lab_fine_weight')
    def _compute_fine_weights(self):
        for rec in self:
            rec.used_fine_weight = sum(rec.line_ids.mapped('received_fine_weight')) + sum(rec.line_ids.mapped('received_lab_fine_weight'))
            rec.remaining_fine_weight = sum(rec.line_ids.mapped('remaining_fine_weight')) + sum(rec.line_ids.mapped('remaining_lab_fine_weight'))

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('jewellery.issue.voucher') or 'New'
        return super().create(vals)

    def action_update_lab_purity(self):
        print('update_lab_purity')
        """Update lab_weight, lab_purity (%) and lab_purity_id on all lines
        that have a linked refinery_issue_id, pulling values from the
        refinery issue's lab test results."""
        self.ensure_one()
        for line in self.line_ids:
            issue = line.refinery_issue_id
            if not issue:
                continue

            # lab_weight from refinery issue lab sample weight
            line.lab_weight = issue.lab_sample_weight

            # lab_purity (float %) from refinery issue lab purity percent
            line.lab_purity = issue.lab_purity_percent

            # lab_purity_id (Many2one gold.purity) — use expected_purity_id
            # (computed from lab results on the refinery issue)
            if issue.expected_purity_id:
                line.lab_purity_id = issue.expected_purity_id
            # elif issue.lab_purity_percent:
            #     # Fallback: find matching gold.purity by percentage
            #     purity = self.env['gold.purity'].search(
            #         [('percentage', '=', round(issue.lab_purity_percent, 2))], limit=1
            #     )
            #     line.lab_purity_id = purity if purity else False

    def action_done(self):
        """Confirm the Issue Voucher and create / update stock moves.

        - First-time confirm: create a new internal picking and validate it.
        - Re-confirm after Edit: the original picking_id already exists.
          Instead of creating a new picking we directly adjust stock.quant
          records at both locations using the quantity delta (new qty - old
          qty), then update the original move quantities to reflect the
          change.  This works even when on-hand stock is zero.
        """
        uom_gram = self.env.ref('uom.product_uom_gram')

        # ── Re-confirm after Edit ──────────────────────────────────────────
        if self.picking_id and self.picking_id.state == 'done':
            Quant = self.env['stock.quant'].sudo()
            for line in self.line_ids:
                new_qty = line.qty if self.is_refinery else line.gross_weight
                product  = line.product_id

                # Find the corresponding move on the original picking
                old_move = self.picking_id.move_ids.filtered(
                    lambda m: m.product_id == product
                )
                old_qty = sum(old_move.mapped('product_uom_qty')) if old_move else 0.0
                delta = new_qty - old_qty

                if delta:
                    # Remove delta from source (more issued → debit source)
                    src_quant = Quant.search([
                        ('product_id', '=', product.id),
                        ('location_id', '=', self.source_location_id.id),
                    ], limit=1)
                    if src_quant:
                        src_quant.quantity -= delta
                    else:
                        Quant.create({
                            'product_id': product.id,
                            'location_id': self.source_location_id.id,
                            'quantity': -delta,
                        })

                    # Add delta at destination
                    dst_quant = Quant.search([
                        ('product_id', '=', product.id),
                        ('location_id', '=', self.received_location_id.id),
                    ], limit=1)
                    if dst_quant:
                        dst_quant.quantity += delta
                    else:
                        Quant.create({
                            'product_id': product.id,
                            'location_id': self.received_location_id.id,
                            'quantity': delta,
                        })

                    # Keep stock.move and stock.move.line records in sync
                    if old_move:
                        move = old_move[0]
                        move.sudo().write({'product_uom_qty': new_qty})
                        # Update move lines: 'quantity' (Odoo 17 rename of
                        # qty_done) is what shows in the Transfer's Operations
                        # tab and affects valuation.
                        for ml in move.move_line_ids:
                            # Only 'quantity' (done qty) is writable on stock.move.line in Odoo 17
                            ml.sudo().write({'quantity': new_qty})

                if self.is_refinery and line.refinery_issue_id:
                    line.refinery_issue_id.state = 'issued'

            self.state = 'done'
            return

        # ── First-time confirm: create a new picking ───────────────────────
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', 'in', (self.company_id.id, False))
        ], limit=1)
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id or self.env.ref('stock.picking_type_internal').sudo().id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.received_location_id.id,
            'origin': self.name,
            'is_old_gold': True,
        })
        for line in self.line_ids:
            self.env['stock.move'].create({
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty if self.is_refinery else line.gross_weight,
                'name': line.product_id.name,
                'product_uom': uom_gram.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'picking_id': picking.id,
                'purity_id': line.purity_id.id,
            })
            if self.is_refinery and line.refinery_issue_id:
                line.refinery_issue_id.state = 'issued'

        picking.action_confirm()
        picking.action_assign()
        for move_line in picking.move_line_ids:
            # Read qty from parent stock.move (product_uom_qty is invalid on move.line in Odoo 17)
            move_line.quantity = move_line.move_id.product_uom_qty
            move_line.picked = True

        picking.with_context(skip_backorder=True).button_validate()

        self.picking_id = picking.id
        self.state = 'done'
        if self.job_work_id:
            self.job_work_id.state = 'issued'

    def action_create_receive_voucher(self):
        self.ensure_one()
        lines = []
        # Check both refinery and lab balances
        lines_to_receive = self.line_ids.filtered(lambda l: (l.remaining_fine_weight + l.remaining_lab_fine_weight) > 0.001)
        if not lines_to_receive:
            raise ValidationError(_("No remaining fine weight to receive for this voucher."))

        company = self.branch_id.company_id or self.company_id or self.env.company
        Product = self.env['product.product'].with_company(company)
        bullion_product = Product.search([
            ('is_bullion_product', '=', True),
            ('company_id', '=', company.id),
        ], limit=1)
        if not bullion_product:
            canonical_bullion = self.env.ref(
                'em_jewellery_management.product_bullion_gold',
                raise_if_not_found=False,
            )
            if canonical_bullion and canonical_bullion.company_id in (False, company):
                bullion_product = canonical_bullion
        if not bullion_product:
            raise ValidationError(_("No bullion product is configured for company %s.") % company.display_name)

        for line in lines_to_receive:
            # lab_purity is now Many2one; get percentage from it for weight calculation
            purity_record = line.lab_purity or line.purity_id
            purity_pct = purity_record.percentage if purity_record else 0.0

            # Add Refinery Balance Line
            if line.remaining_fine_weight > 0.001:
                lines.append((0, 0, {
                    'product_id': bullion_product.id,
                    'product_template_id': bullion_product.product_tmpl_id.id,
                    'purity_id': line.purity_id.id,
                    'is_lab_line': False,
                    'lab_tester_id': line.lab_tester_id.id,
                    'stone_weight': 0.0,
                    'uom_id': line.uom_id.id,
                    'issue_voucher_line_id': line.id,
                    'fine_gms_price': line.fine_gms_price,
                    'fine_issue_amount': line.fine_issue_amount,
                    'lab_purity': line.lab_purity.id if line.lab_purity else False,
                    'gross_weight': line.remaining_fine_weight / (purity_pct / 100) if purity_pct else line.remaining_fine_weight,
                }))

            # Add Lab Balance Line
            if line.remaining_lab_fine_weight > 0.001:
                lines.append((0, 0, {
                    'product_id': bullion_product.id,
                    'product_template_id': bullion_product.product_tmpl_id.id,
                    'purity_id': line.purity_id.id,
                    'is_lab_line': True,
                    'lab_tester_id': line.lab_tester_id.id,
                    'stone_weight': 0.0,
                    'uom_id': line.uom_id.id,
                    'issue_voucher_line_id': line.id,
                    'fine_gms_price': line.fine_gms_price,
                    'fine_issue_amount': line.fine_issue_amount,
                    'lab_purity': line.lab_purity.id if line.lab_purity else False,
                    'gross_weight': line.remaining_lab_fine_weight / (purity_pct / 100) if purity_pct else line.remaining_lab_fine_weight,
                }))

        voucher = self.env['jewellery.receive.voucher'].create({
            'job_work_id': self.job_work_id.id if self.job_work_id else False,
            'job_worker_id': self.job_worker_id.id if self.job_worker_id else self.refinery_id.id,
            'refinery_id': self.refinery_id.id if self.is_refinery else False,
            'is_refinery': self.is_refinery,
            'issue_voucher_id': self.id,
            'branch_id': self.branch_id.id,
            'company_id': company.id,
            'line_ids': lines,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'jewellery.receive.voucher',
            'view_mode': 'form',
            'res_id': voucher.id,
            'target': 'current',
        }

    receive_voucher_ids = fields.One2many('jewellery.receive.voucher', 'issue_voucher_id')
    receive_count = fields.Integer(compute='_compute_receive_count')

    def _compute_receive_count(self):
        for rec in self:
            rec.receive_count = len(rec.receive_voucher_ids)

    def action_view_receive_vouchers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Receive Vouchers'),
            'res_model': 'jewellery.receive.voucher',
            'view_mode': 'tree,form',
            'domain': [('issue_voucher_id', '=', self.id)],
        }

    def action_view_bullion_transfers(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Bullion Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [
                ('id', '=', self.picking_id.id),
            ],

        }

    def action_dept_approve(self):
        self.write(
            {
                "state": "waiting_ir_approval",
                "department_manager_id": self.env.user.id,
                "department_approval_date": fields.Date.context_today(self),
            }
        )

        # Add components to MO from requisition when department approves
        mo = self.job_work_id.mo_id if self.job_work_id else False
        uom_gram = self.env.ref('uom.product_uom_gram')
        if mo and self.job_work_id and self.job_work_id.requisition_id:
            move_raw_ids = []
            for req_line in self.line_ids:
                move_raw_ids.append((0, 0, {
                    'product_id': req_line.product_id.id,
                    'product_uom': req_line.product_id.uom_id.id or uom_gram.id,
                    'product_uom_qty': req_line.fine_weight,
                    'grams': req_line.fine_weight,
                    'purity_id': req_line.purity_id.id,
                    'name': req_line.product_id.name,
                    'raw_material_production_id': mo.id,
                    'location_id': mo.location_src_id.id,
                    'location_dest_id': mo.product_id.with_company(mo.company_id).property_stock_production.id,
                }))
            if move_raw_ids:
                # Add moves to the MO
                self.env['stock.move'].create([vals[2] for vals in move_raw_ids])

    def action_approve(self):
        self.write(
            {
                "state": "approved",
                "approved_id": self.env.user.id,
                "approved_date": fields.Date.context_today(self),
            }
        )

    def action_edit_voucher(self):
        """Reset a 'done' Issue Voucher back to 'approved' for editing.

        No stock operations are performed here. The original picking
        remains as-is.  When the user re-confirms (action_done), stock
        quants are adjusted in place using the quantity delta.
        Editing is allowed even when Receive Vouchers exist.
        """
        self.ensure_one()

        # Simply reset state — no stock reversal needed.
        # action_done will handle the delta adjustment on re-confirm.
        self.state = 'approved'

        # Reset refinery issue states: 'melting' is the state before 'issued'
        if self.is_refinery:
            for line in self.line_ids:
                if line.refinery_issue_id and line.refinery_issue_id.state == 'issued':
                    line.refinery_issue_id.state = 'melting'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Voucher Unlocked for Editing'),
                'message': _('Issue Voucher has been reset to Approved. '
                             'Update quantities and click Confirm to apply.'),
                'type': 'success',
                'sticky': False,
            },
        }

    total_net_weight = fields.Float(
        string="Total Net Weight (g)",
        compute="_compute_total_net_weight",
        digits=(16, 3)
    )

    def _compute_total_net_weight(self):
        for voucher in self:
            voucher.total_net_weight = sum(
                voucher.line_ids.mapped('issued_weight')
            )


class JewelleryIssueVoucherLine(models.Model):
    _name = 'jewellery.issue.voucher.line'
    _rec_name = 'name'

    voucher_id = fields.Many2one('jewellery.issue.voucher', required=True)
    name = fields.Char(string='Line Name', compute='_compute_line_name', store=True)

    @api.depends('voucher_id.name', 'product_id.name', 'fine_weight')
    def _compute_line_name(self):
        for line in self:
            name = f"{line.voucher_id.name or ''} - {line.product_id.name or ''} ({line.fine_weight}g)"
            line.name = name

    product_id = fields.Many2one('product.product')
    product_template_id = fields.Many2one(
        string="Product Template",
        comodel_name='product.template')

    issued_weight = fields.Float(string="Issued Weight (g)", digits=(16, 3))
    qty = fields.Float(string="Net Weight", compute="_compute_qty", store=True, digits=(16, 3), readonly=False)
    gross_weight = fields.Float(string="Gross Weight (g)", compute="_compute_gross_weight", digits=(16, 3))
    stone_weight = fields.Float(string="Stone Weight (g)", digits=(16, 3))
    lab_weight = fields.Float(string="Lab Weight (g)", store=True, digits=(16, 3))
    lab_purity = fields.Float(string="Lab Purity (%)", store=True)
    lab_purity_id = fields.Many2one('gold.purity', string="Lab Purity", store=True)


    refinery_issue_id = fields.Many2one('old.gold.refinery.issue', string="Refinery Issue")
    diamond_weight = fields.Float(string="Diamond Weight (g)", digits=(16, 3))
    uom_id = fields.Many2one('uom.uom', string="UoM")
    purity_id = fields.Many2one('gold.purity', string="Purity")
    fine_weight = fields.Float(string="Fine Weight (g)", digits=(16, 3), compute="_compute_fine_weight", store=True,
                               readonly=False)
    
    lab_fine_weight = fields.Float(string="Lab Fine Weight", compute="_compute_lab_fine_weight", store=True, digits=(16, 3))
    refinery_fine_weight = fields.Float(string="Refinery Fine Weight", compute="_compute_lab_fine_weight", store=True, digits=(16, 3))
    received_lab_fine_weight = fields.Float(string="Received Lab Fine Weight", digits=(16, 3))
    remaining_lab_fine_weight = fields.Float(string="Remaining Lab Fine Weight", compute="_compute_lab_fine_weight", store=True, digits=(16, 3))
    no_of_pieces = fields.Integer(
        string="No. of Pieces",
        default=1
    )
    purchase_making_charge_value = fields.Float(string="Purchase Making Charge")
    purchase_price_per_gram = fields.Float(string="Purchase fine Rate / gram")

    purchase_making_charge_amount = fields.Float(
        string="Purchase Making Charge Amount",
        compute="_compute_purchase_making_charge",
        store=True
    )
    mc_fine = fields.Float(string="MC Fine", digits=(16, 3))
    lab_tester_id = fields.Many2one('res.partner', string="Lab Tester")


    fine_gms_price = fields.Float(string="Fine GMS Price")
    fine_issue_amount = fields.Float(string="Fine Amount")

    gram_range_id = fields.Many2one(
        'gold.gram.range',
        string="Gram Range"
    )

    receive_line_ids = fields.One2many('jewellery.receive.voucher.line', 'issue_voucher_line_id', string="Receive Voucher Lines")
    received_fine_weight = fields.Float(string="Received Fine Weight", compute="_compute_received_fine_weight", digits=(16, 3), store=True)
    remaining_fine_weight = fields.Float(string="Remaining Fine Weight", compute="_compute_received_fine_weight", digits=(16, 3), store=True)

    @api.depends('receive_line_ids.fine_weight', 'receive_line_ids.voucher_id.state', 'receive_line_ids.is_lab_line', 
                 'receive_line_ids.net_weight', 'receive_line_ids.gross_weight', 'receive_line_ids.purity_id', 
                 'receive_line_ids.lab_purity', 'refinery_fine_weight', 'lab_fine_weight')
    def _compute_received_fine_weight(self):
        for line in self:
            # Regular (Refinery) receipts
            refinery_received = sum(line.receive_line_ids.filtered(
                lambda r: r.voucher_id.state == 'done' and not r.is_lab_line
            ).mapped('fine_weight'))
            line.received_fine_weight = refinery_received
            line.remaining_fine_weight = line.refinery_fine_weight - refinery_received
            
            # Lab receipts
            lab_received = sum(line.receive_line_ids.filtered(
                lambda r: r.voucher_id.state == 'done' and r.is_lab_line
            ).mapped('fine_weight'))
            # line.received_lab_fine_weight = lab_received # Field already exists in model
            line.remaining_lab_fine_weight = line.lab_fine_weight - lab_received
            # Actually, I should update received_lab_fine_weight too if it was manual before
            line.received_lab_fine_weight = lab_received

    @api.depends('lab_weight', 'lab_purity', 'lab_purity_id', 'lab_purity_id.percentage', 'purity_id.percentage', 'fine_weight', 'received_lab_fine_weight')
    def _compute_lab_fine_weight(self):
        for line in self:
            purity = line.lab_purity or (line.lab_purity_id.percentage if line.lab_purity_id else (line.purity_id.percentage if line.purity_id else 0.0))
            line.lab_fine_weight = line.lab_weight * (purity / 100)
            # line.refinery_fine_weight = line.fine_weight - line.lab_fine_weight
            # line.remaining_lab_fine_weight = line.lab_fine_weight - line.received_lab_fine_weight

    @api.onchange('product_id', 'product_template_id', 'qty')
    def _onchange_product_pricing(self):
        # Suggest fine_issue_amount based on product price if not set
        if not self.fine_issue_amount or self.env.context.get('force_recompute_price'):
            price = self.product_id.standard_price or self.product_template_id.standard_price or 0.0
            self.fine_issue_amount = self.qty * price
        
        # Suggest fine_gms_price based on amount and weight if not set
        if (not self.fine_gms_price or self.env.context.get('force_recompute_price')) and self.fine_weight:
            self.fine_gms_price = self.fine_issue_amount / self.fine_weight

    @api.depends('issued_weight', 'lab_weight', 'voucher_id.is_refinery', 'fine_weight', 'purity_id.percentage')
    def _compute_qty(self):
        for rec in self:
            if rec.voucher_id.is_refinery:
                # Refinery logic
                rec.qty = rec.issued_weight - rec.lab_weight
            else:
                # Non-refinery logic
                if rec.fine_weight and rec.purity_id and rec.purity_id.percentage:
                    rec.qty = rec.fine_weight / (rec.purity_id.percentage / 100)
                else:
                    rec.qty = 0.0





    @api.depends('issued_weight', 'lab_purity', 'lab_purity_id', 'lab_purity_id.percentage', 'voucher_id.is_refinery', 'qty', 'purity_id.percentage')
    def _compute_fine_weight(self):
        for rec in self:
            if rec.voucher_id.is_refinery:
                purity = rec.purity_id or (rec.purity_id.percentage if rec.purity_id else 0.0)
                rec.fine_weight = rec.issued_weight * (purity / 100)

    @api.depends('issued_weight', 'stone_weight')
    def _compute_gross_weight(self):
        for rec in self:
            if rec.voucher_id.is_refinery:
              rec.gross_weight = (rec.issued_weight + rec.stone_weight)
            else:
              rec.gross_weight = (rec.qty + rec.stone_weight)

    @api.depends(
        'purchase_making_charge_value',
        'mc_fine',
    )
    def _compute_purchase_making_charge(self):
        for rec in self:
            rec.purchase_making_charge_amount = rec.mc_fine * rec.purchase_price_per_gram

    @api.onchange('product_id')
    def onchange_product_id(self):
        if not self.voucher_id.is_refinery and self.product_id:
            self.product_template_id = self.product_id.product_tmpl_id.id
            self.uom_id = self.product_id.uom_id.id
            self.purity_id = self.product_id.sale_purity_id.id

    @api.onchange('refinery_issue_id')
    def onchange_refinery_issue_id(self):
        if self.refinery_issue_id:
            if self.refinery_issue_id.line_ids:
                line = self.refinery_issue_id.line_ids[0]
                self.product_id = line.product_id.id
                self.product_template_id = line.product_id.product_tmpl_id.id
                # Use expected_purity_id (computed output purity) instead of line's raw input purity
                self.purity_id = self.refinery_issue_id.expected_purity_id.id or line.purity_id.id
                self.issued_weight = self.refinery_issue_id.balance_weight
            else:
                self.issued_weight = self.lab_weight

    #
    @api.constrains('fine_weight')
    def _check_fine_limit(self):
        for line in self:
            if line.voucher_id and not line.voucher_id.is_refinery:
                total_lines = sum(
                    line.voucher_id.line_ids.mapped('fine_weight')
                )
                if float_compare(total_lines, line.voucher_id.total_fine_weight, precision_digits=3) == 1:
                    raise ValidationError(
                        _("Fine weight exceeds available total fine weight.")
                    )
