from odoo import models, fields, api


class FineRateHistory(models.Model):
    _name = 'fine.rate.history'
    _description = 'Fine Rate History'
    _order = 'update_datetime desc'

    master_id = fields.Many2one(
        'fine.rate.master',
        required=True,
        ondelete='cascade'
    )
    rate_date = fields.Date(
        string="Rate Date",
        related='master_id.date',
        store=True,
    )

    update_datetime = fields.Datetime(
        string="Updated On",
        default=fields.Datetime.now
    )

    fine_rate = fields.Float(
        string="Fine Rate"
    )