from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    bank_reference = fields.Char(related="payment_id.bank_reference", string="Bank Reference", store=True)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, access_rights_uid=None):
        if self.env.context.get('tree_view_ref') == 'account_reconcile_oca.account_move_line_tree_reconcile_view':
            domain = list(domain or []) + [('account_id.account_type', 'not in', ('asset_receivable', 'liability_payable'))]
            st_journal_id = self.env.context.get('st_journal_id') or self.env.context.get('default_journal_id')
            if st_journal_id:
                domain.extend(['|', ('journal_id', '=', st_journal_id), ('journal_id.type', 'not in', ('bank', 'cash'))])
        return super()._search(domain, offset=offset, limit=limit, order=order, access_rights_uid=access_rights_uid)


