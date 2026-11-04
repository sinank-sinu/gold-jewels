# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2022-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    """inherited account payment register wizard models"""
    _inherit = 'account.payment.register'

    branch_id = fields.Many2one('res.branch', store=True, readonly=False)
    journal_id = fields.Many2one('account.journal', store=True, readonly=False,
                                 compute='_compute_journal_id',
                                 domain="[('company_id', '=', company_id), "
                                        "('type', 'in', ('bank', 'cash')), ('branch_id', '=', branch_id)]")

    def _compute_journal_id(self):
        """Choose a payment journal from the invoice's branch."""
        for wizard in self:
            branches = wizard.line_ids.move_id.branch_id
            if len(branches) > 1:
                raise UserError(_("A payment cannot combine journal items from different branches."))
            branch = branches[:1]
            if not branch:
                super(AccountPaymentRegister, wizard)._compute_journal_id()
                continue

            wizard.branch_id = branch
            domain = [
                ('company_id', '=', branch.company_id.id),
                ('type', 'in', ('bank', 'cash')),
                ('branch_id', '=', branch.id),
                ('id', 'in', wizard.available_journal_ids.ids),
            ]
            journal = self.env['account.journal'].search(domain, limit=1)
            if not journal:
                raise UserError(_(
                    "No available bank or cash journal is configured for branch %s.",
                    branch.name,
                ))
            wizard.journal_id = journal

    def action_create_payments(self):
        from odoo.exceptions import ValidationError
        for rec in self:
            if rec.branch_id:
                if not rec.journal_id:
                    raise ValidationError("No Bank/Cash journal found for this branch. Please create a journal for this branch.")
                if rec.journal_id.branch_id != rec.branch_id:
                    raise ValidationError("The selected journal does not belong to the same branch. Please select a journal for this branch.")
        return super(AccountPaymentRegister, self).action_create_payments()

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        vals.update({'branch_id': self.line_ids.move_id[0].branch_id.id})
        return vals
