import json
from odoo import models, fields


class LabelImportBatch(models.Model):
    _name = 'label.import.batch'
    _description = 'Product Label Import Batch'
    _order = 'batch_number asc'

    job_id = fields.Many2one('label.import.job', required=True, ondelete='cascade', index=True)
    batch_number = fields.Integer(string='Batch #')
    start_row = fields.Integer()
    end_row = fields.Integer()

    created_count = fields.Integer(default=0)
    updated_count = fields.Integer(default=0)
    duplicate_count = fields.Integer(default=0)
    skipped_count = fields.Integer(default=0)
    error_count = fields.Integer(default=0)
    transferred_count = fields.Integer(default=0, string='Transferred')

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