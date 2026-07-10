import json
from odoo import models, fields, api


class LabelImportJob(models.Model):
    _name = 'label.import.job'
    _description = 'Product Label Import Job'
    _order = 'create_date desc'

    name = fields.Char(required=True, default='New Import', copy=False)
    attachment_id = fields.Many2one('ir.attachment', string='Source File', ondelete='set null')
    file_name = fields.Char()
    file_type = fields.Selection([('csv', 'CSV'), ('xlsx', 'XLSX')], string='File Type')

    total_rows = fields.Integer(default=0)
    processed_rows = fields.Integer(default=0)
    current_offset = fields.Integer(default=0)
    batch_size = fields.Integer(default=10000)
    current_batch_number = fields.Integer(default=0)
    total_batches = fields.Integer(default=0)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('processing', 'Processing'),
        ('paused', 'Paused – Awaiting Confirmation'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], default='draft', index=True)

    # Field used to detect existing labels (create vs update).
    unique_field_name = fields.Char(string='Unique Key Field', default='name')

    # Auto-create missing Many2one records (product, purity, branch, ...)
    auto_create_m2o = fields.Boolean(string='Auto-Create Missing Records', default=False)

    # Automatically stock-in (internal transfer) each label right after import.
    auto_transfer = fields.Boolean(
        string='Auto-Transfer (Stock-In)',
        default=False,
        help='After creating each label, run the internal transfer (action_stock_in) '
             'so the item is stocked into its destination location.',
    )

    # Which Excel sheet to read (empty = active/first sheet)
    sheet_name = fields.Char(string='Excel Sheet', default='')

    mapping_config = fields.Text(string='Field Mapping (JSON)')

    # Cumulative stats
    created_count = fields.Integer(default=0)
    updated_count = fields.Integer(default=0)
    duplicate_count = fields.Integer(default=0)
    skipped_count = fields.Integer(default=0)
    error_count = fields.Integer(default=0)
    transferred_count = fields.Integer(default=0, string='Transferred')

    batch_ids = fields.One2many('label.import.batch', 'job_id', string='Batches')
    batch_count = fields.Integer(compute='_compute_batch_count')

    progress_pct = fields.Float(compute='_compute_progress', string='Progress %')

    @api.depends('batch_ids')
    def _compute_batch_count(self):
        for rec in self:
            rec.batch_count = len(rec.batch_ids)

    @api.depends('total_rows', 'processed_rows')
    def _compute_progress(self):
        for rec in self:
            if rec.total_rows:
                rec.progress_pct = round(rec.processed_rows / rec.total_rows * 100, 1)
            else:
                rec.progress_pct = 0.0

    def action_cancel(self):
        self.state = 'cancelled'

    def action_view_batches(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import Batches',
            'res_model': 'label.import.batch',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
            'context': {'default_job_id': self.id},
        }

    def get_mapping(self):
        return json.loads(self.mapping_config or '{}')