from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.populate import compute


class JewelleryReceiveVoucher(models.Model):
    _name = 'jewellery.receive.voucher'
    _description = 'Receive Voucher'
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


    name = fields.Char(string='Receive Voucher Number', copy=False, readonly=True, default='New')
    job_work_id = fields.Many2one('jewellery.job.work', string="Job Work")
    job_worker_id = fields.Many2one('res.partner', string="Job Worker")
    issue_voucher_id = fields.Many2one('jewellery.issue.voucher', string="Issue Voucher")
    refinery_id = fields.Many2one('res.partner', string="Refinery")
    is_refinery = fields.Boolean(string="Is Refinery")

    wastage_weight = fields.Float(string="Wastage Weight",digits = (16, 3))
    line_ids = fields.One2many('jewellery.receive.voucher.line', 'voucher_id')
    state = fields.Selection([
        ('draft','Draft'),
        ("waiting_department_approval", "Waiting Department Approval"),
        ("waiting_ir_approval", "Waiting IR Approval"),
        ("approved", "Approved"),
        ('done','Done')
    ], default='draft')
    active_package_line_ids = fields.One2many(
        'jewellery.receive.voucher.package.line','voucher_id',string='Package Products')
    total_net_weight = fields.Float(
        string="Total Net Weight (g)",
        compute="_compute_total_net_weight",
        digits=(16, 3),
        store=True
    )
    confirmed_by_id = fields.Many2one("res.users", string="Confirmation Person")
    department_manager_id = fields.Many2one("res.users", string="Department Head")
    approved_id = fields.Many2one("res.users", string="Approval Authority")
    confirmed_date = fields.Date(string="Confirmation Date")
    department_approval_date = fields.Date(string="Department Approval Date")
    approved_date = fields.Date(string="Approved Date")
    # job_type = fields.Selection([
    #     ('gold_only', 'Gold Only'),
    #     ('gold_alloy', 'Gold + Alloy')
    # ],required=False)
    job_type_selection = fields.Selection([
        ('gold_only', 'Gold Only'),
        ('gold_alloy', 'Gold + Alloy')
    ], required=False)

    making_charge_type = fields.Selection([
        ('percent', 'Percentage'),
        ('amount', 'Amount'),
        ('rate_per_gram', 'Rate Per Gram')
    ], string="MC Type", default='percent')
    mc_percent = fields.Float(string="MC%")
    rate_value = fields.Float(string="Rate(g)")
    making_charge_value = fields.Float(string="Amount(mc)")
    fine_rate = fields.Float(string="Fine Rate (g)", help="Gold rate per gram used to compute MC Amount from MC Fine")

    total_fine_weight = fields.Float(
        string="Total Fine Weight",
        compute="_compute_total_fine_weight",
        store=True,
        digits=(16, 3)
    )
    mc_fine = fields.Float(
        string="MC Fine",
        compute="_compute_mc_fine",
        store=True,
        digits=(16, 3),
        help="MC Fine Weight = Total Net Weight × MC%"
    )
    making_charge_amount = fields.Monetary(
        string='Making Charge',
        currency_field='currency_id',
        compute="_compute_making_charge_amount",
        readonly=False,
        store=True
    )
    making_charge_bill_id = fields.Many2one(
        'account.move', readonly=True
    )
    picking_id = fields.Many2one('stock.picking', readonly=True)
    source_location_id = fields.Many2one('stock.location', string="Source Location",
                                        compute="_compute_source_location_id", store=True, readonly=False)
    received_location_id = fields.Many2one('stock.location',
                                          domain="[('usage', '=', 'internal'), ('location_id.usage', '!=', 'internal')]",
                                          default=lambda self: self.env.user.branch_id.branch_location_id.id)
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    order_date = fields.Date(
        string="Order Date",
        default=fields.Date.today
    )
    @api.depends('total_net_weight', 'mc_percent', 'making_charge_type')
    def _compute_mc_fine(self):
        for voucher in self:
            if voucher.making_charge_type == 'percent':
                voucher.mc_fine = voucher.total_net_weight * (voucher.mc_percent / 100.0)
            else:
                voucher.mc_fine = 0.0





    @api.depends('is_refinery', 'job_worker_id', 'refinery_id')
    def _compute_source_location_id(self):
        for rec in self:
            if not rec.is_refinery:
                rec.source_location_id = rec.job_worker_id.property_stock_supplier.id
            elif not rec.source_location_id:
                rec.source_location_id = rec.refinery_id.property_stock_supplier.id


    @api.depends('line_ids.net_weight')
    def _compute_total_net_weight(self):
        for voucher in self:
            voucher.total_net_weight = sum(
                voucher.line_ids.mapped('net_weight')
            )

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('jewellery.receive.voucher') or 'New'
        return super().create(vals)


    def action_done(self):
        """Confirm the Receive Voucher and create / update stock moves.

        - First-time confirm: create a new internal picking and validate it.
        - Re-confirm after Edit (picking_id already done): directly adjust
          stock.quant records at both locations using the gross_weight delta.
          Works even when on-hand stock is zero.
        """
        uom_gram = self.env.ref('uom.product_uom_gram')

        # ── Re-confirm after Edit ──────────────────────────────────────────
        if self.picking_id and self.picking_id.state == 'done':
            Quant = self.env['stock.quant'].sudo()
            for line in self.line_ids:
                new_qty = line.gross_weight
                product = line.product_id

                # Find the corresponding move on the original picking
                old_move = self.picking_id.move_ids.filtered(
                    lambda m: m.product_id == product
                )
                old_qty = sum(old_move.mapped('product_uom_qty')) if old_move else 0.0
                delta = new_qty - old_qty

                if delta:
                    # Adjust source location (vendor/job worker)
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

                    # Adjust destination location (internal branch location)
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

            self.state = 'done'
            return

        # ── First-time confirm: create a new picking ───────────────────────
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_internal').id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.received_location_id.id,
            'origin': self.name,
            'is_old_gold': True,
        })
        for line in self.line_ids:
            price_unit = (line.total_receive_fine_amount / line.gross_weight) if line.gross_weight else 0.0
            self.env['stock.move'].create({
                'product_id': line.product_id.id,
                'product_uom_qty': line.gross_weight,
                'name': line.product_id.name,
                'product_uom': uom_gram.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'picking_id': picking.id,
                'purity_id': line.purity_id.id,
                'price_unit': price_unit,
                'receive_voucher_line_id': line.id,
            })

        picking.action_confirm()
        picking.action_assign()
        for move_line in picking.move_line_ids:
            # Read qty from parent stock.move (product_uom_qty is invalid on move.line)
            move_line.quantity = move_line.move_id.product_uom_qty

        picking.with_context(skip_backorder=True).button_validate()

        self.picking_id = picking.id
        self.state = 'done'
        if self.job_work_id:
            self.job_work_id.state = 'received'

        if self.is_refinery:
            for line in self.line_ids:
                if line.issue_voucher_line_id and line.issue_voucher_line_id.refinery_issue_id:
                    line.issue_voucher_line_id.refinery_issue_id.state = 'received'


    def action_dept_approve(self):
        self.write(
            {
                "state": "waiting_ir_approval",
                "department_manager_id": self.env.user.id,
                "department_approval_date": fields.Date.context_today(self),
            }
        )

    def action_approve(self):
        self.write(
            {
                "state": "approved",
                "approved_id": self.env.user.id,
                "approved_date": fields.Date.context_today(self),
            }
        )

    def action_edit_voucher(self):
        """Reset a 'done' Receive Voucher back to 'approved' for editing.

        No stock operations are performed here. The original picking
        remains as-is. When the user re-confirms (action_done), stock
        quants are adjusted in place using the gross_weight delta.
        """
        self.ensure_one()

        # Simply reset state — no stock reversal needed.
        # action_done handles the delta adjustment on re-confirm.
        self.state = 'approved'

        # Reset refinery issue states if applicable
        if self.is_refinery:
            for line in self.line_ids:
                if line.issue_voucher_line_id and line.issue_voucher_line_id.refinery_issue_id:
                    ri = line.issue_voucher_line_id.refinery_issue_id
                    if ri.state == 'received':
                        ri.state = 'issued'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Voucher Unlocked for Editing'),
                'message': _('Receive Voucher has been reset to Approved. '
                             'Update quantities and click Confirm to apply.'),
                'type': 'success',
                'sticky': False,
            },
        }
    def action_create_making_charge_bill(self):
        self.ensure_one()
        if not self.making_charge_amount or not self.job_worker_id:
            return False

        # Create the vendor bill
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.job_worker_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': f'Making Charge - {self.name}',
                'quantity': 1,
                'price_unit': self.making_charge_amount,
            })],
            'job_work_id': self.job_work_id.id,
        })
        if bill:
            self.making_charge_bill_id =bill.id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': bill.id,
            'target': 'new',
        }

    def action_view_making_charge_bills(self):
        """Smart button to show all making charge bills"""
        self.ensure_one()
        return {
            'name': 'Making Charge Bills',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'domain': [('job_work_id', '=', self.job_work_id.id)],
            'view_mode': 'tree,form',
            'target': 'current',
        }
    def action_view_bullion_transfers(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Ornaments Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [
                ('id', '=', self.picking_id.id),
            ],

        }
    @api.depends('line_ids.fine_weight')
    def _compute_total_fine_weight(self):
        for voucher in self:
            voucher.total_fine_weight = sum(voucher.line_ids.mapped('fine_weight'))

    @api.depends(
        'job_type_selection', 'making_charge_type', 'mc_percent',
        'making_charge_value', 'rate_value', 'total_fine_weight',
        'mc_fine', 'fine_rate', 'line_ids.mc_fine'
    )
    def _compute_making_charge_amount(self):
        for voucher in self:
            if voucher.job_type_selection == 'gold_alloy':
                if voucher.making_charge_type == 'percent':
                    # MC Amount = MC Fine × Fine Rate (gold rate per gram)
                    voucher.making_charge_amount = voucher.mc_fine * voucher.fine_rate
                elif voucher.making_charge_type == 'amount':
                    voucher.making_charge_amount = voucher.making_charge_value
                elif voucher.making_charge_type == 'rate_per_gram':
                    voucher.making_charge_amount = voucher.total_net_weight * voucher.rate_value
                else:
                    voucher.making_charge_amount = 0.0
            else:
                voucher.making_charge_amount = 0.0


