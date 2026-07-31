from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_compare


class JewelleryJobWork(models.Model):
    _name = 'jewellery.job.work'
    _description = 'Jewellery Job Work Voucher'
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

    name = fields.Char(string='Job Work Number', copy=False, readonly=True, default='New')
    job_worker_id = fields.Many2one('res.partner', domain=[('is_job_worker','=',True)], required=True)

    mo_id = fields.Many2one('mrp.production')
    issue_voucher_ids = fields.One2many(
        'jewellery.issue.voucher', 'job_work_id'
    )
    receive_voucher_ids = fields.One2many(
        'jewellery.receive.voucher', 'job_work_id'
    )
    job_work_line_ids = fields.One2many(
        'jewellery.job.work.line', 'job_work_id'
    )
    # making_charge_bill_id = fields.Many2one(
    #     'account.move', readonly=True
    # )
    # making_charge_amount = fields.Monetary(string='Making Charge', currency_field='currency_id')
    # making_charge_bill_ids = fields.One2many(
    #     'account.move', 'job_work_id', string='Making Charge Bills'
    # )

    state = fields.Selection([
        ('draft','Draft'),('issued','Issued'),('received','Received'),('done','Done')
    ], default='draft')
    requisition_id = fields.Many2one("material.purchase.requisition")

    order_date = fields.Date(
        string="Order Date",
        default=fields.Date.today
    )


    show_issue_btn = fields.Boolean(compute='_compute_buttons')
    show_receive_btn = fields.Boolean(compute='_compute_buttons')
    show_bill_btn = fields.Boolean(compute='_compute_buttons')
    lab_test_ids = fields.One2many(
        'jewellery.lab.test',
        'job_work_id',
        string='Lab Details'
    )

    total_issued_weight = fields.Float(
        compute='_compute_weights',
        string='Issued Weight',
        digits=(16, 3),
    )

    total_received_weight = fields.Float(
        compute='_compute_weights',
        string='Received Weight',
        digits = (16, 3),
    )

    weight_difference = fields.Float(
        compute='_compute_weights',
        string='Weight Difference',
        digits = (16, 3),
    )

    job_worker_balance = fields.Float(
        string='Previous Balance (g)',
        compute='_compute_job_worker_balance',
        store=False,
        digits=(16, 3)
    )

    final_balance = fields.Float(
        compute='_compute_final_balance',
        string='Final Balance',
        digits = (16, 3)

    )

    total_weight = fields.Float(
        string="Total Weight",
        compute="_compute_totals",
        store=True,
        digits=(16, 3)

    )
    total_fine_weight = fields.Float(
        string="Total Fine Weight",
        compute="_compute_total_fine_weight",
        store=True,
        digits = (16, 3)
    )

    total_labelled = fields.Float(
        string="Total Labelled",
        compute="_compute_total_labelled",
        store=True
    )

    total_unlabelled = fields.Float(
        string="Total Unlabelled",
        compute="_compute_unlabelled_totals",
        store=True
    )
    label_ids = fields.One2many(
        'product.label',
        'purchase_id',
        string="Labels"
    )

    @api.depends(
        'job_work_line_ids.quantity',
    )
    def _compute_totals(self):
        for order in self:
            order.total_weight = sum(
                order.job_work_line_ids.mapped('quantity')
            )

    @api.depends(
        'job_work_line_ids.total_fine',
    )
    def _compute_total_fine_weight(self):
        for order in self:
            order.total_fine_weight = sum(
                order.job_work_line_ids.mapped('total_fine')
            )

    @api.depends('label_ids.sale_gross_weight')
    def _compute_total_labelled(self):
        for order in self:
            order.total_labelled = sum(
                order.label_ids.mapped('sale_gross_weight')
            )

    @api.depends(
        'total_labelled',
        'total_weight'
    )
    def _compute_unlabelled_totals(self):
        for order in self:
            order.total_unlabelled = order.total_weight - order.total_labelled

    def _compute_final_balance(self):
        for rec in self:
            rec.final_balance = (
                    rec.job_worker_balance
                    + rec.total_issued_weight
                    - rec.total_received_weight
            )

    @api.depends('job_worker_id')
    def _compute_job_worker_balance(self):
        for rec in self:
            balance = 0.0
            if rec.job_worker_id:
                jobs = self.env['jewellery.job.work'].search([
                    ('job_worker_id', '=', rec.job_worker_id.id),
                    ('state', '=', 'received'),
                ])

                issued = sum(jobs.mapped('total_issued_weight'))
                received = sum(jobs.mapped('total_received_weight'))

                balance = issued - received

            rec.job_worker_balance = balance

    @api.depends('issue_voucher_ids.total_net_weight', 'receive_voucher_ids.total_net_weight')
    def _compute_weights(self):
        for rec in self:
            issued = sum(rec.issue_voucher_ids.mapped('total_net_weight'))
            received = sum(rec.receive_voucher_ids.mapped('total_net_weight'))
            rec.total_issued_weight = issued
            rec.total_received_weight = received
            rec.weight_difference = issued - received

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('jewellery.job.work') or 'New'
        return super().create(vals)

    @api.depends('state')
    def _compute_buttons(self):
        for rec in self:
            rec.show_issue_btn = rec.state == 'draft'
            rec.show_receive_btn = rec.state == 'issued'
            rec.show_bill_btn = rec.state == 'received'

    def action_create_issue_voucher(self):
        self.ensure_one()

        voucher = self.env['jewellery.issue.voucher'].create({
            'job_work_id': self.id,
            'job_worker_id': self.job_worker_id.id,
            'total_fine_weight':self.total_fine_weight,

        })
        
        self.state = 'issued'
        
        # Create Manufacturing Order when issuing material
        # self._create_manufacturing_order()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'jewellery.issue.voucher',
            'view_mode': 'form',
            'res_id': voucher.id,
        }

    # def _create_manufacturing_order(self):
    #     """Create a single MO for the job work using requisition products as components."""
    #     self.ensure_one()
    #     if self.mo_id:
    #         return self.mo_id
    #
    #     MRP = self.env['mrp.production']
    #     uom_gram = self.env.ref('uom.product_uom_gram')
    #
    #     if not self.job_work_line_ids:
    #         return False
    #
    #     # Use first line as primary finished product reference
    #     first_line = self.job_work_line_ids[0]
    #
    #     move_raw_ids = []
    #
    #     # Location logic: MO should consume and produce at the worker's location
    #     mo_location = self.job_worker_id.property_stock_supplier
    #     if not mo_location or mo_location.usage not in ['internal', 'supplier']:
    #         mo_location = self.branch_id.branch_location_id
    #     if not mo_location or mo_location.usage not in ['internal', 'supplier']:
    #         mo_location = self.env.ref('stock.stock_location_stock')
    #
    #     mo = MRP.create({
    #         'product_id': first_line.product_id.id,
    #         'product_uom_id': first_line.unit_of_measure.id or uom_gram.id,
    #         'product_qty': self.total_weight,
    #         'total_grams': self.total_weight,
    #         'purity_id': first_line.purity_id.id,
    #         'move_raw_ids': move_raw_ids,
    #         'date_start': fields.Datetime.now(),
    #         'location_src_id': mo_location.id,
    #         'location_dest_id': mo_location.id,
    #         'origin': self.name,
    #     })
    #
    #     mo.action_confirm()
    #     self.mo_id = mo.id
    #     return mo
    def action_create_receive_voucher(self):
        self.ensure_one()
        lines = []

        # Get the issue voucher (draft or done) for this job work to link it
        issue_voucher = self.env['jewellery.issue.voucher'].search([
            ('job_work_id', '=', self.id)
        ], limit=1)

        # Only consider issue vouchers in 'done' state for this job work to get lines to match
        issued_vouchers = self.env['jewellery.issue.voucher'].search([
            ('job_work_id', '=', self.id),
            ('state', '=', 'done')
        ])
        issue_lines = issued_vouchers.mapped('line_ids').sorted('id')
        remaining_issue_lines = issue_lines

        for line in self.job_work_line_ids:
            
            # Map one issue line to one job work line sequentially, since purity/product might differ
            matching_issue_line = remaining_issue_lines[:1]
            if matching_issue_line and remaining_issue_lines:
                remaining_issue_lines -= matching_issue_line


            issue_line_id = matching_issue_line.id if matching_issue_line else False
            fine_gms_price = matching_issue_line.fine_gms_price if matching_issue_line else 0.0
            fine_issue_amount = matching_issue_line.fine_issue_amount if matching_issue_line else 0.0

            lines.append((0, 0, {
                'product_id': line.product_id.id,
                'product_template_id': line.product_template_id.id,
                'purity_id': line.purity_id.id,
                'qty': line.quantity,
                'gross_weight': line.gross_weight,
                'stone_weight': line.stone_weight,
                'uom_id': line.unit_of_measure.id,
                'fine_weight': line.fine_weight,
                'mc_fine': line.mc_fine,
                'purchase_making_charge_value': line.purchase_making_charge_value,
                'total_fine': line.total_fine,
                'issue_voucher_line_id': issue_line_id,
                'fine_gms_price': fine_gms_price,
                'fine_issue_amount': fine_issue_amount,
            }))

        voucher = self.env['jewellery.receive.voucher'].create({
            'job_work_id': self.id,
            'job_worker_id': self.job_worker_id.id,
            'issue_voucher_id': issue_voucher.id if issue_voucher else False,
            'line_ids': lines,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'jewellery.receive.voucher',
            'view_mode': 'form',
            'res_id': voucher.id,
        }

    def action_done(self):
        self.state = 'done'




class JewelleryJobWorkLine(models.Model):
    _name = 'jewellery.job.work.line'
    _description = 'Jewellery Job Work Line'

    product_id = fields.Many2one("product.product", string="Product", required=True)
    product_template_id = fields.Many2one(
        string="Product Template",
        comodel_name='product.template')
    quantity = fields.Float(string="Quantity", required=True,digits = (16, 3))
    unit_of_measure = fields.Many2one("uom.uom", string="Unit of Measure", related="product_id.uom_id")
    purity_id = fields.Many2one('gold.purity', string="Purity")
    job_work_id = fields.Many2one('jewellery.job.work', required=True)
    no_of_pieces = fields.Integer(
            string="No. of Pieces",
            default=1
        )
    gram_range_id = fields.Many2one(
        'gold.gram.range',
        string="Gram Range"
    )
    purchase_making_charge_value = fields.Float(string="Purchase Making Charge",)
    purchase_price_per_gram = fields.Float(string="Purchase fine Rate / gram",)

    purchase_making_charge_amount = fields.Float(
        string="Purchase Making Charge Amount",
        store=True
    )
    mc_fine = fields.Float(string="MC Fine", compute="_compute_purchase_mc_fine")
    total_fine = fields.Float(string="Total Fine", compute="_compute_total_fine",digits = (16, 3))

    net_weight = fields.Float(
        string="Net Weight (g)",
        digits=(16, 3)

    )
    fine_weight = fields.Float( compute="_compute_fine_weight",digits = (16, 3))
    gross_weight = fields.Float(string="Gross Weight (g)",digits = (16, 3), compute="_compute_gross_weight")
    stone_weight = fields.Float(string="Stone/Diamond Weight (g)",digits = (16, 3))

    @api.depends('quantity', 'purchase_making_charge_value')
    def _compute_purchase_mc_fine(self):
        for rec in self:
            rec.mc_fine = rec.quantity * (rec.purchase_making_charge_value) / 100

    @api.depends('quantity', 'purity_id')
    def _compute_fine_weight(self):
        for rec in self:
            rec.fine_weight = rec.quantity * (rec.purity_id.percentage)/100

    @api.depends('mc_fine', 'fine_weight')
    def _compute_total_fine(self):
        for rec in self:
            rec.total_fine = rec.mc_fine +rec.fine_weight

    @api.depends('quantity', 'stone_weight')
    def _compute_gross_weight(self):
        for rec in self:
            rec.gross_weight = rec.quantity + rec.stone_weight

