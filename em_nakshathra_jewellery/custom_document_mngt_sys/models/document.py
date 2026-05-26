# -*- coding: utf-8 -*-
from odoo import models, fields, api, tools, _

class Document(models.Model):
    _inherit = 'document.document'

    date_from = fields.Date(
        string='Start Date',
        help="The initialization date of the contract/document."
    )
    date_to = fields.Date(
        string='End Date',
        help="The actual expiration date."
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Documents'
    )
    renewal_count = fields.Integer(
        string='Renewal Count',
        compute='_compute_renewal_count'
    )
    renewal_history_ids = fields.One2many(
        'document.renewal.history',
        'document_id',
        string='Renewal History'
    )
    notification_date = fields.Date(
        string='Notification Date', 
        help="Date when the system should send the expiration alert."
    )

    def _compute_renewal_count(self):
        for rec in self:
            rec.renewal_count = len(rec.renewal_history_ids)
    
    def action_open_renew_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Renew Document',
            'res_model': 'document.renew.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_document_id': self.id,
                'default_old_expiry_date': self.date_to,
            }
        }

    @api.model
    def check_document_expiry_cron(self):
        """Daily background check using the custom Notification Date"""
        # CRITICAL FIX: Use Odoo's native timezone/database safe date string wrapper
        today = fields.Date.context_today(self)

        # Find any document where the user-defined notification date matches today's string
        expiring_documents = self.search([
            ('notification_date', '=', today)
        ])
        
        for doc in expiring_documents:
            # Calculate how many days are left dynamically for the alert text
            if doc.date_to:
                # Cast to field objects to safe calculate date differences
                date_to_obj = fields.Date.from_string(doc.date_to)
                today_obj = fields.Date.from_string(today)
                days_left = (date_to_obj - today_obj).days
                timeline_str = f"{days_left} days" if days_left >= 0 else "Expired"
            else:
                timeline_str = "0 days"
            
            # Send the chatter note and the upper menu bar notification alert tray
            self._send_expiry_chatter_notification(doc, timeline_str)

    # def _send_expiry_chatter_notification(self, doc_record, timeline_str):
    #     """Helper to post sanitized HTML to chatter AND push live in-app alerts"""
    #     subject = f"⚠️ REMINDER: {doc_record.name} Requires Attention"
        
    #     raw_html_body = (
    #         f"<div>"
    #         f"<span style='color: #dc3545; font-weight: bold;'>[AUTOMATED ALERTS]</span><br/>"
    #         f"The document <strong>{doc_record.name}</strong> has reached its notification date. "
    #         f"It is scheduled to expire in <strong>{timeline_str}</strong> on {doc_record.date_to}. "
    #         f"Please initiate the necessary actions."
    #         f"</div>"
    #     )
        
    #     sanitized_html_body = tools.html_sanitize(raw_html_body)
    #     notification_partners = [doc_record.create_uid.partner_id.id] if doc_record.create_uid else []

    #     doc_record.message_post(
    #         body=sanitized_html_body, 
    #         subject=subject, 
    #         message_type='comment',
    #         subtype_xmlid='mail.mt_comment',
    #         partner_ids=notification_partners
    #     )

    def _send_expiry_chatter_notification(self, doc_record, timeline_str):

        subject = f"⚠️ CRITICAL ALERT: {doc_record.name} Expiration"

        raw_html_body = (
            f"<div>"
            f"<span style='color: #dc3545; font-weight: bold;'>[AUTOMATED ALERTS]</span><br/>"
            f"The document <strong>{doc_record.name}</strong> has reached its notification date. "
            f"It is scheduled to expire in <strong>{timeline_str}</strong> on {doc_record.date_to}. "
            f"Please initiate the necessary actions."
            f"</div>"
        )

        sanitized_html_body = tools.html_sanitize(raw_html_body)
        notification_partners = [doc_record.create_uid.partner_id.id] if doc_record.create_uid else []

        # Chatter Message
        doc_record.message_post(
            body=sanitized_html_body,
            subject=subject,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=notification_partners
        )

        # Activity Creation
        activity_type = self.env.ref('mail.mail_activity_data_todo')

        users = self.env['res.users'].search([
            ('share', '=', False)
        ])

        for user in users:

            existing_activity = self.env['mail.activity'].search([
                ('res_model', '=', 'document.document'),
                ('res_id', '=', doc_record.id),
                ('user_id', '=', user.id),
                ('summary', '=', subject),
            ], limit=1)

            if not existing_activity:

                doc_record.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=user.id,
                    summary=subject,
                    note=sanitized_html_body,
                    date_deadline=fields.Date.today(),
                )
                
   

