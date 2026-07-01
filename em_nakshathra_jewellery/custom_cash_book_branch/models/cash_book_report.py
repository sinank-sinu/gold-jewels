# -*- coding: utf-8 -*-
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models
from odoo.tools import date_utils

class CashBookReport(models.TransientModel):
    _inherit = 'cash.book.report'

    @api.model
    def view_report(self):
        # Call the original method to get standard data
        res = super(CashBookReport, self).view_report()
        
        # Inject custom branch data loop into account move lines
        journals = self.env['account.journal'].search([('type', '=', 'cash')])
        account_move_lines = self.env['account.move.line'].search([
            ('parent_state', '=', 'posted'),
            ('journal_id', 'in', journals.ids)
        ])
        
        for account_key in list(res.keys()):
            if account_key in ['move_lines_total', 'accounts']:
                continue
            
            # Map branch details into the data dictionary arrays
            for raw_data in res[account_key]:
                line_id = raw_data.get('id')
                if line_id:
                    line = account_move_lines.browse(line_id)
                    if line.move_id and hasattr(line.move_id, 'branch_id') and line.move_id.branch_id:
                        raw_data['branch_id'] = [line.move_id.branch_id.id, line.move_id.branch_id.name]
                    else:
                        raw_data['branch_id'] = False

        # Fetch all branches for the frontend dropdown menu filter collection
        branches = self.env['res.branch'].search([]).read(['id', 'name'])
        res['branches'] = branches
        return res

    @api.model
    def get_filter_values(self, partner_id, data_range, account_list, options, branch_list=None):
        """
        Overridden to support the additional fifth argument: branch_list
        """
        res = self._summary_from_filters(partner_id, data_range, account_list, options, branch_list)
        branches = self.env['res.branch'].search([]).read(['id', 'name'])
        res['branches'] = branches
        return res