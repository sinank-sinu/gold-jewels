# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    can_responsible_action = fields.Boolean(
        compute='_compute_can_responsible_action',
        store=False
    )
    responsible_user_id = fields.Many2one('res.users',string="Responsible User")

    @api.depends('responsible_user_id')
    def _compute_can_responsible_action(self):
        user = self.env.user
        for picking in self:
            if picking.responsible_user_id:
                picking.can_responsible_action = (
                        picking.responsible_user_id == user
                )
            else:
                picking.can_responsible_action = True

    @api.onchange('responsible_user_id')
    def _onchange_responsible_user_id(self):
        if self.responsible_user_id:
            self.user_id = self.responsible_user_id.id

    def action_confirm(self):
        res = super().action_confirm()

        activity_type = self.env.ref('mail.mail_activity_data_todo')

        for picking in self:
            if not picking.responsible_user_id:
                return res
            else:
                picking.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=picking.responsible_user_id.id,
                    summary=_("Transfer marked as To Do"),
                    note=_("Please process transfer %s") % picking.name,
                )
        return res

    def button_validate(self):
        res = super().button_validate()

        Activity = self.env['mail.activity']
        activity_type = self.env.ref('mail.mail_activity_data_todo')

        for picking in self:
            # Permission check
            if not picking.responsible_user_id:
                return res

            if picking.responsible_user_id and picking.responsible_user_id != self.env.user:
                raise UserError(_("Only the responsible user can validate this transfer."))

            # 1️⃣ Mark existing activities as done
            activities = Activity.search([
                ('res_model', '=', 'stock.picking'),
                ('res_id', '=', picking.id),
                ('user_id','=',picking.responsible_user_id.id)
            ])
            if activities:
                activities.action_feedback(
                    feedback=_("Transfer validated by %s") % self.env.user.name
                )

            # 2️⃣ Create new activity for the creator
            if picking.create_uid:
                picking.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=picking.create_uid.id,
                    summary=_("Transfer marked as To Do"),
                    note=_("The transfer has been validated by %s") % self.env.user.name,
                )
                # Activity.create({
                #     'res_model': 'stock.picking',
                #     'res_id': picking.id,
                #     'activity_type_id': activity_type.id,
                #     'user_id': picking.create_uid.id,
                #     'summary': _("Transfer validated"),
                #     'note': _("The transfer has been validated by %s.") % self.env.user.name,
                # })

        return res


class StockMove(models.Model):
    _inherit = 'stock.move'

    source_location_qty = fields.Float(
        string="On Hand",
        compute="_compute_source_location_qty",
        digits='Product Unit of Measure'
    )
    label_id = fields.Many2one(
        'product.label',
        string="Label",
    )



    @api.depends('product_id', 'location_id','product_uom_qty')
    def _compute_source_location_qty(self):
        for move in self:
            qty = 0.0
            if move.product_id and move.location_id:
                qty = self.env['stock.quant']._get_available_quantity(
                    move.product_id,
                    move.location_id,
                    strict=True
                )
            move.source_location_qty = qty


