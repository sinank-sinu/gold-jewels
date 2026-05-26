# -*- coding: utf-8 -*-

from odoo import models, fields


class DocumentRenewWizard(models.TransientModel):
    _name = 'document.renew.wizard'
    _description = 'Renew Document Wizard'

    document_id = fields.Many2one(
        'document.document',
        required=True
    )

    old_expiry_date = fields.Date(
        string='Current Expiry Date'
    )

    new_start_date = fields.Date(
        string='New Start Date',
        required=True
    )

    new_expiry_date = fields.Date(
        string='New Expiry Date',
        required=True
    )

    remarks = fields.Text()

    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Upload Renewed Documents'
    )

    def action_confirm_renewal(self):

        self.ensure_one()

        document = self.document_id

        # -------------------------------------------------
        # CREATE HISTORY
        # -------------------------------------------------

        self.env['document.renewal.history'].create({
            'document_id': document.id,
            'old_start_date': document.date_from,
            'old_expiry_date': document.date_to,
            'new_start_date': self.new_start_date,
            'new_expiry_date': self.new_expiry_date,
            'remarks': self.remarks,
            'attachment_ids': [(6, 0, self.attachment_ids.ids)],
        })

        # -------------------------------------------------
        # UPDATE CURRENT DOCUMENT
        # -------------------------------------------------

        document.write({
            'date_from': self.new_start_date,
            'date_to': self.new_expiry_date,
            'attachment_ids': [(6, 0, self.attachment_ids.ids)],
        })

        # -------------------------------------------------
        # MARK ACTIVITIES DONE
        # -------------------------------------------------

        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'document.document'),
            ('res_id', '=', document.id),
        ])

        activities.action_feedback(
            feedback="Document renewed successfully."
        )

        # -------------------------------------------------
        # CHATTER MESSAGE
        # -------------------------------------------------

        document.message_post(
            body=f"""
                <b>Document Renewed</b><br/>
                New Expiry Date: {self.new_expiry_date}
            """
        )