from odoo import models, fields, api
from datetime import date


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ring_size = fields.Float(string="Ring Size")
    dob = fields.Date(string="Date of Birth")
    age = fields.Integer(string="Age", compute="_compute_age", store=True)

    @api.model
    def default_get(self, fields_list):
        res = super(ResPartner, self).default_get(fields_list)
        
        # Use .get() to avoid KeyErrors and check if parent_id exists
        parent_id = res.get('parent_id') or self._context.get('default_parent_id')
        
        if parent_id:
            # browse the parent and only take the ring_size
            parent = self.browse(parent_id)
            if parent.exists():
                res.update({
                    'ring_size': parent.ring_size,
                })
        return res

    @api.depends('dob')
    def _compute_age(self):
        for rec in self:
            if rec.dob:
                today = date.today()
                rec.age = today.year - rec.dob.year - (
                    (today.month, today.day) < (rec.dob.month, rec.dob.day)
                )
            else:
                rec.age = 0

    # @api.depends('parent_id', 'parent_id.parent_ring_size', 'parent_ring_size')
    # def _compute_ring_size(self):
    #     for rec in self:
    #         if rec.parent_id:
    #             rec.ring_size = rec.parent_id.parent_ring_size
    #         else:
    #             rec.ring_size = rec.parent_ring_size