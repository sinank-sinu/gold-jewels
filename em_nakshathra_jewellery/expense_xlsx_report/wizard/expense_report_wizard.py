from odoo import models, fields

class ExpenseReportWizard(models.TransientModel):
    _name = 'expense.report.wizard'
    _description = 'Expense Report Wizard'

    date_from = fields.Date(string="Start Date", required=True)
    date_to = fields.Date(string="End Date", required=True)
    account_ids = fields.Many2many(
        'account.account',
        string="Type of Expenses",
        domain=[('account_type', '=', 'expense')]
    )
    branch_ids = fields.Many2many(
        'res.branch',
        string="Branches"
    )

    def action_print_report(self):
        return self.env.ref(
            'expense_xlsx_report.expense_xlsx_report_action'
        ).report_action(self)
