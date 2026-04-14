from odoo import models, fields, api
from odoo.tools.float_utils import float_is_zero

class JewellerySchemeEnrollment(models.Model):
    _name = 'jewellery.scheme.enrollment'
    _description = 'Jewellery Scheme Enrollment'

    name = fields.Char(default="New")
    partner_id = fields.Many2one('res.partner', required=True)
    start_date = fields.Date(default=fields.Date.today)
    duration = fields.Integer(required=True)
    installment_amount = fields.Float(required=True)
    active = fields.Boolean(
        string='Active',
        default=False
    )
    scheme_line_ids = fields.One2many(
        'jewellery.scheme.installment',
        'enrollment_id'
    )

    total_paid = fields.Float(compute='_compute_totals', store=True)
    paid_count = fields.Integer(compute='_compute_totals', store=True)
    balance_amount = fields.Float(compute='_compute_totals', store=True)

    state = fields.Selection([
        ('running', 'Running'),
        ('completed', 'Completed')
    ], default='running')

    def action_set_active_rate(self):
        self.ensure_one()
        self.search([('id', '!=', self.id), ('partner_id', '=', self.partner_id.id)]).write({'active': False})
        self.active = True

    @api.depends('scheme_line_ids.amount', 'scheme_line_ids.state')
    def _compute_totals(self):
        for rec in self:
            paid_lines = rec.scheme_line_ids.filtered(lambda l: l.state == 'paid')
            total = sum(paid_lines.mapped('amount'))
            rec.total_paid = total
            rec.paid_count = len(paid_lines)
            rec.balance_amount = (rec.duration * rec.installment_amount) - total

            if rec.paid_count >= rec.duration:
                rec.state = 'completed'
            else:
                rec.state = 'running'
