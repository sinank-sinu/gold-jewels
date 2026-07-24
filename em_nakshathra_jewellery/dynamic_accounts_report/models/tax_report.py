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
import calendar
import io
import json
from datetime import datetime
import xlsxwriter
from odoo import models, fields, api
from odoo.tools.date_utils import get_month, get_fiscal_year, \
    get_quarter_number, subtract


class TaxReport(models.TransientModel):
    """For creating Tax report."""
    _name = 'tax.report'
    _description = 'Tax Report'

    @api.model
    def view_report(self):
        """
        View a tax report for the current month. This function retrieves
        tax-related information for the current month. It calculates the net
        amount and tax amount for both sales and purchases based on the tax
        information associated with account move lines.
            :return: Dictionary containing sale and purchase data for the
                     current month.
        """
        sale = []
        purchase = []
        today = fields.Date.today()
        
        # 1. Get all taxes in the system
        tax_ids = self.env['account.tax'].search([])
        
        # 2. Pre-aggregate balances for the current month
        domain = [
            ('parent_state', '=', 'posted'),
            ('date', '>=', get_month(today)[0]),
            ('date', '<=', get_month(today)[1]),
            ('tax_ids', '!=', False)
        ]
        groups = self.env['account.move.line'].read_group(
            domain,
            ['tax_ids', 'debit:sum', 'credit:sum'],
            ['tax_ids'],
            lazy=False
        )
        balance_map = {}
        for g in groups:
            if g['tax_ids']:
                balance_map[g['tax_ids'][0]] = {
                    'debit': g['debit'] or 0.0,
                    'credit': g['credit'] or 0.0
                }
                
        # 3. Populate sale and purchase lists
        for tax in tax_ids:
            balances = balance_map.get(tax.id, {'debit': 0.0, 'credit': 0.0})
            debit = balances['debit']
            credit = balances['credit']
            net = round(debit + credit, 2)
            tax_amount = round(net * (tax.amount / 100), 2)
            if tax.type_tax_use == 'sale':
                sale.append({
                    'name': tax.name,
                    'amount': tax.amount,
                    'net': net,
                    'tax': tax_amount
                })
            elif tax.type_tax_use == 'purchase':
                purchase.append({
                    'name': tax.name,
                    'amount': tax.amount,
                    'net': net,
                    'tax': tax_amount
                })
        return {
            'sale': sale,
            'purchase': purchase
        }

    @api.model
    def get_filter_values(self, start_date, end_date, comparison_number,
                          comparison_type, options, report_type):
        """
           Get filtered tax values based on various criteria.

           :param start_date: Start date of the filter period.
           :param end_date: End date of the filter period.
           :param comparison_number: Number of comparison periods.
           :param comparison_type: Type of comparison (year, month, quarter).
           :param options: Filter options.
           :param report_type: Type of report (account, tax).
           :return: Dictionary containing dynamic_date_num, sale, and purchase
                    data.
           """
        sale = []
        purchase = []
        dynamic_date_num = {}
        if options == {}:
            options = None
        if options is None:
            option_domain = ['posted']
        elif 'draft' in options:
            option_domain = ['posted', 'draft']

        start_date_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

        start_date_first = \
            get_fiscal_year(start_date_dt)[0] if comparison_type == 'year' else start_date_dt
        end_date_first = \
            get_fiscal_year(end_date_dt)[1] if comparison_type == 'year' else end_date_dt

        def get_comparison_dates(i):
            if comparison_type == 'year':
                c_start = subtract(start_date_first, years=i)
                c_end = subtract(end_date_first, years=i)
            elif comparison_type == 'month':
                c_start = subtract(start_date_first, months=i)
                c_end = subtract(end_date_first, months=i)
            elif comparison_type == 'quarter':
                c_start = subtract(start_date_first, months=i * 3)
                c_end = subtract(end_date_first, months=i * 3)
            return c_start, c_end

        # Determine grouping fields
        groupby_account = False
        if report_type is not None:
            if 'account' in report_type:
                groupby = ['account_id', 'tax_ids']
                groupby_account = True
            elif 'tax' in report_type:
                groupby = ['tax_ids', 'account_id']
                groupby_account = True
            else:
                groupby = ['tax_ids']
        else:
            groupby = ['tax_ids']

        # 1. Main period aggregation
        domain = [
            ('parent_state', 'in', option_domain),
            ('date', '>=', start_date_first),
            ('date', '<=', end_date_first),
            ('tax_ids', '!=', False)
        ]
        groups_main = self.env['account.move.line'].read_group(
            domain,
            groupby + ['debit:sum', 'credit:sum'],
            groupby,
            lazy=False
        )

        # 2. Comparison periods aggregation
        com_balance_maps = {}
        if comparison_number:
            comp_num = int(comparison_number)
            # Set up dynamic date names
            if comparison_type == 'month':
                dynamic_date_num["dynamic_date_num0"] = self.get_month_name(start_date_first) + ' ' + str(start_date_first.year)
            elif comparison_type == 'quarter':
                dynamic_date_num["dynamic_date_num0"] = 'Q' + ' ' + str(get_quarter_number(start_date_first)) + ' ' + str(start_date_first.year)
            
            for i in range(1, comp_num + 1):
                com_start, com_end = get_comparison_dates(i)
                if comparison_type == 'month':
                    dynamic_date_num[f"dynamic_date_num{i}"] = self.get_month_name(com_start) + ' ' + str(com_start.year)
                elif comparison_type == 'quarter':
                    dynamic_date_num[f"dynamic_date_num{i}"] = 'Q' + ' ' + str(get_quarter_number(com_start)) + ' ' + str(com_start.year)
                    
                com_domain = [
                    ('parent_state', 'in', option_domain),
                    ('date', '>=', com_start),
                    ('date', '<=', com_end),
                    ('tax_ids', '!=', False)
                ]
                groups_com = self.env['account.move.line'].read_group(
                    com_domain,
                    groupby + ['debit:sum', 'credit:sum'],
                    groupby,
                    lazy=False
                )
                com_map = {}
                for g in groups_com:
                    if groupby_account:
                        if g['account_id'] and g['tax_ids']:
                            acc_id = g['account_id'][0]
                            tax_id = g['tax_ids'][0]
                            com_map[(acc_id, tax_id)] = (g['debit'] or 0.0) + (g['credit'] or 0.0)
                    else:
                        if g['tax_ids']:
                            tax_id = g['tax_ids'][0]
                            com_map[tax_id] = (g['debit'] or 0.0) + (g['credit'] or 0.0)
                com_balance_maps[i] = com_map

        # 3. Build response lists
        if groupby_account:
            # For account or tax grouped reports: iterate over active combinations in main period
            for g in groups_main:
                if not g['account_id'] or not g['tax_ids']:
                    continue
                acc_id, acc_name = g['account_id']
                tax_id, tax_name = g['tax_ids']
                key = (acc_id, tax_id)

                tax = self.env['account.tax'].browse(tax_id)
                tax_debit_sums = g['debit'] or 0.0
                tax_credit_sums = g['credit'] or 0.0
                net = round(tax_debit_sums + tax_credit_sums, 2)
                tax_amount = round(net * (tax.amount / 100), 2)

                dynamic_total_tax_sum = {}
                dynamic_total_net_sum = {}
                if comparison_number:
                    comp_num = int(comparison_number)
                    for i in range(1, comp_num + 1):
                        com_net = com_balance_maps[i].get(key, 0.0)
                        dynamic_total_net_sum[f"dynamic_total_net_sum{i}"] = round(com_net, 2)
                        dynamic_total_tax_sum[f"dynamic_total_tax_sum{i}"] = round(com_net * (tax.amount / 100), 2)

                entry = {
                    'name': tax_name,
                    'amount': tax.amount,
                    'net': net,
                    'tax': tax_amount,
                    'account': acc_name,
                }
                if comparison_number:
                    entry['dynamic net'] = dynamic_total_net_sum
                    entry['dynamic tax'] = dynamic_total_tax_sum

                if tax.type_tax_use == 'sale':
                    sale.append(entry)
                elif tax.type_tax_use == 'purchase':
                    purchase.append(entry)
        else:
            # For global tax report: display all taxes in the system
            balance_map_main = {g['tax_ids'][0]: (g['debit'] or 0.0) + (g['credit'] or 0.0) 
                                for g in groups_main if g['tax_ids']}
            all_taxes = self.env['account.tax'].search([])
            for tax in all_taxes:
                net = round(balance_map_main.get(tax.id, 0.0), 2)
                tax_amount = round(net * (tax.amount / 100), 2)

                dynamic_total_tax_sum = {}
                dynamic_total_net_sum = {}
                if comparison_number:
                    comp_num = int(comparison_number)
                    for i in range(1, comp_num + 1):
                        com_net = com_balance_maps[i].get(tax.id, 0.0)
                        dynamic_total_net_sum[f"dynamic_total_net_sum{i}"] = round(com_net, 2)
                        dynamic_total_tax_sum[f"dynamic_total_tax_sum{i}"] = round(com_net * (tax.amount / 100), 2)

                entry = {
                    'name': tax.name,
                    'amount': tax.amount,
                    'net': net,
                    'tax': tax_amount,
                }
                if comparison_number:
                    entry['dynamic net'] = dynamic_total_net_sum
                    entry['dynamic tax'] = dynamic_total_tax_sum

                if tax.type_tax_use == 'sale':
                    sale.append(entry)
                elif tax.type_tax_use == 'purchase':
                    purchase.append(entry)

        return {
            'dynamic_date_num': dynamic_date_num,
            'sale': sale,
            'purchase': purchase
        }

    @api.model
    def get_month_name(self, date):
        """
        Retrieve the abbreviated name of the month for a given date.

        :param date: The date for which to retrieve the month's abbreviated
                     name.
        :type date: datetime.date
        :return: Abbreviated name of the month (e.g., 'Jan', 'Feb', ..., 'Dec').
        :rtype: str
        """
        month_names = calendar.month_abbr
        return month_names[date.month]

    @api.model
    def get_xlsx_report(self, data, response, report_name, report_action):
        """
        Generate an XLSX report based on provided data and response stream.

        Generates an Excel workbook with specified report format, including
        subheadings,column headers, and row data for the given financial report
        data.

        :param str data: JSON-encoded data for the report.
        :param response: Response object to stream the generated report.
        :param str report_name: Name of the financial report.
        """
        data = json.loads(data)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet()
        sub_heading = workbook.add_format(
            {'align': 'center', 'bold': True, 'font_size': '10px',
             'border': 1,
             'border_color': 'black'})
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
        sheet.write('A3:b4', report_name, sub_heading)
        sheet.write(5, col, '', sub_heading)
        i = 1
        for date_view in data['date_viewed']:
            sheet.merge_range(5, col + i, 5, col + i + 1, date_view,
                              sub_heading)
            i += 2
        j = 1
        prev_account = None
        prev_tax = None
        sheet.write(6, col, '', sub_heading)
        for date in data['date_viewed']:
            sheet.write(6, col + j, 'NET', sub_heading)
            sheet.write(6, col + j + 1, 'TAX', sub_heading)
            j += 1
        sheet.write(7, col, 'Sales', sub_heading)
        sheet.write(7, col + 1, ' ', sub_heading)
        sheet.write(7, col + 2, data['sale_total'], sub_heading)
        row = 8
        for sale in data['data']['sale']:
            if data['report_type']:
                if list(data['report_type'].keys())[0] == 'account':
                    if prev_account != sale['account']:
                        prev_account = sale['account']
                        sheet.write(row, col, sale['account'], txt_name)
                        sheet.write(row, col + 1, '', txt_name)
                        sheet.write(row, col + 2, '', txt_name)
                elif list(data['report_type'].keys())[0] == 'tax':
                    if prev_tax != sale['name']:
                        prev_tax = sale['name']
                        sheet.write(row, col, sale['name'] + '(' + str(
                            sale['amount']) + '%)', txt_name)
                        sheet.write(row, col + 1, '', txt_name)
                        sheet.write(row, col + 2, '', txt_name)
                row += 1
                if data['apply_comparison']:
                    if sale['dynamic net']:
                        periods = data['comparison_number_range']
                        for num in periods:
                            if sale['dynamic net'][
                                'dynamic_total_net_sum' + str(num)]:
                                sheet.write(row, col + j, sale['dynamic net'][
                                    'dynamic_total_net_sum' + str(num)],
                                            txt_name)
                            if sale['dynamic tax'][
                                'dynamic_total_tax_sum' + str(num)]:
                                sheet.write(row, col, sale['dynamic tax'][
                                    'dynamic_total_tax_sum' + str(num)],
                                            txt_name)
                            j += 1
                j = 0
                sheet.write(row, col + j, sale['name'], txt_name)
                sheet.write(row, col + j + 1, sale['net'], txt_name)
                sheet.write(row, col + j + 2, sale['tax'], txt_name)
            else:
                j = 0
                sheet.write(row, col + j, sale['name'], txt_name)
                sheet.write(row, col + j + 1, sale['net'], txt_name)
                sheet.write(row, col + j + 2, sale['tax'], txt_name)
                row += 1
        row += 1
        sheet.write(row, col, 'Purchase', sub_heading)
        sheet.write(row, col + 1, ' ', sub_heading)
        sheet.write(row, col + 2, data['purchase_total'], sub_heading)
        row += 1
        for purchase in data['data']['purchase']:
            if data['report_type']:
                if list(data['report_type'].keys())[0] == 'account':
                    if prev_account != purchase['account']:
                        prev_account = purchase['account']
                        sheet.write(row, col, purchase['account'], txt_name)
                        sheet.write(row, col + 1, '', txt_name)
                        sheet.write(row, col + 2, '', txt_name)
                elif list(data['report_type'].keys())[0] == 'tax':
                    if prev_tax != purchase['name']:
                        prev_tax = purchase['name']
                        sheet.write(row, col, purchase['name'] + '(' + str(
                            purchase['amount']) + '%)', txt_name)
                        sheet.write(row, col + 1, '', txt_name)
                        sheet.write(row, col + 2, '', txt_name)
                row += 1
                if data['apply_comparison']:
                    if purchase['dynamic net']:
                        periods = data['comparison_number_range']
                        for num in periods:
                            if purchase['dynamic net'][
                                'dynamic_total_net_sum' + str(num)]:
                                sheet.write(row, col + j,
                                            purchase['dynamic net'][
                                                'dynamic_total_net_sum' + str(
                                                    num)],
                                            txt_name)
                            if purchase['dynamic tax'][
                                'dynamic_total_tax_sum' + str(num)]:
                                sheet.write(row, col, purchase['dynamic tax'][
                                    'dynamic_total_tax_sum' + str(num)],
                                            txt_name)
                            j += 1
                j = 0
                sheet.write(row, col + j, purchase['name'], txt_name)
                sheet.write(row, col + j + 1, purchase['net'], txt_name)
                sheet.write(row, col + j + 2, purchase['tax'], txt_name)
            else:
                j = 0
                sheet.write(row, col + j, purchase['name'], txt_name)
                sheet.write(row, col + j + 1, purchase['net'], txt_name)
                sheet.write(row, col + j + 2, purchase['tax'], txt_name)
                row += 1
        row += 1
        sheet.write(row, col, 'Purchase', sub_heading)
        sheet.write(row, col + 1, ' ', sub_heading)
        sheet.write(row, col + 2, data['purchase_total'], sub_heading)
        row += 1
        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
