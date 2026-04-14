from odoo import models, fields, api
from odoo.exceptions import UserError
import json
from datetime import datetime

class JewelleryJobWork(models.Model):
    _inherit = 'jewellery.job.work'

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', help="Pricelist for current job work.")
    partner_id = fields.Many2one('res.partner', related='job_worker_id', string='Partner', readonly=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency', readonly=True)

    date_order = fields.Datetime(string='Order Date', compute='_compute_date_order', readonly=True, store=True, default=fields.Datetime.now)

    @api.depends('create_date')
    def _compute_date_order(self):
        for rec in self:
            if hasattr(rec, 'confirmed_date') and rec.confirmed_date:
                if isinstance(rec.confirmed_date, datetime):
                    rec.date_order = rec.confirmed_date
                else:
                    rec.date_order = fields.Datetime.to_datetime(rec.confirmed_date)
            elif rec.create_date:
                rec.date_order = rec.create_date
            else:
                rec.date_order = fields.Datetime.now()
    order_line = fields.One2many('jewellery.job.work.line', 'job_work_id', string='Order Lines')

class JewelleryJobWorkLine(models.Model):
    _inherit = 'jewellery.job.work.line'

    product_template_id = fields.Many2one(
        related='product_id.product_tmpl_id',
        string="Product Template",
        readonly=True
    )
    product_template_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='jewellery_job_work_line_ptav_rel',
        string="Product Attribute Values",
        ondelete='restrict'
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='jewellery_job_work_line_no_variant_ptav_rel',
        string="Extra Product Attribute Values",
        ondelete='restrict'
    )
    product_custom_attribute_value_ids = fields.One2many(
        comodel_name='product.attribute.custom.value',
        inverse_name='job_work_line_id',
        string="Custom Product Attribute Values"
    )
    is_configurable_product = fields.Boolean(
        string="Is the product configurable?",
        related='product_template_id.has_configurable_attributes'
    )
    product_type = fields.Selection(
        related='product_id.detailed_type'
    )
    product_uom = fields.Many2one(
        related='unit_of_measure',
        string="Product Unit of Measure",
        readonly=True
    )
    company_id = fields.Many2one(
        related='job_work_id.company_id',
        string='Company',
        store=True,
        readonly=True
    )
    pricelist_id = fields.Many2one(
        related='job_work_id.pricelist_id',
        string='Pricelist',
        readonly=True
    )
    partner_id = fields.Many2one(
        related='job_work_id.partner_id',
        string='Partner',
        readonly=True
    )
    date_order = fields.Datetime(
        related='job_work_id.date_order',
        string='Order Date',
        readonly=True
    )
    currency_id = fields.Many2one(
        related='job_work_id.currency_id',
        string='Currency',
        readonly=True
    )
    order_id = fields.Many2one(
        related='job_work_id',
        string='Order',
        readonly=True
    )
    product_uom_qty = fields.Float(
        related='quantity',
        string="Product Quantity",
        readonly=False
    )
    branch_id = fields.Many2one(
        related='job_work_id.branch_id',
        string='Branch',
        store=True,
        readonly=True
    )

