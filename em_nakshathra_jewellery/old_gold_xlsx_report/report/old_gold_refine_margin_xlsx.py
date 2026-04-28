from odoo import models
from datetime import timedelta, datetime, time

class OldGoldMarginXlsx(models.AbstractModel):
    _name = 'report.old_gold_xlsx_report.og_refine_margin_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, wizard):

        sheet = workbook.add_worksheet('Old Gold Refine Margin')

        bold = workbook.add_format({'bold': True})
        num_format_3 = workbook.add_format({'num_format': '0.000', 'align': 'right'})
        num_format_3_bold = workbook.add_format({'num_format': '0.000','align': 'right','bold': True})
        date_format = workbook.add_format({'num_format': 'dd-mm-yyyy'})
        show_gain_loss = self.env.user.has_group(
            'purchase.group_purchase_manager'
        )
        sheet.write(0, 0, "Date From:", bold)
        sheet.write(0, 1, wizard.date_from, date_format)

        sheet.write(0, 3, "Date To:", bold)
        sheet.write(0, 4, wizard.date_to, date_format)


        sheet.set_column(0, 0, 16)   # Date of Purchase
        sheet.set_column(1, 1, 13)   # Batch No
        sheet.set_column(2, 2, 14)   # Branch
        sheet.set_column(3, 3, 12)   # Purity
        sheet.set_column(4, 4, 13)   # Gross Wt.
        sheet.set_column(5, 5, 13)   # Net Wt.
        sheet.set_column(6, 6, 13)   # Amount
        sheet.set_column(7, 7, 15)   # Expected Fine
        sheet.set_column(8, 8, 14) # Melting Date
        sheet.set_column(9, 9, 13) # Melting Loss
        sheet.set_column(10, 10, 13) # Scrap Bar Qty
        sheet.set_column(11, 11, 13) # Lab Purity
        sheet.set_column(12, 12, 14) # Fine As Per Lab
        sheet.set_column(13, 13, 14) # Fine Rcd
        sheet.set_column(14, 14, 14) # Balance
        sheet.set_column(15, 15, 18) # Fine Rate Next Day 1 PM
        sheet.set_column(16, 16, 18) # Fine As Per 1 PM Rate
        if show_gain_loss:
            sheet.set_column(17, 17, 18) # Total Gain / Loss

    
        #Headers
        headers = [
            'Date of Purchase', 'Batch No', 'Branch', 'Purity', 'Gross Wt.', 'Net Wt.',
            'Amount', 'Expected Fine', 'Melting Date',
            'Melting Loss', 'Scrap Bar Qty',
            'Lab Purity', 'Fine As Per Lab',
            'Fine Rcd', 'Balance',
            'Fine Rate Next Day 1 PM', 'Fine As Per 1 PM Rate'
        ]

        if show_gain_loss:
            headers.append('Total Gain / Loss')
        header_row = 3
        for col, header in enumerate(headers):
            sheet.write(header_row, col, header, bold)

        row = header_row + 1

        #Fetch purchase order lines
        domain = [
            ('issue_id.issue_date', '>=', wizard.date_from),
            ('issue_id.issue_date', '<=', wizard.date_to),
        ]
        if wizard.branch_ids:
            domain.append(('issue_id.branch_id', 'in', wizard.branch_ids.ids))

        records = self.env['old.gold.refinery.issue.line'].search(domain)
        # records = self.env['old.gold.refinery.issue.line'].search([
        #     ('issue_id.issue_date', '>=', wizard.date_from),
        #     ('issue_id.issue_date', '<=', wizard.date_to),
        # ])

        total_gross_wt = 0.0
        total_net_wt = 0.0
        total_amount = 0.0
        total_expected_fine = 0.0
        total_melting_loss = 0.0
        total_scrap_bar_qty = 0.0
        total_fine_as_per_lab = 0.0
        total_fine_rcd = 0.0
        total_balance = 0.0
        total_fine_as_per_1_PM_rate = 0.0
        total_weight_for_purity = 0.0
        total_weighted_purity = 0.0
        total_gain_loss = 0.0

        for rec in records:
            #Calculations

            #Basic fields
            batch = rec.issue_id.name
            branch = rec.issue_id.branch_id.name if rec.issue_id.branch_id else ''
            purity = rec.purity_id.percentage if rec.purity_id else 0
            gross_wt = rec.issue_weight or 0
            net_wt = rec.issue_weight or 0
            amount = rec.issue_id.total_purchase_amount or 0
            expected_fine = net_wt * (purity / 100)
            melting_date = rec.issue_id.mo_id.date_start
            if melting_date:
                melting_date = melting_date.date()
            else: 
                melting_date = False
            melting_loss = rec.issue_id.melting_loss
            scrap_bar_qty = net_wt - melting_loss
            lab_purity = rec.issue_id.lab_purity_percent
            fine_as_per_lab = scrap_bar_qty * (lab_purity / 100)
            fine_rcd = scrap_bar_qty * 0.90
            balance = fine_as_per_lab - fine_rcd
            #Fine rate as the Board rate from Gold rate update log model 
            fine_rate_next_day_1_PM = 0.0
            issue_date = rec.issue_id.issue_date  # this is already a DATE

            if issue_date:
                next_day = issue_date + timedelta(days=1)

                start_dt = datetime.combine(next_day, time.min)  # 00:00:00
                end_dt   = datetime.combine(next_day, time.max)  # 23:59:59

                rate_rec = self.env['gold.rate.update.log'].search([
                    ('rate_datetime', '>=', start_dt),
                    ('rate_datetime', '<=', end_dt),
                ], order='rate_datetime desc', limit=1)

                if rate_rec:
                    fine_rate_next_day_1_PM = rate_rec.board_rate or 0.0
            fine_as_per_1_PM_rate =  (amount / fine_rate_next_day_1_PM if fine_rate_next_day_1_PM else 0)
            gain_loss = fine_as_per_1_PM_rate - fine_rcd
            
            # totals
            total_gross_wt += gross_wt
            total_net_wt += net_wt
            total_amount += amount
            total_expected_fine += expected_fine
            total_melting_loss += melting_loss
            total_scrap_bar_qty += scrap_bar_qty
            total_fine_as_per_lab += fine_as_per_lab
            total_fine_rcd += fine_rcd
            total_balance += balance
            total_fine_as_per_1_PM_rate += fine_as_per_1_PM_rate
            total_weight_for_purity += net_wt
            total_weighted_purity += (purity * net_wt)
            total_gain_loss += gain_loss

            #Write values
            sheet.write(row, 0, issue_date, date_format)
            sheet.write(row, 1, batch)
            # partner_name = rec.order_id.partner_id.name if rec.order_id.partner_id else ''
            # sheet.write(row, 2, partner_name)
            sheet.write(row, 2, branch)
            sheet.write(row, 3, f"{purity}%")
            sheet.write(row, 4, gross_wt, num_format_3)
            sheet.write(row, 5, net_wt, num_format_3)
            sheet.write(row, 6, amount, num_format_3)
            sheet.write(row, 7, expected_fine, num_format_3)
            if melting_date:
                sheet.write(row, 8, melting_date, date_format)
            else:
                sheet.write(row, 8, "")
            # sheet.write(row, 8, melting_date, date_format)
            sheet.write(row, 9, melting_loss, num_format_3)
            sheet.write(row, 10, scrap_bar_qty, num_format_3)
            sheet.write(row, 11, f"{lab_purity}%")
            sheet.write(row, 12, fine_as_per_lab, num_format_3)
            sheet.write(row, 13, fine_rcd, num_format_3)
            sheet.write(row, 14, balance, num_format_3)
            sheet.write(row, 15, fine_rate_next_day_1_PM, num_format_3)
            sheet.write(row, 16, fine_as_per_1_PM_rate, num_format_3)
            if show_gain_loss:
                sheet.write(row, 17, gain_loss, num_format_3)
            
            
            
            row += 1
        avg_purity = (
            total_weighted_purity / total_weight_for_purity
            if total_weight_for_purity else 0
        )
        #Total row
        sheet.write(row, 1, "Total", bold)
        sheet.write(row, 3, f"{avg_purity:.2f}%", bold)
        sheet.write(row, 4, total_gross_wt, num_format_3_bold)
        sheet.write(row, 5, total_net_wt, num_format_3_bold)
        sheet.write(row, 6, total_amount, num_format_3_bold)
        sheet.write(row, 7, total_expected_fine, num_format_3_bold)
        sheet.write(row, 9, total_melting_loss, num_format_3_bold)
        sheet.write(row, 10, total_scrap_bar_qty, num_format_3_bold)
        sheet.write(row, 12, total_fine_as_per_lab, num_format_3_bold)
        sheet.write(row, 13, total_fine_rcd, num_format_3_bold)
        sheet.write(row, 14, total_balance, num_format_3_bold)
        sheet.write(row, 16, total_fine_as_per_1_PM_rate, num_format_3_bold)
        if show_gain_loss:
            sheet.write(row, 17, total_gain_loss, num_format_3_bold)