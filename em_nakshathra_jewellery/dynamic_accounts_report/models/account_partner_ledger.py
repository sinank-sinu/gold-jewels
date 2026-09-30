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
import math
import re
from dateutil.relativedelta import relativedelta
import xlsxwriter
from odoo import api, fields, models
from datetime import datetime
from odoo.tools import date_utils


class AccountPartnerLedger(models.TransientModel):
    """For creating Partner Ledger report"""
    _name = 'account.partner.ledger'
    _description = 'Partner Ledger Report'

    @api.model
    def view_report(self, option=None, tag=None):
        """
        Retrieve partner-related data for generating a report.
        Initial load returns page 1 with 80 partners.
        """
        return self.get_filter_values(
            partner_id=None,
            data_range=None,
            account=None,
            options=None,
            page=1,
            page_size=80,
            search_term=None
        )

    @api.model
    def get_filter_values(self, partner_id=None, data_range=None, account=None, options=None,
                          page=1, page_size=80, search_term=None):
        """
        Retrieve filtered and paginated partner-related data for generating a report.
        """
        if options == {}:
            options = None
        if account == {}:
            account = None

        company_id = self.env.company.id
        currency_id = self.env.company.currency_id.symbol

        # Account type filter
        if account is None or ('Receivable' in account and 'Payable' in account):
            account_type_domain = ['asset_receivable', 'liability_payable']
        elif 'Receivable' in account:
            account_type_domain = ['asset_receivable']
        elif 'Payable' in account:
            account_type_domain = ['liability_payable']
        else:
            account_type_domain = ['asset_receivable', 'liability_payable']

        # Status filter (posted vs draft)
        if options and 'draft' in options:
            option_domain = ['posted', 'draft']
        else:
            option_domain = ['posted']

        # Date range parsing
        today = fields.Date.today()
        start_date = None
        end_date = None

        if isinstance(data_range, str):
            if data_range == 'month':
                start_date = today.replace(day=1)
                end_date = today + relativedelta(months=1, day=1, days=-1)
            elif data_range == 'year':
                start_date = today.replace(month=1, day=1)
                end_date = today.replace(month=12, day=31)
            elif data_range == 'quarter':
                quarter_start, quarter_end = date_utils.get_quarter(today)
                start_date = quarter_start
                end_date = quarter_end
            elif data_range == 'last-month':
                first_this_month = today.replace(day=1)
                end_date = first_this_month - relativedelta(days=1)
                start_date = end_date.replace(day=1)
            elif data_range == 'last-year':
                start_date = today.replace(year=today.year - 1, month=1, day=1)
                end_date = today.replace(year=today.year - 1, month=12, day=31)
            elif data_range == 'last-quarter':
                quarter_start, quarter_end = date_utils.get_quarter(today)
                end_date = quarter_start - relativedelta(days=1)
                start_date = end_date - relativedelta(months=3, days=-1)
        elif isinstance(data_range, dict):
            if data_range.get('start_date'):
                try:
                    start_date = datetime.strptime(data_range['start_date'], '%Y-%m-%d').date()
                except Exception:
                    start_date = fields.Date.from_string(data_range['start_date'])
            if data_range.get('end_date'):
                try:
                    end_date = datetime.strptime(data_range['end_date'], '%Y-%m-%d').date()
                except Exception:
                    end_date = fields.Date.from_string(data_range['end_date'])

        # Build SQL where clauses for finding distinct matching partners
        where_clauses = [
            "aml.company_id = %s",
            "aml.parent_state IN %s",
            "aa.account_type IN %s",
            "aml.partner_id IS NOT NULL",
        ]
        params = [company_id, tuple(option_domain), tuple(account_type_domain)]

        if partner_id:
            p_list = [partner_id] if isinstance(partner_id, int) else [p for p in partner_id if p]
            if p_list:
                where_clauses.append("aml.partner_id = ANY(%s)")
                params.append(p_list)

        if search_term and str(search_term).strip():
            term = str(search_term).strip()
            where_clauses.append("(rp.name ILIKE %s OR rp.phone ILIKE %s OR rp.mobile ILIKE %s OR CAST(rp.id AS TEXT) = %s)")
            params.extend([f"%{term}%", f"%{term}%", f"%{term}%", term])

        if end_date:
            where_clauses.append("aml.date <= %s")
            params.append(end_date)

        where_sql = " AND ".join(where_clauses)
        cr = self.env.cr

        # 1. Total matching partners count
        count_sql = f"""
            SELECT count(DISTINCT aml.partner_id)
            FROM account_move_line aml
            JOIN account_account aa ON aml.account_id = aa.id
            JOIN res_partner rp ON aml.partner_id = rp.id
            WHERE {where_sql}
        """
        cr.execute(count_sql, tuple(params))
        total_partners = cr.fetchone()[0] or 0

        # Pagination calculations
        page = max(1, int(page or 1))
        page_size = max(1, int(page_size or 80))
        total_pages = max(1, math.ceil(total_partners / page_size)) if total_partners > 0 else 1
        if page > total_pages:
            page = total_pages
        offset = (page - 1) * page_size

        partner_dict = {}
        partner_totals = {}

        if total_partners > 0:
            # 2. Fetch page partners
            page_sql = f"""
                SELECT aml.partner_id, rp.name, rp.phone, rp.mobile
                FROM account_move_line aml
                JOIN account_account aa ON aml.account_id = aa.id
                JOIN res_partner rp ON aml.partner_id = rp.id
                WHERE {where_sql}
                GROUP BY aml.partner_id, rp.name, rp.phone, rp.mobile
                ORDER BY rp.name ASC, aml.partner_id ASC
                LIMIT %s OFFSET %s
            """
            cr.execute(page_sql, tuple(params + [page_size, offset]))
            page_partners = cr.fetchall()
            page_partner_ids = [p[0] for p in page_partners]

            if page_partner_ids:
                # 3. Batch fetch period move lines for the page partners
                period_domain = [
                    ('company_id', '=', company_id),
                    ('partner_id', 'in', page_partner_ids),
                    ('account_type', 'in', account_type_domain),
                    ('parent_state', 'in', option_domain),
                ]
                if start_date:
                    period_domain.append(('date', '>=', start_date))
                if end_date:
                    period_domain.append(('date', '<=', end_date))

                period_move_lines = self.env['account.move.line'].search(
                    period_domain, order='date asc, id asc'
                )

                # 4. If start_date, batch fetch opening moves for initial balance
                initial_move_lines = self.env['account.move.line']
                if start_date:
                    init_domain = [
                        ('company_id', '=', company_id),
                        ('partner_id', 'in', page_partner_ids),
                        ('account_type', 'in', account_type_domain),
                        ('parent_state', 'in', option_domain),
                        ('date', '<', start_date),
                    ]
                    initial_move_lines = self.env['account.move.line'].search(init_domain)

                # Group lines by partner_id
                period_by_partner = {}
                for line in period_move_lines:
                    period_by_partner.setdefault(line.partner_id.id, []).append(line)

                init_by_partner = {}
                for line in initial_move_lines:
                    init_by_partner.setdefault(line.partner_id.id, []).append(line)

                # Build dictionary for each partner on this page
                for row in page_partners:
                    pid = row[0]
                    pname = row[1]
                    phone = row[2]
                    mobile = row[3]
                    p_name = pname or 'Unknown Partner'
                    p_contact = (mobile or phone or '').strip()
                    if p_contact:
                        clean_name_digits = re.sub(r'\D', '', p_name)
                        clean_contact_digits = re.sub(r'\D', '', p_contact)
                        if clean_name_digits and len(clean_name_digits) >= 7 and (
                            clean_contact_digits.endswith(clean_name_digits) or clean_name_digits.endswith(clean_contact_digits)
                        ):
                            partner_key = p_contact
                        else:
                            partner_key = f"{p_name} ({p_contact})"
                    else:
                        partner_key = p_name

                    if partner_key in partner_dict:
                        partner_key = f"{partner_key} ({pid})"

                    p_lines = period_by_partner.get(pid, [])
                    p_init_lines = init_by_partner.get(pid, [])

                    init_debit = sum(l.debit for l in p_init_lines)
                    init_credit = sum(l.credit for l in p_init_lines)
                    init_balance = init_debit - init_credit

                    move_line_list = []
                    if p_lines:
                        p_records = self.env['account.move.line'].browse([l.id for l in p_lines])
                        # Batch pre-fetch account codes and journal codes
                        acc_ids = list(set(l.account_id.id for l in p_records if l.account_id))
                        jrnl_ids = list(set(l.journal_id.id for l in p_records if l.journal_id))
                        acc_map = {a.id: (a.code or '') for a in self.env['account.account'].browse(acc_ids)}
                        jrnl_map = {j.id: (j.code or '') for j in self.env['account.journal'].browse(jrnl_ids)}

                        # Batch read all line data at once
                        p_lines_data = p_records.read(
                            ['date', 'move_name', 'account_type', 'debit', 'credit',
                             'date_maturity', 'account_id', 'journal_id', 'move_id',
                             'matching_number', 'amount_currency', 'ref']
                        )
                        for item in p_lines_data:
                            aid = item['account_id'][0] if item.get('account_id') else None
                            jid = item['journal_id'][0] if item.get('journal_id') else None
                            item['code'] = acc_map.get(aid, '')
                            item['jrnl'] = jrnl_map.get(jid, '')
                            move_line_list.append([item])

                    tot_debit = sum(l.debit for l in p_lines)
                    tot_credit = sum(l.credit for l in p_lines)

                    partner_dict[partner_key] = move_line_list
                    partner_totals[partner_key] = {
                        'total_debit': round(tot_debit, 2),
                        'total_credit': round(tot_credit, 2),
                        'currency_id': currency_id,
                        'initial_balance': round(init_balance, 2),
                        'partner_id': pid,
                        'move_name': 'Initial Balance',
                        'initial_debit': round(init_debit, 2),
                        'initial_credit': round(init_credit, 2),
                    }

        partner_dict['partner_totals'] = partner_totals
        partner_dict['pagination'] = {
            'current_page': page,
            'page_size': page_size,
            'total_partners': total_partners,
            'total_pages': total_pages,
        }
        return partner_dict

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
            {'font_size': 15, 'align': 'center', 'bold': True})
        head_highlight = workbook.add_format(
            {'font_size': 10, 'align': 'center', 'bold': True})
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
            account_keys = list(data['filters']['account'].keys())
            account_keys_str = ', '.join(account_keys)
            sheet.merge_range('C5:G5', account_keys_str, filter_body)
        if data['filters']['options']:
            option_keys = list(data['filters']['options'].keys())
            option_keys_str = ', '.join(option_keys)
            sheet.merge_range('C6:G6', option_keys_str, filter_body)
        if data:
            if report_action == 'dynamic_accounts_report.action_partner_ledger':
                sheet.write(8, col, ' ', sub_heading)
                sheet.write(8, col + 1, 'JNRL', sub_heading)
                sheet.write(8, col + 2, 'Account', sub_heading)
                sheet.merge_range('D9:E9', 'Ref', sub_heading)
                sheet.merge_range('F9:G9', 'Due Date', sub_heading)
                sheet.merge_range('H9:I9', 'Debit', sub_heading)
                sheet.merge_range('J9:K9', 'Credit', sub_heading)
                sheet.merge_range('L9:M9', 'Balance', sub_heading)
                row = 8
                for partner in data['partners'] or []:
                    row += 1
                    sheet.write(row, col, partner, txt_name)
                    sheet.write(row, col + 1, ' ', txt_name)
                    sheet.write(row, col + 2, ' ', txt_name)
                    sheet.merge_range(row, col + 3, row, col + 4, ' ',
                                      txt_name)
                    sheet.merge_range(row, col + 5, row, col + 6, ' ',
                                      txt_name)
                    sheet.merge_range(row, col + 7, row, col + 8,
                                      data['total'][partner]['total_debit'] or 0,
                                      txt_name)
                    sheet.merge_range(row, col + 9, row, col + 10,
                                      data['total'][partner]['total_credit'] or 0,
                                      txt_name)
                    sheet.merge_range(row, col + 11, row, col + 12,
                                      (data['total'][partner]['total_debit'] or 0)-
                                      (data['total'][partner]['total_credit'] or 0),
                                      txt_name)
                    if data['total'][partner]['initial_balance'] != 0:
                        row += 1
                        sheet.write(row, col, '', txt_name)
                        sheet.write(row, col + 1, ' ', txt_name)
                        sheet.write(row, col + 2, ' ', txt_name)
                        sheet.merge_range(row, col + 3, row, col + 4, 'Initial Balance ',
                                          head_highlight)
                        sheet.merge_range(row, col + 5, row, col + 6, ' ',
                                          txt_name)
                        sheet.merge_range(row, col + 7, row, col + 8,
                                          data['total'][partner]['initial_debit'],
                                          txt_name)
                        sheet.merge_range(row, col + 9, row, col + 10,
                                          data['total'][partner]['initial_credit'],
                                          txt_name)
                        sheet.merge_range(row, col + 11, row, col + 12,
                                          data['total'][partner]['initial_balance'],
                                          txt_name)
                    for rec in data['data'][partner]:
                        row += 1
                        sheet.write(row, col, rec[0]['date'], txt_name)
                        sheet.write(row, col + 1, rec[0]['jrnl'], txt_name)
                        sheet.write(row, col + 2, rec[0]['code'], txt_name)
                        sheet.merge_range(row, col + 3, row, col + 4,
                                          rec[0]['move_name'],
                                          txt_name)
                        sheet.merge_range(row, col + 5, row, col + 6,
                                          rec[0]['date_maturity'],
                                          txt_name)
                        sheet.merge_range(row, col + 7, row, col + 8,
                                          rec[0]['debit'], txt_name)
                        sheet.merge_range(row, col + 9, row, col + 10,
                                          rec[0]['credit'], txt_name)
                        sheet.merge_range(row, col + 11, row, col + 12, ' ',
                                          txt_name)
                row += 1
                grand_total = data.get('grand_total') or {}
                g_debit = float(grand_total.get('total_debit') or 0)
                g_credit = float(grand_total.get('total_credit') or 0)
                sheet.merge_range(row, col, row, col + 6, 'Total', filter_head)
                sheet.merge_range(row, col + 7, row, col + 8,
                                  # (data['grand_total']['total_debit'] or 0),
                                  g_debit, filter_head)
                sheet.merge_range(row, col + 9, row, col + 10,
                                  # data['grand_total']['total_credit'],
                                  g_credit, filter_head)
                sheet.merge_range(row, col + 11, row, col + 12,
                                  # (data['grand_total']['total_debit'] or 0) -
                                  # (data['grand_total']['total_credit'] or 0),
                                  # filter_head)
                                  g_debit - g_credit,filter_head)

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
