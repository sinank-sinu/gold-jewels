# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: Ammu Raj (odoo@cybrosys.com)
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
################################################################################
import io
import json
from dateutil.relativedelta import relativedelta
import xlsxwriter
from datetime import datetime
from odoo.tools import date_utils
from odoo import api, fields, models


class CashBookReport(models.TransientModel):
    """For creating Cash Book report"""
    _name = 'cash.book.report'
    _description = 'Account Cash Book Report'

    def _summary_from_filters(self, partner_id=None, date_range=None, account_list=None, options=None, branch_list=None):
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
        if account_list:
            domain.append(('account_id', 'in', account_list))
            
        has_branch = hasattr(self.env['account.move'], 'branch_id')
        if branch_list and has_branch:
            domain.append(('move_id.branch_id', 'in', branch_list))
            
        if date_range:
            today = fields.Date.today()
            quarter_start, quarter_end = date_utils.get_quarter(today)
            previous_quarter_start = quarter_start - relativedelta(months=3)
            previous_quarter_end = quarter_start - relativedelta(days=1)
            
            if date_range == 'month':
                domain.append(('date', '>=', today.replace(day=1)))
                domain.append(('date', '<=', (today + relativedelta(months=1, day=1)) - relativedelta(days=1)))
            elif date_range == 'year':
                domain.append(('date', '>=', today.replace(month=1, day=1)))
                domain.append(('date', '<=', today.replace(month=12, day=31)))
            elif date_range == 'quarter':
                domain += [('date', '>=', quarter_start), ('date', '<=', quarter_end)]
            elif date_range == 'last-month':
                last_month = today - relativedelta(months=1)
                domain.append(('date', '>=', last_month.replace(day=1)))
                domain.append(('date', '<=', (last_month + relativedelta(months=1, day=1)) - relativedelta(days=1)))
            elif date_range == 'last-year':
                last_year = today - relativedelta(years=1)
                domain.append(('date', '>=', last_year.replace(month=1, day=1)))
                domain.append(('date', '<=', last_year.replace(month=12, day=31)))
            elif date_range == 'last-quarter':
                domain += [('date', '>=', previous_quarter_start), ('date', '<=', previous_quarter_end)]
            elif isinstance(date_range, dict):
                if 'start_date' in date_range and date_range['start_date']:
                    domain.append(('date', '>=', datetime.strptime(date_range['start_date'], '%Y-%m-%d').date()))
                if 'end_date' in date_range and date_range['end_date']:
                    domain.append(('date', '<=', datetime.strptime(date_range['end_date'], '%Y-%m-%d').date()))

        groups = self.env['account.move.line'].read_group(
            domain,
            ['account_id', 'debit:sum', 'credit:sum'],
            ['account_id']
        )
        
        data = {}
        move_lines_total = {}
        accounts = []
        currency_id = self.env.company.currency_id.symbol
        for g in groups:
            if not g['account_id']:
                continue
            acc_id, acc_name = g['account_id']
            accounts.append({'id': acc_id, 'name': acc_name, 'display_name': acc_name})
            data[acc_name] = []
            move_lines_total[acc_name] = {
                'total_debit': round(g['debit'] or 0.0, 2),
                'total_credit': round(g['credit'] or 0.0, 2),
                'currency_id': currency_id,
                'account_id': acc_id,
                'line_count': g['account_id_count']
            }
            
        data['move_lines_total'] = move_lines_total
        data['accounts'] = accounts
        return data

    @api.model
    def view_report(self):
        return self._summary_from_filters()

    @api.model
    def get_account_lines(self, account_id, journal_id=None, partner_id=None,
                          date_range=None, options=None, branch_ids=None,
                          limit=500, offset=0, known_total=None):
        journals = self.env['account.journal'].search([('type', '=', 'cash')])
        option_domain = ['posted']
        if options is not None and 'draft' in options:
            option_domain = ['posted', 'draft']
            
        domain = [
            ('parent_state', 'in', option_domain),
            ('journal_id', 'in', journals.ids),
            ('account_id', '=', account_id),
        ]
        if partner_id:
            domain.append(('partner_id', 'in', partner_id))
            
        has_branch = hasattr(self.env['account.move'], 'branch_id')
        if branch_ids and has_branch:
            domain.append(('move_id.branch_id', 'in', branch_ids))
            
        if date_range:
            today = fields.Date.today()
            quarter_start, quarter_end = date_utils.get_quarter(today)
            previous_quarter_start = quarter_start - relativedelta(months=3)
            previous_quarter_end = quarter_start - relativedelta(days=1)
            
            if date_range == 'month':
                domain.append(('date', '>=', today.replace(day=1)))
                domain.append(('date', '<=', (today + relativedelta(months=1, day=1)) - relativedelta(days=1)))
            elif date_range == 'year':
                domain.append(('date', '>=', today.replace(month=1, day=1)))
                domain.append(('date', '<=', today.replace(month=12, day=31)))
            elif date_range == 'quarter':
                domain += [('date', '>=', quarter_start), ('date', '<=', quarter_end)]
            elif date_range == 'last-month':
                last_month = today - relativedelta(months=1)
                domain.append(('date', '>=', last_month.replace(day=1)))
                domain.append(('date', '<=', (last_month + relativedelta(months=1, day=1)) - relativedelta(days=1)))
            elif date_range == 'last-year':
                last_year = today - relativedelta(years=1)
                domain.append(('date', '>=', last_year.replace(month=1, day=1)))
                domain.append(('date', '<=', last_year.replace(month=12, day=31)))
            elif date_range == 'last-quarter':
                domain += [('date', '>=', previous_quarter_start), ('date', '<=', previous_quarter_end)]
            elif isinstance(date_range, dict):
                if 'start_date' in date_range and date_range['start_date']:
                    domain.append(('date', '>=', datetime.strptime(date_range['start_date'], '%Y-%m-%d').date()))
                if 'end_date' in date_range and date_range['end_date']:
                    domain.append(('date', '<=', datetime.strptime(date_range['end_date'], '%Y-%m-%d').date()))

        # Search move lines
        move_lines = self.env['account.move.line'].search(domain, order='date asc, id asc')
        total = len(move_lines)
        
        # Paginate
        if limit:
            paginated_lines = move_lines[offset:offset+limit]
        else:
            paginated_lines = move_lines
            
        # Read fields
        fields_to_read = ['date', 'journal_id', 'partner_id', 'move_name', 'debit', 'move_id', 'credit', 'name', 'ref']
        lines_data = paginated_lines.read(fields_to_read)
        
        # Inject branch details if present
        for line, raw_data in zip(paginated_lines, lines_data):
            if has_branch and line.move_id and line.move_id.branch_id:
                raw_data['branch_id'] = [line.move_id.branch_id.id, line.move_id.branch_id.name]
            else:
                raw_data['branch_id'] = False
                
        return {
            'lines': lines_data,
            'total': total,
            'offset': offset
        }

    @api.model
    def get_filter_values(self, partner_id, data_range, account_list, options):
        return self._summary_from_filters(partner_id, data_range, account_list, options)

    @api.model
    def get_xlsx_report(self, data, response, report_name, report_action):
        """
        Generate an Excel report based on the provided data.
        :param data: The data used to generate the report.
        :type data: str (JSON format)
        :param response: The response object to write the report to.
        :type response: object
        :param report_name: The name of the report.
        :type report_name: str
        :return: None
        """
        data = json.loads(data)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        start_date = data['filters']['start_date'] if \
            data['filters']['start_date'] else ''
        end_date = data['filters']['end_date'] if \
            data['filters']['end_date'] else ''
        sheet = workbook.add_worksheet()
        head = workbook.add_format(
            {'align': 'center', 'bold': True, 'font_size': '15px'})
        sub_heading = workbook.add_format(
            {'align': 'center', 'bold': True, 'font_size': '10px',
             'border': 1, 'bg_color': '#D3D3D3',
             'border_color': 'black'})
        filter_head = workbook.add_format(
            {'align': 'center', 'bold': True, 'font_size': '10px',
             'border': 1, 'bg_color': '#D3D3D3',
             'border_color': 'black'})
        filter_body = workbook.add_format(
            {'align': 'center', 'bold': True, 'font_size': '10px'})
        side_heading_sub = workbook.add_format(
            {'align': 'left', 'bold': True, 'font_size': '10px',
             'border': 1,
             'border_color': 'black'})
        side_heading_sub.set_indent(1)
        txt_name = workbook.add_format({'font_size': '10px', 'border': 1})
        txt_name.set_indent(2)
        sheet.set_column(0, 0, 30)
        sheet.set_column(1, 1, 20)
        sheet.set_column(2, 2, 15)
        sheet.set_column(3, 3, 15)
        col = 0
        sheet.write('A1:b1', report_name, head)
        sheet.write('B3:b4', 'Date Range', filter_head)
        sheet.write('B4:b4', 'Partners', filter_head)
        sheet.write('B5:b4', 'Accounts', filter_head)
        sheet.write('B6:b4', 'Options', filter_head)
        if start_date or end_date:
            sheet.merge_range('C3:G3', f"{start_date} to {end_date}",
                              filter_body)
        if data['filters']['partner']:
            display_names = [partner.get('display_name', 'undefined') for
                             partner in data['filters']['partner']]
            display_names_str = ', '.join(display_names)
            sheet.merge_range('C4:G4', display_names_str, filter_body)
        if data['filters']['account']:
            account_keys_str = ', '.join(data['filters']['account'])
            sheet.merge_range('C5:G5', account_keys_str, filter_body)
        if data['filters']['options']:
            option_keys = list(data['filters']['options'].keys())
            option_keys_str = ', '.join(option_keys)
            sheet.merge_range('C6:G6', option_keys_str, filter_body)
        if data:
            if report_action == 'dynamic_accounts_report.action_cash_book':
                sheet.write(8, col, ' ', sub_heading)
                sheet.merge_range('B9:C9', 'Journal', sub_heading)
                sheet.merge_range('D9:E9', 'Partner', sub_heading)
                sheet.merge_range('F9:G9', 'Ref', sub_heading)
                sheet.merge_range('H9:I9', 'Move', sub_heading)
                sheet.merge_range('J9:K9', 'Entry Label', sub_heading)
                sheet.merge_range('L9:M9', 'Debit', sub_heading)
                sheet.merge_range('N9:O9', 'Credit', sub_heading)
                sheet.merge_range('P9:Q9', 'Balance', sub_heading)
                row = 8
                for move_line in data['move_lines']:
                    row += 1
                    sheet.write(row, col, move_line, txt_name)
                    sheet.merge_range(row, col + 1, row, col + 2, ' ',
                                      txt_name)
                    sheet.merge_range(row, col + 3, row, col + 4, ' ',
                                      txt_name)
                    sheet.merge_range(row, col + 5, row, col + 6, ' ',
                                      txt_name)
                    sheet.merge_range(row, col + 7, row, col + 8, ' ',
                                      txt_name)
                    sheet.merge_range(row, col + 9, row, col + 10, ' ',
                                      txt_name)
                    sheet.merge_range(row, col + 11, row, col + 12,
                                      data['total'][move_line]['total_debit'],
                                      txt_name)
                    sheet.merge_range(row, col + 13, row, col + 14,
                                      data['total'][move_line]['total_credit'],
                                      txt_name)
                    sheet.merge_range(row, col + 15, row, col + 16,
                                      data['total'][move_line]['total_debit'] -
                                      data['total'][move_line]['total_credit'],
                                      txt_name)
                    for rec in data['data'][move_line]:
                        row += 1
                        if rec['partner_id']:
                            partner = rec['partner_id'][1]
                        else:
                            partner = ' '
                        sheet.write(row, col, rec['date'], txt_name)
                        sheet.merge_range(row, col + 1, row, col + 2,
                                          rec['journal_id'][1],
                                          txt_name)
                        sheet.merge_range(row, col + 3, row, col + 4, partner,
                                          txt_name)
                        sheet.merge_range(row, col + 5, row, col + 6,
                                          rec['ref'], txt_name)
                        sheet.merge_range(row, col + 7, row, col + 8,
                                          rec['move_name'],
                                          txt_name)
                        sheet.merge_range(row, col + 9, row, col + 10,
                                          rec['name'],
                                          txt_name)
                        sheet.merge_range(row, col + 11, row, col + 12,
                                          rec['debit'], txt_name)
                        sheet.merge_range(row, col + 13, row, col + 14,
                                          rec['credit'], txt_name)
                        sheet.merge_range(row, col + 15, row, col + 16, ' ',
                                          txt_name)
                sheet.merge_range(row + 1, col, row + 1, col + 10, 'Total',
                                  filter_head)
                sheet.merge_range(row + 1, col + 11, row + 1, col + 12,
                                  data['grand_total']['total_debit'],
                                  filter_head)
                sheet.merge_range(row + 1, col + 13, row + 1, col + 14,
                                  data['grand_total']['total_credit'],
                                  filter_head)
                sheet.merge_range(row + 1, col + 15, row + 1, col + 16,
                                  float(data['grand_total']['total_debit']) -
                                  float(data['grand_total']['total_credit']),
                                  filter_head)
        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
