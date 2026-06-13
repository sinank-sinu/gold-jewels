from odoo import models, fields, api
from odoo.tools.float_utils import float_is_zero

class JewellerySchemeEnrollment(models.Model):
    _name = 'jewellery.scheme.enrollment'
    _description = 'Jewellery Scheme Enrollment'
    _order = 'create_date desc'

    name = fields.Char(default="New")
    partner_id = fields.Many2one('res.partner', required=True)
    phone = fields.Char(string="Phone Number",)
    whatsapp_number = fields.Char(string="WhatsApp Number")
    address = fields.Text(string="Address")
    nominee = fields.Char(string="Nominee")
    date_of_joining = fields.Date(string="Date of Joining", default=fields.Date.today)

    def _get_branch_domain(self):
        """methode to get branch domain"""
        company = self.env.company
        branch_ids = self.env.user.branch_ids
        branch = branch_ids.filtered(
            lambda branch: branch.company_id == company)
        return [('id', 'in', branch.ids)]

    branch_id = fields.Many2one('res.branch', string='Branch', store=True,
                                domain=_get_branch_domain,
                                help='Leave this field empty if this account is'
                                     ' shared between all branches',
                                default=lambda self: self.env.user.branch_id.id, )

    @api.onchange('partner_id')
    def _onchange_partner(self):
        for rec in self:
            if rec.partner_id:
                partner = rec.partner_id

                rec.phone = partner.phone
                rec.whatsapp_number = partner.mobile

                rec.address = "\n".join(filter(None, [
                    partner.street,
                    partner.street2,
                    f"{partner.city or ''} - {partner.zip or ''}" if partner.city or partner.zip else '',
                    partner.state_id.name if partner.state_id else '',
                    partner.country_id.name if partner.country_id else '',
                ]))
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

    ticket_number = fields.Char(string="Ticket Number")
    

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
