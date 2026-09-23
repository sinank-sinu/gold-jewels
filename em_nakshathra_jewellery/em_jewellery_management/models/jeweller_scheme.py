from odoo import models, fields, api, _
from odoo.tools.float_utils import float_is_zero
from markupsafe import Markup

class JewellerySchemeEnrollment(models.Model):
    _name = 'jewellery.scheme.enrollment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Jewellery Scheme Enrollment'
    _order = 'create_date desc'

    name = fields.Char(default="New", tracking=True)
    partner_id = fields.Many2one('res.partner', required=True, tracking=True)
    phone = fields.Char(string="Phone Number", tracking=True)
    whatsapp_number = fields.Char(string="WhatsApp Number", tracking=True)
    address = fields.Text(string="Address", tracking=True)
    nominee = fields.Char(string="Nominee", tracking=True)
    nominee_phone = fields.Char(string="Nominee Phone Number", tracking=True)
    date_of_joining = fields.Date(string="Date of Joining", default=fields.Date.today, tracking=True)

    def _get_branch_domain(self):
        """methode to get branch domain"""
        company = self.env.company
        branch_ids = self.env.user.branch_ids
        branch = branch_ids.filtered(
            lambda branch: branch.company_id == company)
        return [('id', 'in', branch.ids)]

    user_id = fields.Many2one(
        'res.users',
        string='Salesperson',
        default=lambda self: self.env.user.id,
        tracking=True
    )

    branch_id = fields.Many2one('res.branch', string='Branch', store=True,
                                domain=_get_branch_domain,
                                help='Leave this field empty if this account is'
                                     ' shared between all branches',
                                default=lambda self: self.env.user.branch_id.id,
                                tracking=True)

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

                # Pre-fill Nominee and Nominee Phone from partner's contacts details
                nominee_contact = partner.child_ids.filtered(lambda c: c.type == 'other')[:1] or partner.child_ids[:1]
                if nominee_contact:
                    rec.nominee = nominee_contact.name
                    rec.nominee_phone = nominee_contact.phone or nominee_contact.mobile

    @api.onchange('nominee')
    def _onchange_nominee(self):
        for rec in self:
            if rec.partner_id and rec.nominee:
                matching = rec.partner_id.child_ids.filtered(
                    lambda c: (c.name or '').strip().lower() == rec.nominee.strip().lower()
                )[:1]
                if matching:
                    rec.nominee_phone = matching.phone or matching.mobile

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('partner_id'):
                partner = self.env['res.partner'].browse(vals['partner_id'])
                if not vals.get('nominee'):
                    nominee_contact = partner.child_ids.filtered(lambda c: c.type == 'other')[:1] or partner.child_ids[:1]
                    if nominee_contact:
                        vals['nominee'] = nominee_contact.name
                        if not vals.get('nominee_phone'):
                            vals['nominee_phone'] = nominee_contact.phone or nominee_contact.mobile
                elif vals.get('nominee') and not vals.get('nominee_phone'):
                    matching = partner.child_ids.filtered(
                        lambda c: (c.name or '').strip().lower() == vals['nominee'].strip().lower()
                    )[:1] or partner.child_ids.filtered(lambda c: c.type == 'other')[:1] or partner.child_ids[:1]
                    if matching:
                        vals['nominee_phone'] = matching.phone or matching.mobile
        return super().create(vals_list)

    start_date = fields.Date(default=fields.Date.today, tracking=True)
    duration = fields.Integer(required=True, default=11, tracking=True, readonly=True)
    installment_amount = fields.Float(required=True, tracking=True)
    active = fields.Boolean(
        string='Active',
        default=False,
        tracking=True
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
    ], default='running', tracking=True)

    ticket_number = fields.Char(string="Ticket Number", tracking=True)

    def action_set_active_rate(self):
        self.ensure_one()
        self.search([('id', '!=', self.id), ('partner_id', '=', self.partner_id.id)]).write({'active': False})
        self.active = True
        self.message_post(
            body=Markup(_("Scheme enrollment set as <b>Active</b>.")),
            subtype_xmlid='mail.mt_note'
        )

    @api.depends('scheme_line_ids.amount', 'scheme_line_ids.state')
    def _compute_totals(self):
        for rec in self:
            paid_lines = rec.scheme_line_ids.filtered(lambda l: l.state == 'paid')
            total = sum(paid_lines.mapped('amount'))
            rec.total_paid = total
            rec.paid_count = len(paid_lines)
            rec.balance_amount = (rec.duration * rec.installment_amount) - total

            if rec.state not in ('redeemed', 'completed'):
                if (rec.duration > 0 and rec.paid_count >= rec.duration) or (rec.duration > 0 and rec.total_paid >= (rec.duration * rec.installment_amount)):
                    rec.state = 'completed'
                else:
                    rec.state = 'running'
            elif rec.state == 'completed':
                if getattr(rec, 'is_redeemed', False):
                    rec.state = 'redeemed'
