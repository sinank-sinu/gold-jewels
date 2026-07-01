import json
from odoo import models, fields


class PoImportBatch(models.Model):
    _name = 'po.import.batch'
    _description = 'Purchase Order Import Batch'
    _order = 'batch_number asc'

    job_id = fields.Many2one('po.import.job', required=True, ondelete='cascade', index=True)
    batch_number = fields.Integer(string='Batch #')
    start_row = fields.Integer()
    end_row = fields.Integer()

    created_count = fields.Integer(default=0)
    updated_count = fields.Integer(default=0)
    duplicate_count = fields.Integer(default=0)
    skipped_count = fields.Integer(default=0)
    error_count = fields.Integer(default=0)
    lines_created_count = fields.Integer(default=0, string='Lines Created')

    # Row-level result data stored as JSON lists to avoid 100K model records
    error_rows_json = fields.Text(default='[]')
    updated_rows_json = fields.Text(default='[]')
    duplicate_rows_json = fields.Text(default='[]')
    skipped_rows_json = fields.Text(default='[]')

    def get_error_rows(self):
        return json.loads(self.error_rows_json or '[]')

    def get_updated_rows(self):
        return json.loads(self.updated_rows_json or '[]')

    def get_duplicate_rows(self):
        return json.loads(self.duplicate_rows_json or '[]')

    def get_skipped_rows(self):
        return json.loads(self.skipped_rows_json or '[]')