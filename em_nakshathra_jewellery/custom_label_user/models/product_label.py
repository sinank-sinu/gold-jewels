from odoo import models, fields, api


class ProductLabel(models.Model):
    _inherit = 'product.label'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        default=lambda self: self.env['hr.employee'].search([
            ('user_id', '=', self.env.user.id)
        ], limit=1)
    )

    user_id = fields.Many2one(
        'res.users',
        string='User',
        related='employee_id.user_id',
        store=True,
        readonly=True
    )

    @api.onchange('employee_id')
    def _onchange_employee_id_set_location(self):
        """On change of employee, set the source location of the label to the employee's label location."""
        for rec in self:
            if rec.employee_id and rec.employee_id.label_location_id:
                rec.source_location_id = rec.employee_id.label_location_id.id

    @api.model
    def create(self, vals):
        """Override create to auto-assign employee based on logged-in user and set source location from employee's label location."""
        # Auto assign employee from logged-in user
        if not vals.get('employee_id'):
            employee = self.env['hr.employee'].search([
                ('user_id', '=', self.env.user.id)
            ], limit=1)

            if employee:
                vals['employee_id'] = employee.id

                # Auto set source location from employee label location
                if employee.label_location_id:
                    vals['source_location_id'] = employee.label_location_id.id

        return super().create(vals)