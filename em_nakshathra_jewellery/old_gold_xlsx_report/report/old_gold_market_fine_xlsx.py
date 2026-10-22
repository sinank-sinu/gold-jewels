# -*- coding: utf-8 -*-
from datetime import timedelta, date
from odoo import models


class OldGoldMarketFineXlsx(models.AbstractModel):
    _name = 'report.old_gold_xlsx_report.old_gold_market_fine_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, wizard):
        # -------------------------------------------------------------
        # STYLES & FORMATS
        # -------------------------------------------------------------
        title_format = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'left'
        })
        sub_title = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_color': '#555555'
        })
        header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#D9E1F2',
            'border': 1,
            'text_wrap': True
        })
        date_format = workbook.add_format({
            'num_format': 'dd-mm-yyyy', 'align': 'center', 'border': 1
        })
        text_center = workbook.add_format({
            'align': 'center', 'border': 1
        })
        text_left = workbook.add_format({
            'align': 'left', 'border': 1
        })
        num_format_3 = workbook.add_format({
            'num_format': '0.000', 'align': 'right', 'border': 1
        })
        num_format_2 = workbook.add_format({
            'num_format': '0.00', 'align': 'right', 'border': 1
        })
        bold_num_3 = workbook.add_format({
            'bold': True, 'num_format': '0.000', 'align': 'right', 'border': 1, 'bg_color': '#F2F2F2'
        })
        bold_num_2 = workbook.add_format({
            'bold': True, 'num_format': '0.00', 'align': 'right', 'border': 1, 'bg_color': '#F2F2F2'
        })
        bold_center = workbook.add_format({
            'bold': True, 'align': 'center', 'border': 1, 'bg_color': '#F2F2F2'
        })

        # Cache fine rates by date to minimize database searches
        fine_rate_cache = {}

        def get_next_day_rate(dt):
            if not dt:
                return 0.0
            next_day = dt + timedelta(days=1)
            if next_day in fine_rate_cache:
                return fine_rate_cache[next_day]

            fine_rate_rec = self.env['fine.rate.master'].search([
                ('date', '=', next_day)
            ], order='date desc', limit=1)

            if not fine_rate_rec:
                fine_rate_rec = self.env['fine.rate.master'].search([
                    ('date', '<=', next_day)
                ], order='date desc', limit=1)

            rate = 0.0
            if fine_rate_rec:
                history_line = self.env['fine.rate.history'].search([
                    ('master_id', '=', fine_rate_rec.id)
                ], order='id desc', limit=1)
                if history_line and history_line.fine_rate:
                    rate = history_line.fine_rate
                else:
                    rate = fine_rate_rec.fine_rate or 0.0

            fine_rate_cache[next_day] = rate
            return rate

        # Pre-cache batches for fast mapping
        all_batches = self.env['old.gold.batch'].search([])
        batch_by_date_branch_purity = {}
        for b in all_batches:
            key = (b.batch_date, b.branch_id.id, b.purity_id.id)
            batch_by_date_branch_purity.setdefault(key, []).append(b)

        # Pre-cache old.gold.purchase by purchase_order_id and sale_id
        og_purchases = self.env['old.gold.purchase'].search([
            '|', ('purchase_order_id', '!=', False), ('sale_id', '!=', False)
        ])
        ogp_by_po = {}
        ogp_by_sale = {}
        for ogp in og_purchases:
            if ogp.purchase_order_id:
                ogp_by_po.setdefault(ogp.purchase_order_id.id, []).append(ogp)
            if ogp.sale_id:
                ogp_by_sale.setdefault(ogp.sale_id.id, []).append(ogp)

        def get_batches_for_po_line(rec):
            po = rec.order_id
            matching_batches = set()

            ogps = list(ogp_by_po.get(po.id, []))
            if po.sale_id:
                ogps.extend(ogp_by_sale.get(po.sale_id.id, []))

            purity_id = rec.purity_id.id if rec.purity_id else False
            branch_id = po.branch_id.id if po.branch_id else False

            for ogp in ogps:
                for line in ogp.old_gold_line_ids:
                    line_purity_id = (line.verified_purity_id or line.purity_id).id if (line.verified_purity_id or line.purity_id) else purity_id
                    line_branch_id = (line.branch_id or ogp.branch_id).id if (line.branch_id or ogp.branch_id) else branch_id

                    if not purity_id or not line_purity_id or line_purity_id == purity_id:
                        if line.batch_id:
                            matching_batches.add(line.batch_id)
                        else:
                            found = batch_by_date_branch_purity.get((ogp.date, line_branch_id, line_purity_id), [])
                            for fb in found:
                                matching_batches.add(fb)

            # Fallback matching by (po_date, branch, purity)
            if not matching_batches and purity_id and branch_id and po.date_order:
                found = batch_by_date_branch_purity.get((po.date_order.date(), branch_id, purity_id), [])
                for fb in found:
                    matching_batches.add(fb)

            return matching_batches

        # Cache Market Fine per batch
        batch_market_fine_cache = {}

        def get_market_fine_for_batch(batch):
            if batch.id in batch_market_fine_cache:
                return batch_market_fine_cache[batch.id]

            lines = batch.line_ids
            if not lines:
                ogps = self.env['old.gold.purchase'].search([
                    ('date', '=', batch.batch_date),
                    ('branch_id', '=', batch.branch_id.id)
                ])
                lines = ogps.mapped('old_gold_line_ids').filtered(
                    lambda l: (l.verified_purity_id or l.purity_id) == batch.purity_id
                )

            batch_po_lines = set()
            for l in lines:
                po = l.old_gold_purchase_id.purchase_order_id
                if not po and l.old_gold_purchase_id.sale_id:
                    po = self.env['purchase.order'].search([
                        ('sale_id', '=', l.old_gold_purchase_id.sale_id.id)
                    ], limit=1)
                if po:
                    pols = po.order_line.filtered(
                        lambda pl: pl.purity_id == batch.purity_id or pl.is_old_gold
                    )
                    for pol in pols:
                        batch_po_lines.add(pol)

            total_mf = 0.0
            for pol in batch_po_lines:
                po_date = pol.order_id.date_order.date() if pol.order_id.date_order else batch.batch_date
                rate = get_next_day_rate(po_date)
                amt = pol.price_subtotal or 0.0
                if amt > 0 and rate > 0:
                    total_mf += (amt / rate)

            # Fallback if no individual PO lines found
            if not total_mf and batch.total_purchase_amount > 0:
                rate = get_next_day_rate(batch.batch_date)
                if rate > 0:
                    total_mf = batch.total_purchase_amount / rate

            batch_market_fine_cache[batch.id] = total_mf
            return total_mf

        # =============================================================
        # SHEET 1: REFINERY SUMMARY (GAIN / LOSS COMPARISON)
        # =============================================================
        sheet1 = workbook.add_worksheet('Refinery Summary')

        sheet1.write(0, 0, "Old Gold Refinery Summary (Received Fine vs Market Fine)", title_format)
        sheet1.write(1, 0, f"Period: {wizard.date_from.strftime('%d-%m-%Y')} to {wizard.date_to.strftime('%d-%m-%Y')}", sub_title)

        summary_headers = [
            'Issue Date',
            'Issue Voucher',
            'Batch No(s)',
            'Branch',
            'Issued Wt (g)',
            'Melting Loss (g)',
            'Output Wt (g)',
            'Purchase Amount (₹)',
            'Market Fine (g)',
            'Received Fine (g)',
            'Gain / Loss (g)'
        ]

        sheet1.set_column(0, 0, 14)   # Issue Date
        sheet1.set_column(1, 1, 16)   # Issue Voucher
        sheet1.set_column(2, 2, 24)   # Batch No(s)
        sheet1.set_column(3, 3, 16)   # Branch
        sheet1.set_column(4, 4, 15)   # Issued Wt
        sheet1.set_column(5, 5, 15)   # Melting Loss
        sheet1.set_column(6, 6, 15)   # Output Wt
        sheet1.set_column(7, 7, 18)   # Purchase Amount
        sheet1.set_column(8, 8, 16)   # Market Fine (g)
        sheet1.set_column(9, 9, 16)   # Received Fine (g)
        sheet1.set_column(10, 10, 16) # Gain / Loss (g)

        header_row1 = 3
        sheet1.set_row(header_row1, 28)
        for col, h in enumerate(summary_headers):
            sheet1.write(header_row1, col, h, header_format)

        issue_domain = [
            ('issue_date', '>=', wizard.date_from),
            ('issue_date', '<=', wizard.date_to),
        ]
        if wizard.branch_ids:
            issue_domain.append(('branch_id', 'in', wizard.branch_ids.ids))

        issues = self.env['old.gold.refinery.issue'].search(issue_domain, order='issue_date asc, id asc')

        row1 = header_row1 + 1

        tot_s1_issued_wt = 0.0
        tot_s1_loss = 0.0
        tot_s1_output_wt = 0.0
        tot_s1_amount = 0.0
        tot_s1_market_fine = 0.0
        tot_s1_rcd_fine = 0.0
        tot_s1_gain_fine = 0.0

        for issue in issues:
            issue_date = issue.issue_date
            voucher_no = issue.name or ''
            branch_name = issue.branch_id.name if issue.branch_id else ''
            batch_names = ", ".join(issue.batch_ids.mapped('name')) if issue.batch_ids else '-'

            issued_wt = issue.total_issued_weight or 0.0
            melting_loss = issue.melting_loss or 0.0
            output_wt = issue.output_weight or 0.0
            amount = issue.total_purchase_amount or 0.0

            # Market Fine: Total market fine of all POs belonging to the batch(es) of this issue
            if issue.batch_ids:
                market_fine = sum(get_market_fine_for_batch(b) for b in issue.batch_ids)
                if not market_fine and amount > 0:
                    rate = get_next_day_rate(issue_date)
                    market_fine = (amount / rate) if rate else 0.0
            else:
                next_day_rate = get_next_day_rate(issue_date)
                market_fine = (amount / next_day_rate) if next_day_rate else 0.0

            # Find matching Bullion Receipt Voucher(s)
            receipts = self.env['old.gold.bullion.receipt'].search([
                ('issue_id', '=', issue.id)
            ])

            if receipts:
                rcd_fine = sum(
                    r.receive_weight * (r.purity_id.percentage / 100.0) if r.purity_id and r.purity_id.percentage
                    else r.receive_weight for r in receipts
                )
            else:
                # Fallback to Lab Purity calculation if receipt voucher not yet created
                lab_purity = issue.lab_purity_percent or issue.expected_purity or 0.0
                rcd_fine = output_wt * (lab_purity / 100.0)

            # Gain / Loss (in grams) = Received Fine - Market Fine
            gain_loss_fine = rcd_fine - market_fine

            # Accumulate totals
            tot_s1_issued_wt += issued_wt
            tot_s1_loss += melting_loss
            tot_s1_output_wt += output_wt
            tot_s1_amount += amount
            tot_s1_market_fine += market_fine
            tot_s1_rcd_fine += rcd_fine
            tot_s1_gain_fine += gain_loss_fine

            # Write row
            sheet1.write(row1, 0, issue_date, date_format)
            sheet1.write(row1, 1, voucher_no, text_center)
            sheet1.write(row1, 2, batch_names, text_left)
            sheet1.write(row1, 3, branch_name, text_left)
            sheet1.write(row1, 4, issued_wt, num_format_3)
            sheet1.write(row1, 5, melting_loss, num_format_3)
            sheet1.write(row1, 6, output_wt, num_format_3)
            sheet1.write(row1, 7, amount, num_format_2)
            sheet1.write(row1, 8, market_fine, num_format_3)
            sheet1.write(row1, 9, rcd_fine, num_format_3)
            sheet1.write(row1, 10, gain_loss_fine, num_format_3)

            row1 += 1

        # Summary total row
        sheet1.set_row(row1, 24)
        sheet1.write(row1, 0, "", bold_center)
        sheet1.write(row1, 1, "Total", bold_center)
        sheet1.write(row1, 2, "", bold_center)
        sheet1.write(row1, 3, "", bold_center)
        sheet1.write(row1, 4, tot_s1_issued_wt, bold_num_3)
        sheet1.write(row1, 5, tot_s1_loss, bold_num_3)
        sheet1.write(row1, 6, tot_s1_output_wt, bold_num_3)
        sheet1.write(row1, 7, tot_s1_amount, bold_num_2)
        sheet1.write(row1, 8, tot_s1_market_fine, bold_num_3)
        sheet1.write(row1, 9, tot_s1_rcd_fine, bold_num_3)
        sheet1.write(row1, 10, tot_s1_gain_fine, bold_num_3)

        # =============================================================
        # SHEET 2: PURCHASE DETAILS (PO LEVEL)
        # =============================================================
        sheet2 = workbook.add_worksheet('Purchase Details')

        sheet2.write(0, 0, "Old Gold Purchase Details (PO Level)", title_format)
        sheet2.write(1, 0, f"Period: {wizard.date_from.strftime('%d-%m-%Y')} to {wizard.date_to.strftime('%d-%m-%Y')}", sub_title)

        detail_headers = [
            'Date',
            'PO Number',
            'Batch No',
            'Branch',
            'Purity',
            'Gross Wt (g)',
            'Net Wt (g)',
            'Expected Fine (g)',
            'Amount (₹)',
            'Next Day Rate (₹/g)',
            'Market Fine (g)'
        ]

        sheet2.set_column(0, 0, 14)  # Date
        sheet2.set_column(1, 1, 18)  # PO Number
        sheet2.set_column(2, 2, 24)  # Batch No
        sheet2.set_column(3, 3, 16)  # Branch
        sheet2.set_column(4, 4, 12)  # Purity
        sheet2.set_column(5, 5, 14)  # Gross Wt
        sheet2.set_column(6, 6, 14)  # Net Wt
        sheet2.set_column(7, 7, 16)  # Expected Fine
        sheet2.set_column(8, 8, 16)  # Amount
        sheet2.set_column(9, 9, 18)  # Next Day Rate
        sheet2.set_column(10, 10, 16)# Market Fine

        header_row2 = 3
        sheet2.set_row(header_row2, 28)
        for col, h in enumerate(detail_headers):
            sheet2.write(header_row2, col, h, header_format)

        po_domain = [
            ('order_id.date_order', '>=', wizard.date_from),
            ('order_id.date_order', '<=', wizard.date_to),
            ('order_id.state', 'not in', ('draft', 'cancel')),
            ('order_id.is_sale_return_po', '=', False),
            ('order_id.is_sale_return_shop', '=', False),
            ('order_id.is_purchase_expense', '=', False),
            '|',
            ('order_id.is_old_gold', '=', True),
            ('order_id.sale_id.has_old_gold', '=', True),
        ]
        if wizard.branch_ids:
            po_domain.append(('order_id.branch_id', 'in', wizard.branch_ids.ids))

        po_lines = self.env['purchase.order.line'].search(po_domain)
        min_date = date.min
        po_lines = po_lines.sorted(
            key=lambda r: (
                r.order_id.date_order.date() if r.order_id.date_order else min_date,
                r.order_id.name or '',
                r.id
            )
        )

        row2 = header_row2 + 1

        tot_s2_gross = 0.0
        tot_s2_net = 0.0
        tot_s2_exp_fine = 0.0
        tot_s2_amount = 0.0
        tot_s2_market_fine = 0.0
        tot_s2_weighted_purity = 0.0

        for rec in po_lines:
            if not rec.purity_id and not rec.is_old_gold:
                continue

            # Skip lines with invalid or negative amounts to prevent distorted totals
            if rec.price_subtotal <= 0:
                continue

            order_date = rec.order_id.date_order.date() if rec.order_id.date_order else False
            po_num = rec.order_id.name or ''
            branch = rec.order_id.branch_id.name if rec.order_id.branch_id else ''

            purity = rec.purity_id.percentage if rec.purity_id else 0.0
            purity_str = f"{purity:.2f}%" if purity else (rec.purity_id.name or '-')

            gross_wt = rec.gross_weight or rec.product_qty or 0.0
            net_wt = rec.net_weight or rec.product_qty or 0.0
            expected_fine = rec.fine_weight or (net_wt * (purity / 100.0) if purity else 0.0)
            amount = rec.price_subtotal or 0.0

            # Find batch number(s) linked to this PO line
            batches = get_batches_for_po_line(rec)
            if not batches:
                # Skip unbatched purchase orders as requested
                continue

            batch_name = ", ".join(sorted(set(b.name for b in batches if b.name))) if batches else '-'

            next_day_rate = get_next_day_rate(order_date)
            market_fine = (amount / next_day_rate) if next_day_rate else 0.0

            # Accumulate totals
            tot_s2_gross += gross_wt
            tot_s2_net += net_wt
            tot_s2_exp_fine += expected_fine
            tot_s2_amount += amount
            tot_s2_market_fine += market_fine
            tot_s2_weighted_purity += (purity * net_wt)

            # Write row
            sheet2.write(row2, 0, order_date, date_format)
            sheet2.write(row2, 1, po_num, text_center)
            sheet2.write(row2, 2, batch_name, text_left)
            sheet2.write(row2, 3, branch, text_left)
            sheet2.write(row2, 4, purity_str, text_center)
            sheet2.write(row2, 5, gross_wt, num_format_3)
            sheet2.write(row2, 6, net_wt, num_format_3)
            sheet2.write(row2, 7, expected_fine, num_format_3)
            sheet2.write(row2, 8, amount, num_format_2)
            sheet2.write(row2, 9, next_day_rate, num_format_2)
            sheet2.write(row2, 10, market_fine, num_format_3)

            row2 += 1

        avg_purity2 = (tot_s2_weighted_purity / tot_s2_net) if tot_s2_net else 0.0

        # Detail total row
        sheet2.set_row(row2, 24)
        sheet2.write(row2, 0, "", bold_center)
        sheet2.write(row2, 1, "Total", bold_center)
        sheet2.write(row2, 2, "", bold_center)
        sheet2.write(row2, 3, "", bold_center)
        sheet2.write(row2, 4, f"{avg_purity2:.2f}%" if avg_purity2 else "", bold_center)
        sheet2.write(row2, 5, tot_s2_gross, bold_num_3)
        sheet2.write(row2, 6, tot_s2_net, bold_num_3)
        sheet2.write(row2, 7, tot_s2_exp_fine, bold_num_3)
        sheet2.write(row2, 8, tot_s2_amount, bold_num_2)
        sheet2.write(row2, 9, "", bold_center)
        sheet2.write(row2, 10, tot_s2_market_fine, bold_num_3)
