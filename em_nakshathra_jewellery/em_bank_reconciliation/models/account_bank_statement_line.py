from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    bank_reference = fields.Char(string="Bank Reference Number")

    def _get_st_line_strings_for_matching(self, allowed_fields=None):
        """Override to include bank_reference in the list of strings for matching."""
        st_line_text_values = super()._get_st_line_strings_for_matching(allowed_fields=allowed_fields)
        
        # Add the bank_reference to the token list for matching if it is not restricted,
        # or if it's explicitly allowed. 
        if self.bank_reference:
            st_line_text_values.append(self.bank_reference)

        return st_line_text_values

    def _get_default_amls_matching_domain(self):
        """Override to clean up Bank Reconciliation candidate matching view:
        1. Exclude Debtors (asset_receivable) and Creditors (liability_payable) accounts
           so customer scheme ticket balances do not clutter the bank reconciliation screen.
        2. Restrict matching candidate lines to the current Bank Journal or non-bank/general journals (Suspense/Misc).
        """
        domain = super()._get_default_amls_matching_domain()
        domain.append(('account_id.account_type', 'not in', ('asset_receivable', 'liability_payable')))
        if self.journal_id:
            domain.extend(['|', ('journal_id', '=', self.journal_id.id), ('journal_id.type', 'not in', ('bank', 'cash'))])
            if self.journal_id.branch_id:
                domain.extend(['|', ('branch_id', '=', self.journal_id.branch_id.id), ('branch_id', '=', False)])
        return domain
