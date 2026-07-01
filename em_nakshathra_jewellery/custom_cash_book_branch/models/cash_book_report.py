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
        data = {}
        move_lines_total = {}
        today = fields.Date.today()
        quarter_start, quarter_end = date_utils.get_quarter(today)
        previous_quarter_start = quarter_start - relativedelta(months=3)
        previous_quarter_end = quarter_start - relativedelta(days=1)
        journals = self.env['account.journal'].search([('type', '=', 'cash')])
        
        option_domain = ['posted']
        if options is not None and 'draft' in options:
            option_domain = ['posted', 'draft']
            
        domain = [
            ('parent_state', 'in', option_domain),
            ('journal_id', 'in', journals.ids),
        ]
        if partner_id:
            domain.append(('partner_id', 'in', partner_id))
            
        # --- Inject Custom Branch Domain Filter Entry ---
        if branch_list:
            domain.append(('move_id.branch_id', 'in', branch_list))

        if account_list:
            domain.append(('account_id', 'in', account_list))
            
        if data_range:
            if data_range == 'month':
                account_move_lines = self.env['account.move.line'].search(domain).filtered(
                    lambda x: x.date.month == fields.Date.today().month)
            elif data_range == 'year':
                account_move_lines = self.env['account.move.line'].search(domain).filtered(
                    lambda x: x.date.year == fields.Date.today().year)
            elif data_range == 'quarter':
                domain += [('date', '>=', quarter_start), ('date', '<=', quarter_end)]
                account_move_lines = self.env['account.move.line'].search(domain)
            elif data_range == 'last-month':
                account_move_lines = self.env['account.move.line'].search(domain).filtered(
                    lambda x: x.date.month == fields.Date.today().month - 1)
            elif data_range == 'last-year':
                account_move_lines = self.env['account.move.line'].search(domain).filtered(
                    lambda x: x.date.year == fields.Date.today().year - 1)
            elif data_range == 'last-quarter':
                domain += [('date', '>=', previous_quarter_start), ('date', '<=', previous_quarter_end)]
                account_move_lines = self.env['account.move.line'].search(domain)
            elif 'start_date' in data_range and 'end_date' in data_range:
                start_date = datetime.strptime(data_range['start_date'], '%Y-%m-%d').date()
                end_date = datetime.strptime(data_range['end_date'], '%Y-%m-%d').date()
                domain += [('date', '>=', start_date), ('date', '<=', end_date)]
                account_move_lines = self.env['account.move.line'].search(domain)
            elif 'start_date' in data_range:
                start_date = datetime.strptime(data_range['start_date'], '%Y-%m-%d').date()
                domain.append(('date', '>=', start_date))
                account_move_lines = self.env['account.move.line'].search(domain)
            elif 'end_date' in data_range:
                end_date = datetime.strptime(data_range['end_date'], '%Y-%m-%d').date()
                domain.append(('date', '<=', end_date))
                account_move_lines = self.env['account.move.line'].search(domain)
        else:
            account_move_lines = self.env['account.move.line'].search(domain)

        accounts = account_move_lines.mapped('account_id').read(['display_name'])
        for account in accounts:
            move_lines = account_move_lines.filtered(lambda x: x.account_id.id == account['id'])
            move_line_data = move_lines.read(['date', 'journal_id', 'partner_id', 'move_name', 'debit', 'move_id', 'credit', 'name', 'ref'])
            
            # Inject dynamic branch elements row details
            for line, raw_data in zip(move_lines, move_line_data):
                if line.move_id and hasattr(line.move_id, 'branch_id') and line.move_id.branch_id:
                    raw_data['branch_id'] = [line.move_id.branch_id.id, line.move_id.branch_id.name]
                else:
                    raw_data['branch_id'] = False
                    
            data[move_lines.mapped('account_id').display_name] = move_line_data
            currency_id = self.env.company.currency_id.symbol
            move_lines_total[move_lines.mapped('account_id').display_name] = {
                'total_debit': round(sum(move_lines.mapped('debit')), 2),
                'total_credit': round(sum(move_lines.mapped('credit')), 2),
                'currency_id': currency_id,
                'account_id': account['id'],
                'line_count': len(move_lines)
            }
            
        branches = self.env['res.branch'].search([]).read(['id', 'name'])
        data['branches'] = branches
        data['accounts'] = accounts
        data['move_lines_total'] = move_lines_total
        return data