class JewelleryReceiveVoucherLine(models.Model):
    _name = 'jewellery.receive.voucher.line'


    voucher_id = fields.Many2one('jewellery.receive.voucher')
    # product_id = fields.Many2one('product.template')

    product_id = fields.Many2one('product.product')
    product_template_id = fields.Many2one(
        string="Product Template",
        comodel_name='product.template')
    qty = fields.Float()
    gross_weight = fields.Float(string="Gross Weight (g)",digits=(16, 3))
    stone_weight = fields.Float(string="Stone Weight (g)",digits=(16, 3))
    diamond_weight = fields.Float(string="Diamond Weight (g)",digits=(16, 3))
    uom_id = fields.Many2one('uom.uom', string="UoM")
    purity_id = fields.Many2one('gold.purity', string="Purity")
    lab_purity = fields.Float(string="Lab Purity (%)")
    lab_purity_id = fields.Many2one('gold.purity', string="Lab Purity")
    fine_weight = fields.Float(string="Fine Weight  (g)",compute="_compute_fine_weight",digits=(16, 3))
    purchase_making_charge_value = fields.Float(string="Purchase Making Charge")
    mc_fine = fields.Float(string="MC Fine", compute="_compute_purchase_mc_fine")
    total_fine = fields.Float(string="Total Fine", compute="_compute_total_fine",digits=(16, 3))
    lab_tester_id = fields.Many2one("res.partner",string="Lab Tester")
    is_lab_line = fields.Boolean(string="Is Lab Receipt Line")

    net_weight = fields.Float(
        string="Net Weight (g)",
        compute="_compute_net_weight",
        store=True,digits=(16, 3)
    )

    fine_gms_price = fields.Float(string="Fine GMS Price", compute="_compute_fine_pricing", store=True, readonly=False)

    @api.onchange('voucher_id')
    def _onchange_voucher_id(self):
        if self.voucher_id and self.voucher_id.issue_voucher_id and not self.issue_voucher_line_id:
            # Find first line of the issue voucher that has remaining balance
            lines = self.voucher_id.issue_voucher_id.line_ids.filtered(
                lambda l: (l.remaining_fine_weight + l.remaining_lab_fine_weight) > 0.001
            )
            if lines:
                self.issue_voucher_line_id = lines[0].id
                # Trigger follow-up logic to pull defaults from this line
                self.onchange_issue_voucher_line_id()

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and self.voucher_id.is_refinery:
            if self.product_id.purity_id:
                self.purity_id = self.product_id.purity_id.id

    issue_voucher_line_id = fields.Many2one(
        'jewellery.issue.voucher.line',
        string="Issue Voucher Line",
        help="Linked issue voucher line to get issued fine amount"
    )
    fine_issue_amount = fields.Float(
        string="Fine Issue Amount",
        compute="_compute_fine_pricing",
        store=True,
        readonly=False,
    )

    @api.depends('issue_voucher_line_id')
    def _compute_fine_pricing(self):
        for rec in self:
            # Only pull from IV if currently zero or if IV line just changed (handled by depends)
            # and only if NOT clearing manually? 
            # Actually, compute will run when IV line is set.
            if rec.issue_voucher_line_id:
                if not rec.fine_gms_price or rec.env.context.get('force_recompute'):
                    rec.fine_gms_price = rec.issue_voucher_line_id.fine_gms_price
                if not rec.fine_issue_amount or rec.env.context.get('force_recompute'):
                    rec.fine_issue_amount = rec.issue_voucher_line_id.fine_issue_amount
            else:
                # If no IV line, keep existing or set to 0?
                pass

    total_receive_fine_amount = fields.Float(string="Total Fine Amount", compute="_compute_total_fine_amount", store=True)

    fine_balance_amount = fields.Float(string="Fine Balance Amount", compute="_compute_fine_balance_amount", store=True)


    @api.depends("total_receive_fine_amount", "fine_issue_amount", "issue_voucher_line_id.receive_line_ids.total_receive_fine_amount", "issue_voucher_line_id.receive_line_ids.voucher_id.state", "voucher_id.line_ids.total_receive_fine_amount")
    def _compute_fine_balance_amount(self):
        for rec in self:
            if rec.issue_voucher_line_id:
                # 1. Previous Done Vouchers (excluding the current one)
                previous_receipts = sum(rec.issue_voucher_line_id.receive_line_ids.filtered(
                    lambda r: r.voucher_id.state == 'done' and r.voucher_id.id != rec.voucher_id._origin.id
                ).mapped('total_receive_fine_amount'))
                
                # 2. Current Voucher Receipts (all lines of the same issue line in this voucher)
                current_voucher_receipts = sum(rec.voucher_id.line_ids.filtered(
                    lambda l: l.issue_voucher_line_id.id == rec.issue_voucher_line_id.id
                ).mapped('total_receive_fine_amount'))
                
                rec.fine_balance_amount = rec.fine_issue_amount - (previous_receipts + current_voucher_receipts)
            else:
                rec.fine_balance_amount = rec.fine_issue_amount - rec.total_receive_fine_amount

    @api.depends("total_fine", "fine_gms_price")
    def _compute_total_fine_amount(self):
        for rec in self:
            rec.total_receive_fine_amount = rec.total_fine * rec.fine_gms_price


    @api.depends('net_weight', 'purchase_making_charge_value')
    def _compute_purchase_mc_fine(self):
        for rec in self:
            rec.mc_fine = rec.net_weight * (rec.purchase_making_charge_value) / 100

    @api.depends('mc_fine', 'fine_weight')
    def _compute_total_fine(self):
        for rec in self:
            rec.total_fine = rec.mc_fine + rec.fine_weight

    @api.depends('net_weight', 'purity_id', 'lab_purity', 'lab_purity_id', 'lab_purity_id.percentage', 'voucher_id.is_refinery')
    def _compute_fine_weight(self):
        for rec in self:
            purity = rec.lab_purity or (rec.lab_purity_id.percentage if rec.lab_purity_id else (rec.purity_id.percentage if rec.purity_id else 0.0))
            rec.fine_weight = rec.net_weight * (purity) / 100

    @api.depends(
        'gross_weight',
        'stone_weight',
        'diamond_weight'
    )
    def _compute_net_weight(self):
        for rec in self:
            rec.net_weight = (
                    rec.gross_weight
                    - rec.stone_weight
                    - rec.diamond_weight
            )

    @api.onchange('issue_voucher_line_id')
    def onchange_issue_voucher_line_id(self):
        if self.issue_voucher_line_id:
            line = self.issue_voucher_line_id
            self.product_id = line.product_id.id
            self.product_template_id = line.product_template_id.id
            self.uom_id = line.uom_id.id
            # Price and amount are now handled by _compute_fine_pricing

    def action_done(self):
        # self.ensure_one()
        #
        # if self.state != 'draft':
        #     return
        #
        # picking = self.env['stock.picking'].create({
        #     'picking_type_id': self.env.ref('stock.picking_type_internal').id,
        #     'location_id': self.source_location_id.id,
        #     'location_dest_id': self.received_location_id.id,
        #     'origin': self.name,
        #     'is_old_gold': True,
        # })
        # for rec in self.line_ids:
        #
        #     self.env['stock.move'].create({
        #         'product_id': rec.product_id.id,
        #         'product_uom_qty': rec.received_weight,
        #         'name': 'Bullion Gold',
        #         'product_uom': self.env.ref('uom.product_uom_gram').id,
        #         'location_id': picking.location_id.id,
        #         'location_dest_id': picking.location_dest_id.id,
        #         'picking_id': picking.id,
        #         'purity_id': self.purity_id.id,
        #     })
        #
        # for move_line in picking.move_line_ids:
        #     move_line.qty_done = move_line.product_uom_qty
        #
        # picking.button_validate()
        #
        # picking.button_validate()
        #
        # self.picking_id = picking.id
        self.state = 'done'


    # @api.depends(
    #     'purchase_making_charge_value',
    #     'fine_weight',
    # )
    # def _compute_purchase_making_charge(self):
    #     for rec in self:
    #         rec.purchase_making_charge_amount = rec.fine_weight * rec.purchase_price_per_gram
    #
    # @api.depends('net_weight', 'purchase_making_charge_amount')
    # def _compute_purchase_mc_fine(self):
    #     for rec in self:
    #         rec.mc_fine = rec.purchase_making_charge_amount


