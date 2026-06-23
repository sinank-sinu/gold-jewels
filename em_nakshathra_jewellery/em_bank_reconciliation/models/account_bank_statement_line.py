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