class JewelleryIssueVoucher(models.Model):
    _inherit = 'jewellery.issue.voucher'

    def action_done(self):
        """Override to pass branch_id to stock.picking"""
        res = super().action_done()
        for rec in self:
            if rec.picking_id:
                rec.picking_id.branch_id = rec.branch_id.id
        return res

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', help="Pricelist for current voucher.")
    partner_id = fields.Many2one('res.partner', related='job_worker_id', string='Partner', readonly=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency', readonly=True)
    date_order = fields.Datetime(string='Order Date', compute='_compute_date_order', readonly=True)

    @api.depends('confirmed_date')
    def _compute_date_order(self):
        for rec in self:
            if rec.confirmed_date:
                rec.date_order = fields.Datetime.to_datetime(rec.confirmed_date)
            else:
                rec.date_order = fields.Datetime.now()
    order_line = fields.One2many('jewellery.issue.voucher.line', 'voucher_id', string='Order Lines')

class JewelleryIssueVoucherLine(models.Model):
    _inherit = 'jewellery.issue.voucher.line'

    product_template_id = fields.Many2one(
        related='product_id.product_tmpl_id',
        string="Product Template",
        readonly=True
    )
    product_template_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='jewellery_issue_voucher_line_ptav_rel',
        string="Product Attribute Values",
        ondelete='restrict'
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='jewellery_issue_voucher_line_no_variant_ptav_rel',
        string="Extra Product Attribute Values",
        ondelete='restrict'
    )
    product_custom_attribute_value_ids = fields.One2many(
        comodel_name='product.attribute.custom.value',
        inverse_name='issue_voucher_line_id',
        string="Custom Product Attribute Values"
    )
    is_configurable_product = fields.Boolean(
        string="Is the product configurable?",
        related='product_template_id.has_configurable_attributes'
    )
    product_type = fields.Selection(
        related='product_id.detailed_type'
    )
    product_uom = fields.Many2one(
        related='uom_id',
        string="Product Unit of Measure",
        readonly=True
    )
    company_id = fields.Many2one(
        related='voucher_id.company_id',
        string='Company',
        store=True,
        readonly=True
    )
    pricelist_id = fields.Many2one(
        related='voucher_id.pricelist_id',
        string='Pricelist',
        readonly=True
    )
    partner_id = fields.Many2one(
        related='voucher_id.partner_id',
        string='Partner',
        readonly=True
    )
    date_order = fields.Datetime(
        related='voucher_id.date_order',
        string='Order Date',
        readonly=True
    )
    currency_id = fields.Many2one(
        related='voucher_id.currency_id',
        string='Currency',
        readonly=True
    )
    order_id = fields.Many2one(
        related='voucher_id',
        string='Order',
        readonly=True
    )
    product_uom_qty = fields.Float(
        related='qty',
        string="Product Quantity",
        readonly=False
    )

class JewelleryReceiveVoucher(models.Model):
    _inherit = 'jewellery.receive.voucher'

    def action_done(self):
        """Override to pass branch_id to stock.picking"""
        res = super().action_done()
        for rec in self:
            if rec.picking_id:
                rec.picking_id.branch_id = rec.branch_id.id
        return res

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', help="Pricelist for current voucher.")
    partner_id = fields.Many2one('res.partner', related='job_worker_id', string='Partner', readonly=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency', readonly=True)
    date_order = fields.Datetime(string='Order Date', compute='_compute_date_order', readonly=True)

    @api.depends('confirmed_date')
    def _compute_date_order(self):
        for rec in self:
            if rec.confirmed_date:
                rec.date_order = fields.Datetime.to_datetime(rec.confirmed_date)
            else:
                rec.date_order = fields.Datetime.now()
    order_line = fields.One2many('jewellery.receive.voucher.line', 'voucher_id', string='Order Lines')

class JewelleryReceiveVoucherLine(models.Model):
    _inherit = 'jewellery.receive.voucher.line'

    product_template_id = fields.Many2one(
        related='product_id.product_tmpl_id',
        string="Product Template",
        readonly=True
    )
    product_template_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='jewellery_receive_voucher_line_ptav_rel',
        string="Product Attribute Values",
        ondelete='restrict'
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='jewellery_receive_voucher_line_no_variant_ptav_rel',
        string="Extra Product Attribute Values",
        ondelete='restrict'
    )
    product_custom_attribute_value_ids = fields.One2many(
        comodel_name='product.attribute.custom.value',
        inverse_name='receive_voucher_line_id',
        string="Custom Product Attribute Values"
    )
    is_configurable_product = fields.Boolean(
        string="Is the product configurable?",
        related='product_template_id.has_configurable_attributes'
    )
    product_type = fields.Selection(
        related='product_id.detailed_type'
    )
    product_uom = fields.Many2one(
        related='uom_id',
        string="Product Unit of Measure",
        readonly=True
    )
    company_id = fields.Many2one(
        related='voucher_id.company_id',
        string='Company',
        store=True,
        readonly=True
    )
    pricelist_id = fields.Many2one(
        related='voucher_id.pricelist_id',
        string='Pricelist',
        readonly=True
    )
    partner_id = fields.Many2one(
        related='voucher_id.partner_id',
        string='Partner',
        readonly=True
    )
    date_order = fields.Datetime(
        related='voucher_id.date_order',
        string='Order Date',
        readonly=True
    )
    currency_id = fields.Many2one(
        related='voucher_id.currency_id',
        string='Currency',
        readonly=True
    )
    order_id = fields.Many2one(
        related='voucher_id',
        string='Order',
        readonly=True
    )
    product_uom_qty = fields.Float(
        related='qty',
        string="Product Quantity",
        readonly=False
    )

class MaterialPurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', help="Pricelist for current requisition.")
    partner_id = fields.Many2one('res.partner', related='employee_id.work_contact_id', string='Partner', readonly=True)
    date_order = fields.Datetime(string='Order Date', compute='_compute_date_order', readonly=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency', readonly=True)
    order_line = fields.One2many('material.purchase.requisition.line', 'requisition_id', string='Order Lines')
    has_work_order = fields.Boolean(compute='_compute_has_work_order', string='Has Work Order Lines', store=True)

    @api.depends('requisition_lines.request_action')
    def _compute_has_work_order(self):
        for rec in self:
            rec.has_work_order = any(l.request_action == 'work order' for l in rec.requisition_lines)

    @api.depends('requisition_date')
    def _compute_date_order(self):
        for rec in self:
            if rec.requisition_date:
                rec.date_order = fields.Datetime.to_datetime(rec.requisition_date)
            else:
                rec.date_order = fields.Datetime.now()

class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = 'material.purchase.requisition.line'

    product_template_id = fields.Many2one(
        related='product_id.product_tmpl_id',
        string="Product Template",
        readonly=True
    )
    is_work_order = fields.Boolean(compute='_compute_is_work_order', string='Is Work Order')

    @api.depends('request_action')
    def _compute_is_work_order(self):
        for rec in self:
            rec.is_work_order = rec.request_action == 'work order'

    product_template_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='material_purchase_requisition_line_ptav_rel',
        string="Product Attribute Values",
        ondelete='restrict'
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        relation='material_purchase_requisition_line_no_variant_ptav_rel',
        string="Extra Product Attribute Values",
        ondelete='restrict'
    )
    product_custom_attribute_value_ids = fields.One2many(
        comodel_name='product.attribute.custom.value',
        inverse_name='requisition_line_id',
        string="Custom Product Attribute Values"
    )
    is_configurable_product = fields.Boolean(
        string="Is the product configurable?",
        related='product_template_id.has_configurable_attributes'
    )
    product_type = fields.Selection(
        related='product_id.detailed_type'
    )
    product_uom = fields.Many2one(
        related='unit_of_measure',
        string="Product Unit of Measure",
        readonly=True
    )
    company_id = fields.Many2one(
        related='requisition_id.company_id',
        string='Company',
        store=True,
        readonly=True
    )
    pricelist_id = fields.Many2one(
        related='requisition_id.pricelist_id',
        string='Pricelist',
        readonly=True
    )
    partner_id = fields.Many2one(
        related='requisition_id.partner_id',
        string='Partner',
        readonly=True
    )
    date_order = fields.Datetime(
        related='requisition_id.date_order',
        string='Order Date',
        readonly=True
    )
    currency_id = fields.Many2one(
        related='requisition_id.currency_id',
        string='Currency',
        readonly=True
    )
    order_id = fields.Many2one(
        related='requisition_id',
        string='Order',
        readonly=True
    )
    product_uom_qty = fields.Float(
        related='quantity',
        string="Product Quantity",
        readonly=False
    )

class ProductAttributeCustomValue(models.Model):
    _inherit = 'product.attribute.custom.value'

    job_work_line_id = fields.Many2one('jewellery.job.work.line', string="Job Work Line", ondelete='cascade')
    issue_voucher_line_id = fields.Many2one('jewellery.issue.voucher.line', string="Issue Voucher Line", ondelete='cascade')
    receive_voucher_line_id = fields.Many2one('jewellery.receive.voucher.line', string="Receive Voucher Line", ondelete='cascade')
    requisition_line_id = fields.Many2one('material.purchase.requisition.line', string="Requisition Line", ondelete='cascade')
