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
import calendar
from dateutil.relativedelta import relativedelta
import xlsxwriter
from odoo import api, fields, models
from datetime import datetime
from odoo.tools import date_utils


class AccountGeneralLedger(models.TransientModel):
    """For creating General Ledger report"""
    _name = 'account.general.ledger'
    _description = 'General Ledger Report'

    def _build_filter_domain(self, journal_id, date_range, options, analytic,
                              method):
        """Build move-line domain from the JS filter state."""
        today = fields.Date.today()
        quarter_start, quarter_end = date_utils.get_quarter(today)
        previous_quarter_start = quarter_start - relativedelta(months=3)
        previous_quarter_end = quarter_start - relativedelta(days=1)
        if options == {}:
            options = None
        option_domain = ['posted', 'draft'] if (options and 'draft' in options) \
            else ['posted']
        domain = [('journal_id', 'in', journal_id),
                  ('parent_state', 'in', option_domain)] if journal_id else [
            ('parent_state', 'in', option_domain)]
        if method == {}:
            method = None
        if method and 'cash' in method:
            domain += [('journal_id', 'in',
                        self.env.company.tax_cash_basis_journal_id.ids)]
        if analytic:
            analytic_line_ids = self.env['account.analytic.line'].search(
                [('account_id', 'in', analytic)]).ids
            domain += [('analytic_line_ids', 'in', analytic_line_ids)]
        if date_range:
            if date_range == 'month':
                domain += [('date', '>=', today.replace(day=1)),
                           ('date', '<=', today)]
            elif date_range == 'year':
                domain += [('date', '>=', today.replace(month=1, day=1)),
                           ('date', '<=', today)]
            elif date_range == 'quarter':
                domain += [('date', '>=', quarter_start),
                           ('date', '<=', quarter_end)]
            elif date_range == 'last-month':
                lm_start = today.replace(day=1) - relativedelta(months=1)
                lm_end = lm_start + relativedelta(
                    day=calendar.monthrange(lm_start.year, lm_start.month)[1])
                domain += [('date', '>=', lm_start), ('date', '<=', lm_end)]
            elif date_range == 'last-year':
                ly_start = today.replace(month=1, day=1) - relativedelta(years=1)
                ly_end = ly_start.replace(month=12, day=31)
                domain += [('date', '>=', ly_start), ('date', '<=', ly_end)]
            elif date_range == 'last-quarter':
                domain += [('date', '>=', previous_quarter_start),
                           ('date', '<=', previous_quarter_end)]
            elif isinstance(date_range, dict):
                if 'start_date' in date_range and date_range['start_date']:
                    domain += [('date', '>=', datetime.strptime(
                        date_range['start_date'], '%Y-%m-%d').date())]
                if 'end_date' in date_range and date_range['end_date']:
                    domain += [('date', '<=', datetime.strptime(
                        date_range['end_date'], '%Y-%m-%d').date())]
        return domain

    def _summary_from_domain(self, domain):
        """Return account_dict with summaries only (no line details).
        line_count is included free from read_group so get_account_lines
        never needs a separate search_count.
        """
        account_dict = {}
        account_totals = {}
        currency_id = self.env.company.currency_id.symbol
        groups = self.env['account.move.line'].read_group(
            domain,
            ['account_id', 'debit:sum', 'credit:sum'],
            ['account_id'],
        )
        for group in groups:
            if not group['account_id']:
                continue
            acc_id, acc_name = group['account_id']
            account_dict[acc_name] = []
            account_totals[acc_name] = {
                'total_debit': round(group['debit'] or 0.0, 2),
                'total_credit': round(group['credit'] or 0.0, 2),
                'currency_id': currency_id,
                'account_id': acc_id,
                'line_count': group['account_id_count'],  # free from read_group
            }
        account_dict['account_totals'] = account_totals
        return account_dict

    @api.model
    def view_report(self, option, tag):
        """Return account summaries only — lines are fetched lazily per account."""
        domain = [('parent_state', '=', 'posted')]
        account_dict = self._summary_from_domain(domain)
        account_dict['journal_ids'] = self.env['account.journal'].search_read(
            [], ['name'])
        account_dict['analytic_ids'] = self.env[
            'account.analytic.account'].search_read([], ['name'])
        return account_dict

    @api.model
    def get_pdf_data(self, filters):
        """Fetch all data for PDF generation entirely server-side.
        filters format from JS filter():
          journal   = list of journal name strings
          analytic  = list of analytic name strings
          options   = dict  (e.g. {'draft': True})
          start_date / end_date = 'YYYY-MM-DD' strings or null
        """
        options    = filters.get('options') or {}
        start_date = filters.get('start_date')
        end_date   = filters.get('end_date')

        # Resolve journal names → IDs
        journal_names = [n for n in (filters.get('journal') or []) if n]
        journal_ids   = []
        if journal_names:
            journal_ids = self.env['account.journal'].search(
                [('name', 'in', journal_names)]).ids

        # Build filter domain using existing helper
        date_range = None
        if start_date or end_date:
            date_range = {}
            if start_date:
                date_range['start_date'] = start_date
            if end_date:
                date_range['end_date'] = end_date

        if journal_ids or date_range or options:
            domain = self._build_filter_domain(
                journal_ids, date_range, options, None, None)
        else:
            domain = [('parent_state', '=', 'posted')]

        # Account summaries via read_group (fast)
        summary        = self._summary_from_domain(domain)
        account_totals = summary.get('account_totals', {})
        account_names  = [k for k in summary
                          if k not in ('account_totals', 'journal_ids', 'analytic_ids')]
        currency_id    = self.env.company.currency_id.symbol

        # Build SQL WHERE for line fetching
        option_domain = ['posted', 'draft'] if (options and 'draft' in options) \
            else ['posted']
        where_parts = ["AND aml.parent_state = ANY(%s)"]
        params      = (option_domain,)
        if journal_ids:
            where_parts.append("AND aml.journal_id = ANY(%s)")
            params += (journal_ids,)
        if start_date:
            where_parts.append("AND aml.date >= %s")
            params += (start_date,)
        if end_date:
            where_parts.append("AND aml.date <= %s")
            params += (end_date,)
        where_extra = ' '.join(where_parts)

        # Fetch lines per account with fast SQL JOIN
        data = {}
        for acc_name in account_names:
            acc_id = account_totals[acc_name]['account_id']
            lines  = self._account_lines_sql(
                acc_id, where_extra, params, limit=0, offset=0)
            data[acc_name] = [[line] for line in lines]

        total_debit  = sum(v.get('total_debit',  0) for v in account_totals.values())
        total_credit = sum(v.get('total_credit', 0) for v in account_totals.values())
        return {
            'account':     account_names,
            'data':        data,
            'total':       account_totals,
            'grand_total': {
                'total_debit':  round(total_debit,  2),
                'total_credit': round(total_credit, 2),
                'currency':     currency_id,
            },
        }

    def _account_lines_sql(self, account_id, where_extra='', params_extra=(),
                            limit=500, offset=0):
        """Single raw-SQL query — JOIN partner+move in one round-trip.
        Returns a list of dicts already formatted to match ORM Many2one style.
        """
        limit_clause = 'LIMIT %s' % limit if limit else ''
        sql = """
            SELECT
                aml.id,
                aml.date,
                aml.name,
                aml.move_name,
                aml.debit,
                aml.credit,
                aml.partner_id,
                rp.name       AS partner_name,
                aml.account_id,
                aml.journal_id,
                aml.move_id,
                am.name       AS move_ref
            FROM account_move_line aml
            LEFT JOIN res_partner   rp ON rp.id = aml.partner_id
            LEFT JOIN account_move  am ON am.id = aml.move_id
            WHERE aml.account_id = %%s
              AND aml.company_id = ANY(%%s)
              %s
            ORDER BY aml.id ASC
            %s
            OFFSET %%s
        """ % (where_extra, limit_clause)

        company_ids = list(self.env.companies.ids)
        self.env.cr.execute(sql, (account_id, company_ids) + params_extra + (offset,))
        rows = self.env.cr.dictfetchall()

        lines = []
        for r in rows:
            lines.append({
                'id':         r['id'],
                'date':       r['date'],
                'name':       r['name'] or '',
                'move_name':  r['move_name'] or '',
                'debit':      r['debit'] or 0.0,
                'credit':     r['credit'] or 0.0,
                'partner_id': [r['partner_id'], r['partner_name']]
                              if r['partner_id'] else False,
                'account_id': [r['account_id'], ''],
                'journal_id': [r['journal_id'], ''],
                'move_id':    [r['move_id'], r['move_ref'] or ''],
            })
        return lines

    @api.model
    def get_account_lines(self, account_id, journal_id=None, date_range=None,
                          options=None, analytic=None, method=None,
                          limit=500, offset=0, known_total=None):
        """Fetch paginated journal lines for a single account.

        limit=0 → no limit (used by print/export).
        known_total → skips search_count.
        Returns {lines, total, offset}.
        """
        # Build extra WHERE fragments for filters
        where_parts = ["AND aml.parent_state = ANY(%s)"]
        params = ()

        if options == {}:
            options = None
        state_list = ['posted', 'draft'] if (options and 'draft' in options) \
            else ['posted']
        params += (state_list,)

        if journal_id:
            where_parts.append("AND aml.journal_id = ANY(%s)")
            params += (journal_id,)

        if date_range and isinstance(date_range, dict):
            if date_range.get('start_date'):
                where_parts.append("AND aml.date >= %s")
                params += (date_range['start_date'],)
            if date_range.get('end_date'):
                where_parts.append("AND aml.date <= %s")
                params += (date_range['end_date'],)
        elif date_range and isinstance(date_range, str):
            today = fields.Date.today()
            quarter_start, quarter_end = date_utils.get_quarter(today)
            prev_qs = quarter_start - relativedelta(months=3)
            prev_qe = quarter_start - relativedelta(days=1)
            date_map = {
                'month':        (today.replace(day=1), today),
                'year':         (today.replace(month=1, day=1), today),
                'quarter':      (quarter_start, quarter_end),
                'last-month':   (today.replace(day=1) - relativedelta(months=1),
                                 today.replace(day=1) - relativedelta(days=1)),
                'last-year':    (today.replace(month=1, day=1) - relativedelta(years=1),
                                 today.replace(month=1, day=1) - relativedelta(days=1)),
                'last-quarter': (prev_qs, prev_qe),
            }
            if date_range in date_map:
                s, e = date_map[date_range]
                where_parts.append("AND aml.date BETWEEN %s AND %s")
                params += (s, e)

        where_extra = ' '.join(where_parts)

        # Count: use known_total when available (free from read_group summary)
        if known_total is not None:
            total = known_total
        else:
            count_sql = """
                SELECT COUNT(*) FROM account_move_line aml
                WHERE aml.account_id = %%s
                  AND aml.company_id = ANY(%%s)
                  %s
            """ % where_extra
            self.env.cr.execute(count_sql,
                                (account_id, list(self.env.companies.ids)) + params)
            total = self.env.cr.fetchone()[0]

        lines = self._account_lines_sql(
            account_id, where_extra, params, limit=limit, offset=offset)

        return {'lines': [[line] for line in lines], 'total': total,
                'offset': offset}

    @api.model
    def get_filter_values(self, journal_id, date_range, options, analytic,
                          method):
        """Return account summaries for the given filters — lines loaded lazily."""
        domain = self._build_filter_domain(
            journal_id, date_range, options, analytic, method)
        account_dict = self._summary_from_domain(domain)
        account_dict['journal_ids'] = self.env['account.journal'].search_read(
            [], ['name'])
        account_dict['analytic_ids'] = self.env[
            'account.analytic.account'].search_read([], ['name'])
        return account_dict

    @api.model
    def get_xlsx_report(self, data, response, report_name, report_action):
        """
        Generate an XLSX report based on the provided data and write it to the
        response stream.

        :param data: The data used to generate the report.
        :type data: str (JSON format)

        :param response: The response object to write the generated report to.
        :type response: werkzeug.wrappers.Response

        :param report_name: The name of the report.
        :type report_name: str
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
        sheet.write('B4:b4', 'Journals', filter_head)
        sheet.write('B5:b4', 'Analytic', filter_head)
        sheet.write('B6:b4', 'Options', filter_head)
        if start_date or end_date:
            sheet.merge_range('C3:G3', f"{start_date} to {end_date}",
                              filter_body)
        if data['filters']['journal']:
            display_names = [journal for
                             journal in data['filters']['journal']]
            display_names_str = ', '.join(display_names)
            sheet.merge_range('C4:G4', display_names_str, filter_body)
        if data['filters']['analytic']:
            display_names = [analytic for
                             analytic in data['filters']['analytic']]
            account_keys_str = ', '.join(display_names)
            sheet.merge_range('C5:G5', account_keys_str, filter_body)
        if data['filters']['options']:
            option_keys = list(data['filters']['options'].keys())
            option_keys_str = ', '.join(option_keys)
            sheet.merge_range('C6:G6', option_keys_str, filter_body)
        if data:
            if report_action == 'dynamic_accounts_report.action_general_ledger':
                sheet.write(8, col, ' ', sub_heading)
                sheet.write(8, col + 1, 'Date', sub_heading)
                sheet.merge_range('C9:E9', 'Communication', sub_heading)
                sheet.merge_range('F9:G9', 'Partner', sub_heading)
                sheet.merge_range('H9:I9', 'Debit', sub_heading)
                sheet.merge_range('J9:K9', 'Credit', sub_heading)
                sheet.merge_range('L9:M9', 'Balance', sub_heading)
                row = 8
                for account in data['account']:
                    row += 1
                    sheet.write(row, col, account, txt_name)
                    sheet.write(row, col + 1, ' ', txt_name)
                    sheet.merge_range(row, col + 2, row, col + 4, ' ', txt_name)
                    sheet.merge_range(row, col + 5, row, col + 6, ' ',
                                      txt_name)
                    sheet.merge_range(row, col + 7, row, col + 8,
                                      data['total'][account]['total_debit'],
                                      txt_name)
                    sheet.merge_range(row, col + 9, row, col + 10,
                                      data['total'][account]['total_credit'],
                                      txt_name)
                    sheet.merge_range(row, col + 11, row, col + 12,
                                      data['total'][account]['total_debit'] -
                                      data['total'][account]['total_credit'],
                                      txt_name)
                    for rec in data['data'][account]:
                        row += 1
                        partner = rec[0]['partner_id']
                        name = partner[1] if partner else None
                        sheet.write(row, col, rec[0]['move_name'], txt_name)
                        sheet.write(row, col + 1, rec[0]['date'], txt_name)
                        sheet.merge_range(row, col + 2, row, col + 4,
                                          rec[0]['name'], txt_name)
                        sheet.merge_range(row, col + 5, row, col + 6, name,
                                          txt_name)
                        sheet.merge_range(row, col + 7, row, col + 8,
                                          rec[0]['debit'],
                                          txt_name)
                        sheet.merge_range(row, col + 9, row, col + 10,
                                          rec[0]['credit'], txt_name)
                        sheet.merge_range(row, col + 11, row, col + 12, ' ',
                                          txt_name)
                row += 1
                sheet.merge_range(row, col, row, col + 6, 'Total',
                                  filter_head)
                sheet.merge_range(row, col + 7, row, col + 8,
                                  data['grand_total']['total_debit'],
                                  filter_head)
                sheet.merge_range(row, col + 9, row, col + 10,
                                  data['grand_total']['total_credit'],
                                  filter_head)
                sheet.merge_range(row, col + 11, row, col + 12,
                                  float(data['grand_total']['total_debit']) -
                                  float(data['grand_total']['total_credit']),
                                  filter_head)
        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
