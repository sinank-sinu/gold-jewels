import json
from odoo import models, fields, api


class PoImportJob(models.Model):
    _name = 'po.import.job'
    _description = 'Purchase Order Import Job'
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

    match_field = fields.Selection([
        ('name', 'PO Number'),
        ('partner_ref', 'Vendor Reference'),
        ('partner_name', 'Vendor + PO Number'),
    ], default='name', string='Match Existing POs By')

    model_name = fields.Char(string='Target Model', default='purchase.order')
    unique_field_name = fields.Char(string='Unique Key Field', default='name')

    # Header + Lines mode
    has_lines = fields.Boolean(string='Has Line Items', default=False)
    line_model_name = fields.Char(string='Line Model')
    line_link_field = fields.Char(string='Line → Parent Field')
    group_by_field = fields.Char(string='Group Rows By Field')

    # Direct-to-existing-PO mode: all rows become lines on this PO
    target_po_id = fields.Many2one('purchase.order', string='Add Lines To (Existing PO)',
                                   ondelete='set null')

    # Auto-create missing Many2one records
    auto_create_m2o = fields.Boolean(string='Auto-Create Missing Records', default=False)

    # Automatically confirm PO, receive products, and validate after import
    auto_confirm_receive = fields.Boolean(
        string='Auto-Confirm & Receive',
        default=False,
        help='After creating/updating each PO: confirm the order, receive all products, and validate the picking.',
    )

    # Automatically create + post vendor bill after receiving
    auto_create_bill = fields.Boolean(
        string='Auto-Create & Post Bill',
        default=False,
        help=(
            'After confirming & receiving, create a vendor bill, '
            'replace the Creditors account with Opening Balance Account, '
            'and post (approve) the bill.'
        ),
    )

    # Which Excel sheet to read (empty = active/first sheet)
    sheet_name = fields.Char(string='Excel Sheet', default='')

    mapping_config = fields.Text(string='Field Mapping (JSON)')

    # Tracks partner_id → purchase_order_id across batches to avoid creating
    # duplicate POs for the same vendor when rows are split across batches.
    vendor_po_map = fields.Text(string='Vendor-PO Map (JSON)', default='{}')

    # Cumulative stats
    created_count = fields.Integer(default=0)
    updated_count = fields.Integer(default=0)
    duplicate_count = fields.Integer(default=0)
    skipped_count = fields.Integer(default=0)
    error_count = fields.Integer(default=0)
    lines_created_count = fields.Integer(default=0, string='Lines Created')

    batch_ids = fields.One2many('po.import.batch', 'job_id', string='Batches')
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
            'res_model': 'po.import.batch',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
            'context': {'default_job_id': self.id},
        }

    def get_mapping(self):
        return json.loads(self.mapping_config or '{}')