from odoo import models

class OldGoldMarginXlsx(models.AbstractModel):
    _name = 'report.old_gold_xlsx_report.old_gold_margin_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, wizard):

        sheet = workbook.add_worksheet('Old Gold Margin')

        bold = workbook.add_format({'bold': True})
        num_format_3 = workbook.add_format({'num_format': '0.000', 'align': 'right'})
        num_format_3_bold = workbook.add_format({'num_format': '0.000','align': 'right','bold': True})
        date_format = workbook.add_format({'num_format': 'dd-mm-yyyy'})
        show_market_gain = self.env.user.has_group(
            'purchase.group_purchase_manager'
        )

        sheet.set_column(0, 0, 15)   # Date
        sheet.set_column(1, 1, 18)   # Voucher No
        sheet.set_column(2, 2, 20)   # Partner 
        sheet.set_column(3, 3, 18)   # Branch
        sheet.set_column(4, 4, 12)   # Type
        sheet.set_column(5, 5, 12)   # Purity
        sheet.set_column(6, 7, 14)   # Gross/Net Wt
        sheet.set_column(8, 8, 18)   # Amount
        sheet.set_column(9, 10, 16)  # Purchase/Board Rate
        sheet.set_column(11, 12, 20) # 2% Less + Gain/Loss
        sheet.set_column(13, 13, 16) # Expected Fine
        sheet.set_column(14, 14, 18) # Purchase Fine Rate
        sheet.set_column(15, 15, 16) # Market Rate

        if show_market_gain:
            sheet.set_column(16, 16, 22) # Gain/Loss Market

        #Headers
        headers = [
            'Date', 'Voucher No', 'Partner', 'Branch', 'Type', 'Purity',
            'Gross Wt', 'Net Wt', 'Amount',
            'Purchase Rate', 'Board Rate',
            '2% Less Of Board Rate', 'Gain/ Loss (2%Less Board)',
            'Expected Fine', 'Purchase Fine Rate',
            'Market Fine Rate'
        ]

        if show_market_gain:
            headers.append('Gain/ Loss (Market Rate)')

        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)

        row = 1

        #Fetch purchase order lines
        domain = [
            ('order_id.date_order', '>=', wizard.date_from),
            ('order_id.date_order', '<=', wizard.date_to),
            '|',
            ('order_id.is_old_gold', '=', True),
            ('order_id.sale_id.has_old_gold', '=', True),
        ]
        if wizard.branch_ids:
            domain.append(('order_id.branch_id', 'in', wizard.branch_ids.ids))

        records = self.env['purchase.order.line'].search(domain)
        # records = self.env['purchase.order.line'].search([
        #     ('order_id.date_order', '>=', wizard.date_from),
        #     ('order_id.date_order', '<=', wizard.date_to),
        #     '|',
        #     ('order_id.is_old_gold', '=', True),                         
        #     ('order_id.sale_id.has_old_gold', '=', True),                
        # ])
        total_gross_wt = 0.0
        total_net_wt = 0.0
        total_amount = 0.0
        total_expected_fine = 0.0
        total_gain_loss_market = 0.0
        total_weight_for_purity = 0.0
        total_weighted_purity = 0.0

        for rec in records:
            #Date (fix datetime → date)
            date_value = rec.order_id.date_order
            if date_value:
                date_value = date_value.date()

            #Basic fields
            voucher = rec.order_id.name
            branch = rec.order_id.branch_id.name if rec.order_id.branch_id else ''
            purity = rec.purity_id.percentage if rec.purity_id else 0
            gross_wt = rec.product_qty or 0
            net_wt = rec.product_qty or 0
            amount = rec.price_subtotal or 0
            purchase_rate = rec.price_unit or 0

            #Board rate based on purchase date
            gold_rate = self.env['gold.rate.master'].search([
                ('date', '<=', date_value)
            ], order='date desc', limit=1)
            board_rate = gold_rate.rate_per_gram if gold_rate else 0

            # Fetch Fine Rate from fine.rate.master matching the report date
            fine_rate_rec = self.env['fine.rate.master'].search([
                ('date', '<=', date_value)
            ], order='date desc', limit=1)

            market_fine_rate = 0.0

            if fine_rate_rec:
                history_line = self.env['fine.rate.history'].search([
                    ('master_id', '=', fine_rate_rec.id)
                ], order='id desc', limit=1)
                if history_line:
                    market_fine_rate = history_line.fine_rate
                else:
                    # Fallback to the main form view rate field if no history item exists
                    market_fine_rate = fine_rate_rec.fine_rate or 0.0

            # Calculations
            less_2_board = board_rate * 0.98
            gain_loss_board = purchase_rate - less_2_board
            expected_fine = net_wt * (purity / 100)
            purchase_fine_rate = (amount / expected_fine) if expected_fine else 0.0
            gain_loss_market = market_fine_rate - purchase_fine_rate

            if rec.order_id.sale_id and rec.order_id.sale_id.has_old_gold:
                purchase_type = 'Exchange'
            elif rec.order_id.is_old_gold:
                purchase_type = 'CP'
            else:
                continue 
            # totals
            total_gross_wt += gross_wt
            total_purity_percetage =+ purity
            total_net_wt += net_wt
            total_amount += amount
            total_expected_fine += expected_fine
            total_gain_loss_market += gain_loss_market
            total_weight_for_purity += net_wt
            total_weighted_purity += (purity * net_wt)

            #Write values
            sheet.write(row, 0, date_value, date_format)
            sheet.write(row, 1, voucher)
            partner_name = rec.order_id.partner_id.name if rec.order_id.partner_id else ''
            sheet.write(row, 2, partner_name)
            sheet.write(row, 3, branch)
            sheet.write(row, 4, purchase_type)
            sheet.write(row, 5, f"{purity}%")
            sheet.write(row, 6, gross_wt, num_format_3)
            sheet.write(row, 7, net_wt, num_format_3)
            sheet.write(row, 8, amount, num_format_3)
            sheet.write(row, 9, purchase_rate, num_format_3)
            sheet.write(row, 10, board_rate, num_format_3)
            sheet.write(row, 11, less_2_board, num_format_3)
            sheet.write(row, 12, gain_loss_board, num_format_3)
            sheet.write(row, 13, expected_fine, num_format_3)
            sheet.write(row, 14, purchase_fine_rate, num_format_3)
            sheet.write(row, 15, market_fine_rate, num_format_3)
            if show_market_gain:
                sheet.write(row, 16, gain_loss_market, num_format_3)

            row += 1
        avg_purity = (
            total_weighted_purity / total_weight_for_purity
            if total_weight_for_purity else 0
        )
        #Total row
        sheet.write(row, 2, "Total", bold)
        sheet.write(row, 5, f"{avg_purity:.2f}%", bold)
        sheet.write(row, 6, total_gross_wt, num_format_3_bold)
        sheet.write(row, 7, total_net_wt, num_format_3_bold)
        sheet.write(row, 8, total_amount, num_format_3_bold)
        sheet.write(row, 13, total_expected_fine, num_format_3_bold)
        if show_market_gain:
            sheet.write(row, 16, total_gain_loss_market, num_format_3_bold)