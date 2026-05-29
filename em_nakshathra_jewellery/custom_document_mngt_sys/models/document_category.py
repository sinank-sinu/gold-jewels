# -*- coding: utf-8 -*-
from odoo import models, fields

class DocumentCategory(models.Model):
    _name = 'document.category'
    _description = 'Document Category'
    _order = 'name'

    name = fields.Char(string='Category Name', required=True)
    active = fields.Boolean(default=True)
    
    # This counts how many documents exist inside this category dynamically
    document_count = fields.Integer(
        string='Documents Count', 
        compute='_compute_document_count'
    )

    def _compute_document_count(self):
        for rec in self:
            rec.document_count = self.env['document.document'].search_count([
                ('category_id', '=', rec.id)
            ])

    def action_view_documents(self):
        """Action triggered when clicking a category card to open its filtered documents"""
        self.ensure_one()
        return {
            'name': self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'document.document',
            'view_mode': 'kanban,tree,form',
            'domain': [('category_id', '=', self.id)],
            # Automatically pre-selects this category when clicking the "New" button
            'context': {'default_category_id': self.id}, 
        }