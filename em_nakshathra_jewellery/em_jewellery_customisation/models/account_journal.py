from odoo import models, api, fields, _
from odoo.exceptions import UserError


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def write(self, vals):
        if 'code' in vals:
            for journal in self:
                if vals['code'] != journal.code:
                    has_entries = self.env['account.move'].sudo().search_count([
                        ('journal_id', '=', journal.id)
                    ], limit=1)
                    if has_entries:
                        raise UserError(_("You cannot modify the Short Code of a journal with existing entries."))
        return super().write(vals)
