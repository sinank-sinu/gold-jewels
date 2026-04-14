from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'


    is_job_worker = fields.Boolean(string='Job Worker')
    default_making_charge = fields.Float(string='Making Charge / Gram')
    show_making_charge = fields.Boolean(compute='_compute_show_making_charge')
    scheme_amount = fields.Monetary(
        string='Scheme Balance',
        currency_field='currency_id',
        default=0.0
    )

    city = fields.Selection([
        ("Kochi", "Kochi"),
        ("Edappally", "Edappally"),
        ("Kaloor", "Kaloor"),
        ("Vyttila", "Vyttila"),
        ("Aluva", "Aluva"),
        ("Other", "Other"),
    ], string="City")




    # @api.depends('is_job_worker')
    # def _compute_show_making_charge(self):
    #     for rec in self:
    #         rec.show_making_charge = rec.is_job_worker

    @api.depends('is_job_worker')
    def _compute_show_making_charge(self):
        for rec in self:
            rec.show_making_charge = rec.is_job_worker


    @api.onchange("name")
    def _onchange_name_capitalize_first(self):
        if self.name:
            self.name = self.name.strip()
            self.name = self.name[0].upper() + self.name[1:]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        # Auto-fill Salesperson with logged-in user
        if 'user_id' in fields_list and not res.get('user_id'):
            res['user_id'] = self.env.user.id

        return res