class JewelleryReceiveVoucherPackageLine(models.Model):
    _name = 'jewellery.receive.voucher.package.line'
    _description = 'Receive Voucher Package Product'

    voucher_id = fields.Many2one(
        'jewellery.receive.voucher',
        ondelete='cascade',

    )
    product_id = fields.Many2one('product.product', )
    qty = fields.Float()
    uom_id = fields.Many2one('uom.uom')
    # purchase_making_charge_value = fields.Float(string="Purchase Making Charge")
    # purchase_price_per_gram = fields.Float(string="Purchase fine Rate / gram")
    #
    # purchase_making_charge_amount = fields.Float(
    #     string="Purchase Making Charge Amount",
    #     compute="_compute_purchase_making_charge",
    #     store=True
    # )
    # mc_fine = fields.Float(string="MC Fine", compute="_compute_purchase_mc_fine")
    #
    # @api.depends(
    #     'purchase_making_charge_value',
    #     'mc_fine',
    # )
    # def _compute_purchase_making_charge(self):
    #     for rec in self:
    #         rec.purchase_making_charge_amount = rec.mc_fine * rec.purchase_price_per_gram
    #
    # @api.depends('net_weight', 'purchase_making_charge_amount')
    # def _compute_purchase_mc_fine(self):
    #     for rec in self:
    #         rec.mc_fine = rec.net_weight * (rec.purchase_making_charge_value) / 100
    #
