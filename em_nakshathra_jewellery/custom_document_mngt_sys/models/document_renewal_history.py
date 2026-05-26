# -*- coding: utf-8 -*-

from odoo import models, fields


class DocumentRenewalHistory(models.Model):
    _name = 'document.renewal.history'
    _description = 'Document Renewal History'
    _order = 'id desc'

    document_id = fields.Many2one(
        'document.document',
        string='Document'
    )

    old_start_date = fields.Date(
        string='Old Start Date'
    )

    old_expiry_date = fields.Date(
        string='Old Expiry Date'
    )

    new_start_date = fields.Date(
        string='New Start Date'
    )

    new_expiry_date = fields.Date(
        string='New Expiry Date'
    )

    renewed_by = fields.Many2one(
        'res.users',
        string='Renewed By',
        default=lambda self: self.env.user
    )

    renewed_on = fields.Datetime(
        string='Renewed On',
        default=fields.Datetime.now
    )

    remarks = fields.Text()

    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Attachments'
    )