# # -*- coding: utf-8 -*-
# from odoo import models, fields, api, tools, _
# from datetime import datetime, timedelta


# class Document(models.Model):
#     _inherit = 'document.document'

#     date_from = fields.Date(
#         string='Start Date',
#         help="The initialization date of the contract/document."
#     )

#     date_to = fields.Date(
#         string='End Date',
#         help="The actual expiration date."
#     )
#     attachment_ids = fields.Many2many(
#         'ir.attachment',
#         string='Documents'
#     )
#     renewal_count = fields.Integer(
#         string='Renewal Count',
#         compute='_compute_renewal_count'
#     )
#     renewal_history_ids = fields.One2many(
#         'document.renewal.history',
#         'document_id',
#         string='Renewal History'
#     )
#     notification_date = fields.Date(string='Notification Date', help="Date when the system should send the expiration alert.")

#     def _compute_renewal_count(self):
#         for rec in self:
#             rec.renewal_count = len(rec.renewal_history_ids)
    
#     def action_open_renew_wizard(self):
#         return {
#             'type': 'ir.actions.act_window',
#             'name': 'Renew Document',
#             'res_model': 'document.renew.wizard',
#             'view_mode': 'form',
#             'target': 'new',
#             'context': {
#                 'default_document_id': self.id,
#                 'default_old_expiry_date': self.date_to,
#             }
#         }

#     @api.model
#     def check_document_expiry_cron(self):

#         today = datetime.now().date()

#         notice_30_days = today + timedelta(days=30)
#         notice_60_days = today + timedelta(days=60)

#         # Standard Documents
#         expiring_standard_docs = self.search([
#             ('date_to', '=', notice_30_days),
#             '|', '|', '|',
#             ('name', 'ilike', 'Tenancy'),
#             ('name', 'ilike', 'Insurance'),
#             ('name', 'ilike', 'ID'),
#             ('name', 'ilike', 'Accommodation')
#         ])

#         for doc in expiring_standard_docs:
#             self._send_expiry_alert(doc, "30 days")

#         # Employee Contracts
#         expiring_contracts = self.search([
#             ('date_to', '=', notice_60_days),
#             ('name', 'ilike', 'Contract')
#         ])

#         for contract in expiring_contracts:
#             self._send_expiry_alert(contract, "2 months")
   
#     # ---------------------------------------------------------
#     # ALERT FUNCTION
#     # ---------------------------------------------------------
    # def _send_expiry_alert(self, doc_record, timeline_str):

    #     subject = f"⚠️ CRITICAL ALERT: {doc_record.name} Expiration"

    #     raw_html_body = (
    #         f"<div>"
    #         f"<span style='color:#dc3545;font-weight:bold;'>"
    #         f"[AUTOMATED ALERT]"
    #         f"</span><br/>"
    #         f"The document <strong>{doc_record.name}</strong> "
    #         f"is scheduled to expire in "
    #         f"<strong>{timeline_str}</strong> "
    #         f"on <strong>{doc_record.date_to}</strong>."
    #         f"</div>"
    #     )

    #     sanitized_html_body = tools.html_sanitize(raw_html_body)

    #     # Chatter Message
    #     doc_record.message_post(
    #         body=sanitized_html_body,
    #         subject=subject,
    #         message_type='comment',
    #         subtype_xmlid='mail.mt_comment',
    #     )

    #     # Activity Creation
    #     activity_type = self.env.ref('mail.mail_activity_data_todo')

    #     users = self.env['res.users'].search([
    #         ('share', '=', False)
    #     ])

    #     for user in users:

    #         existing_activity = self.env['mail.activity'].search([
    #             ('res_model', '=', 'document.document'),
    #             ('res_id', '=', doc_record.id),
    #             ('user_id', '=', user.id),
    #             ('summary', '=', subject),
    #         ], limit=1)

    #         if not existing_activity:

    #             doc_record.activity_schedule(
    #                 activity_type_id=activity_type.id,
    #                 user_id=user.id,
    #                 summary=subject,
    #                 note=sanitized_html_body,
    #                 date_deadline=fields.Date.today(),
    #             )
                
   