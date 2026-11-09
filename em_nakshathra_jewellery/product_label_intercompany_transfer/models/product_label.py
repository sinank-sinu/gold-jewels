# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ProductLabel(models.Model):
    _inherit = 'product.label'

    is_transferred = fields.Boolean(
        string="Transferred to Other Company",
        default=False,
        copy=False,
        help="Indicates whether this label was transferred to another company."
    )
    transfer_dest_company_id = fields.Many2one(
        'res.company',
        string="Transferred to Company",
        copy=False,
        readonly=True,
        help="The destination company to which this label was transferred."
    )
    transfer_dest_label_id = fields.Many2one(
        'product.label',
        string="Transferred Label Record",
        copy=False,
        readonly=True,
        help="The newly created label record in the destination company."
    )
    transfer_date = fields.Date(
        string="Intercompany Transfer Date",
        copy=False,
        readonly=True
    )
    transfer_notes = fields.Char(
        string="Transfer Notes",
        copy=False,
        readonly=True
    )
    original_vendor_id = fields.Many2one(
        'res.partner',
        string="Original Vendor",
        copy=False,
        help="Preserves the original manufacturing vendor across inter-company transfers."
    )

    @api.depends('purchase_id.partner_id', 'original_vendor_id')
    def _compute_partner_id(self):
        super()._compute_partner_id()
        for rec in self:
            if rec.original_vendor_id:
                rec.partner_id = rec.original_vendor_id


