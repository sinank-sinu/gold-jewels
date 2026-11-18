# -*- coding: utf-8 -*-
import io
import xlsxwriter

from odoo import http
from odoo.http import request


class StockInflowOutflowController(http.Controller):

    @http.route('/stock_inflow_outflow/export_xlsx', type='http', auth='user')
    def export_xlsx(
        self,
        branch_id='all',
        date_from=None,
        date_to=None,
        mode='movement',
        include_no_vendor='1',
        only_period_activity='0',
        active_filter='all',
        **kwargs
    ):
        report = request.env['stock.inflow.outflow.report']
        inc_no_vendor = str(include_no_vendor).lower() in ('1', 'true', 'yes')
        only_act = str(only_period_activity).lower() in ('1', 'true', 'yes')

        flow_data = report.get_inflow_outflow_summary(
            branch_id=branch_id,
            date_from=date_from,
            date_to=date_to,
            only_with_movement=False,
            product_limit=5000,
            product_offset=0,
        )
        ledger_data = report.get_inflow_outflow_ledger(
            branch_id=branch_id,
            date_from=date_from,
            date_to=date_to,
            limit=25000,
            offset=0,
        )
        vendor_data = report.get_vendor_labels_summary(
            branch_id=branch_id,
            date_from=date_from,
            date_to=date_to,
            mode=mode,
            include_no_vendor=inc_no_vendor,
            only_period_activity=only_act,
            active_filter=active_filter,
        )
        label_data = report.get_vendor_label_lines(
            branch_id=branch_id,
            date_from=date_from,
            date_to=date_to,
            mode=mode,
            include_no_vendor=inc_no_vendor,
            active_filter=active_filter,
            limit=25000,
            offset=0,
        )

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})

        # Formats
        title_fmt = wb.add_format({'bold': True, 'font_size': 14, 'font_color': '#0F172A'})
        sub_fmt = wb.add_format({'font_size': 10, 'font_color': '#475569'})
        sec_fmt = wb.add_format({'bold': True, 'font_size': 11, 'font_color': '#1E293B', 'bg_color': '#E2E8F0', 'border': 1})
        th_fmt = wb.add_format({'bold': True, 'font_size': 10, 'font_color': '#FFFFFF', 'bg_color': '#0F172A', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        th_in_fmt = wb.add_format({'bold': True, 'font_size': 10, 'font_color': '#FFFFFF', 'bg_color': '#059669', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        th_out_fmt = wb.add_format({'bold': True, 'font_size': 10, 'font_color': '#FFFFFF', 'bg_color': '#E11D48', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        td_l = wb.add_format({'font_size': 10, 'border': 1, 'valign': 'vcenter'})
        td_c = wb.add_format({'font_size': 10, 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        td_int = wb.add_format({'font_size': 10, 'border': 1, 'align': 'right', 'num_format': '#,##0', 'valign': 'vcenter'})
        td_wt = wb.add_format({'font_size': 10, 'border': 1, 'align': 'right', 'num_format': '#,##0.000', 'valign': 'vcenter'})
        td_wt_in = wb.add_format({'font_size': 10, 'border': 1, 'align': 'right', 'num_format': '#,##0.000', 'font_color': '#047857', 'bold': True, 'valign': 'vcenter'})
        td_wt_out = wb.add_format({'font_size': 10, 'border': 1, 'align': 'right', 'num_format': '#,##0.000', 'font_color': '#BE123C', 'bold': True, 'valign': 'vcenter'})
        tot_l = wb.add_format({'bold': True, 'font_size': 10, 'border': 1, 'bg_color': '#F1F5F9', 'valign': 'vcenter'})
        tot_int = wb.add_format({'bold': True, 'font_size': 10, 'border': 1, 'bg_color': '#F1F5F9', 'align': 'right', 'num_format': '#,##0', 'valign': 'vcenter'})
        tot_wt = wb.add_format({'bold': True, 'font_size': 10, 'border': 1, 'bg_color': '#F1F5F9', 'align': 'right', 'num_format': '#,##0.000', 'valign': 'vcenter'})

        branch_lbl = flow_data['selected_branch_name']
        period_lbl = f"{flow_data['date_from']} to {flow_data['date_to']}"

        # ------------------------------------------------------------------
        # Sheet 1: Flow Summary & Branches
        # ------------------------------------------------------------------
        ws1 = wb.add_worksheet('Flow Summary & Branches')
        ws1.write(0, 0, 'Stock Inflow & Outflow Summary', title_fmt)
        ws1.write(1, 0, f"Branch: {branch_lbl}   |   Period: {period_lbl}", sub_fmt)

        k = flow_data['kpis']
        ws1.write(3, 0, 'Overall Stock Equation', sec_fmt)
        ws1.write(3, 1, '', sec_fmt)
        ws1.write(3, 2, '', sec_fmt)
        for col, h in enumerate(['Metric', 'Weight (g)', 'Qty / Pcs']):
            ws1.write(4, col, h, th_fmt)
        eq_rows = [
            ('Opening Stock', k['opening_wt'], k['opening_qty']),
            ('Total Stock Inflow (+)', k['inflow_wt'], k['inflow_qty']),
            ('Total Stock Outflow (-)', k['outflow_wt'], k['outflow_qty']),
            ('Net Flow (In - Out)', k['net_wt'], k['net_qty']),
            ('Closing Stock (=)', k['closing_wt'], k['closing_qty']),
        ]
        for idx, (lbl, wt, q) in enumerate(eq_rows, start=5):
            fmt = tot_l if idx in (5, 9) else td_l
            wfmt = tot_wt if idx in (5, 9) else (td_wt_in if idx == 6 else (td_wt_out if idx == 7 else td_wt))
            ws1.write(idx, 0, lbl, fmt)
            ws1.write(idx, 1, wt, wfmt)
            ws1.write(idx, 2, q, td_wt)

        # Category breakdown table
        ws1.write(3, 4, 'Movement Category Breakdown', sec_fmt)
        for c in range(5, 9):
            ws1.write(3, c, '', sec_fmt)
        for col, h in enumerate(['Direction', 'Category', 'Move Count', 'Weight (g)', 'Share %'], start=4):
            ws1.write(4, col, h, th_fmt)
        cats = flow_data['categories']
        cat_order = ['purchase_in', 'transfer_in', 'sales_return', 'other_in', 'sales_out', 'transfer_out', 'purchase_return', 'other_out']
        for idx, ck in enumerate(cat_order, start=5):
            cd = cats[ck]
            ws1.write(idx, 4, 'INFLOW' if cd['dir'] == 'in' else 'OUTFLOW', td_c)
            ws1.write(idx, 5, cd['label'], td_l)
            ws1.write(idx, 6, cd['count'], td_int)
            ws1.write(idx, 7, cd['wt'], td_wt_in if cd['dir'] == 'in' else td_wt_out)
            ws1.write(idx, 8, cd['share_pct'] / 100.0, wb.add_format({'font_size': 10, 'border': 1, 'align': 'right', 'num_format': '0.0%'}))

        # Branch-wise summary
        start_r = 15
        ws1.write(start_r - 1, 0, 'Branch-Wise Inflow / Outflow Summary', sec_fmt)
        b_headers = [
            'Branch', 'Opening (g)', 'Purchase In (g)', 'Transfer In (g)', 'Other In (g)',
            'Total Inflow (g)', 'Sales Out (g)', 'Transfer Out (g)', 'Other Out (g)',
            'Total Outflow (g)', 'Net Flow (g)', 'Closing (g)'
        ]
        for c in range(1, len(b_headers)):
            ws1.write(start_r - 1, c, '', sec_fmt)
        for c, h in enumerate(b_headers):
            fmt = th_in_fmt if 2 <= c <= 5 else (th_out_fmt if 6 <= c <= 9 else th_fmt)
            ws1.write(start_r, c, h, fmt)

        r = start_r + 1
        for br in flow_data['branch_summary']:
            ws1.write(r, 0, br['branch_name'], td_l)
            ws1.write(r, 1, br['opening_wt'], td_wt)
            ws1.write(r, 2, br['purchase_in_wt'], td_wt)
            ws1.write(r, 3, br['transfer_in_wt'], td_wt)
            ws1.write(r, 4, br['other_in_wt'], td_wt)
            ws1.write(r, 5, br['inflow_wt'], td_wt_in)
            ws1.write(r, 6, br['sales_out_wt'], td_wt)
            ws1.write(r, 7, br['transfer_out_wt'], td_wt)
            ws1.write(r, 8, br['other_out_wt'], td_wt)
            ws1.write(r, 9, br['outflow_wt'], td_wt_out)
            ws1.write(r, 10, br['net_wt'], td_wt)
            ws1.write(r, 11, br['closing_wt'], td_wt)
            r += 1

        ws1.set_column(0, 0, 26)
        ws1.set_column(1, 11, 16)
        ws1.freeze_panes(start_r + 1, 1)

        # ------------------------------------------------------------------
        # Sheet 2: Product-Wise Flow
        # ------------------------------------------------------------------
        ws2 = wb.add_worksheet('Product-Wise Flow')
        ws2.write(0, 0, f'Product-Wise Stock Inflow & Outflow ({branch_lbl} | {period_lbl})', title_fmt)
        p_headers = [
            'Product / Variant', 'Category', 'UoM', 'Opening (g)',
            'Purchase In (g)', 'Transfer In (g)', 'Other In (g)', 'Total Inflow (g)',
            'Sales Out (g)', 'Transfer Out (g)', 'Other Out (g)', 'Total Outflow (g)',
            'Net Flow (g)', 'Closing (g)'
        ]
        for c, h in enumerate(p_headers):
            fmt = th_in_fmt if 4 <= c <= 7 else (th_out_fmt if 8 <= c <= 11 else th_fmt)
            ws2.write(2, c, h, fmt)
        r = 3
        for p in flow_data['product_rows']:
            ws2.write(r, 0, p['product_name'], td_l)
            ws2.write(r, 1, p['category_name'], td_l)
            ws2.write(r, 2, p['uom_name'], td_c)
            ws2.write(r, 3, p['opening_wt'], td_wt)
            ws2.write(r, 4, p['purchase_in_wt'], td_wt)
            ws2.write(r, 5, p['transfer_in_wt'], td_wt)
            ws2.write(r, 6, p['other_in_wt'], td_wt)
            ws2.write(r, 7, p['inflow_wt'], td_wt_in)
            ws2.write(r, 8, p['sales_out_wt'], td_wt)
            ws2.write(r, 9, p['transfer_out_wt'], td_wt)
            ws2.write(r, 10, p['other_out_wt'], td_wt)
            ws2.write(r, 11, p['outflow_wt'], td_wt_out)
            ws2.write(r, 12, p['net_wt'], td_wt)
            ws2.write(r, 13, p['closing_wt'], td_wt)
            r += 1
        ws2.set_column(0, 0, 36)
        ws2.set_column(1, 1, 22)
        ws2.set_column(2, 13, 15)
        ws2.freeze_panes(3, 1)

        # ------------------------------------------------------------------
        # Sheet 3: Movement Ledger
        # ------------------------------------------------------------------
        ws3 = wb.add_worksheet('Movement Ledger')
        ws3.write(0, 0, f'Stock Movement Ledger ({branch_lbl} | {period_lbl})', title_fmt)
        l_headers = [
            'Date & Time', 'Reference', 'Direction', 'Category', 'Branch',
            'From Location', 'To Location', 'Product', 'Label Ref', 'Partner / Vendor',
            'Weight (g)', 'Qty', 'UoM', 'Origin'
        ]
        for c, h in enumerate(l_headers):
            ws3.write(2, c, h, th_fmt)
        r = 3
        for ln in ledger_data['lines']:
            ws3.write(r, 0, ln['date_str'], td_c)
            ws3.write(r, 1, ln['ref_name'], td_l)
            ws3.write(r, 2, 'INFLOW' if ln['direction'] == 'in' else 'OUTFLOW', td_c)
            ws3.write(r, 3, ln['category_label'], td_l)
            ws3.write(r, 4, ln['branch_name'], td_l)
            ws3.write(r, 5, ln['src_location'], td_l)
            ws3.write(r, 6, ln['dst_location'], td_l)
            ws3.write(r, 7, ln['product_name'], td_l)
            ws3.write(r, 8, ln['label_name'], td_c)
            ws3.write(r, 9, ln['partner_name'], td_l)
            ws3.write(r, 10, ln['wt'], td_wt_in if ln['direction'] == 'in' else td_wt_out)
            ws3.write(r, 11, ln['qty'], td_wt)
            ws3.write(r, 12, ln['uom_name'], td_c)
            ws3.write(r, 13, ln['origin'], td_l)
            r += 1
        ws3.set_column(0, 13, 20)
        ws3.set_column(7, 7, 32)
        ws3.freeze_panes(3, 1)

        # ------------------------------------------------------------------
        # Sheet 4: Vendor-Wise Labels Summary
        # ------------------------------------------------------------------
        ws4 = wb.add_worksheet('Vendor-Wise Labels')
        ws4.write(0, 0, f'Vendor-Wise Labels Summary ({branch_lbl} | {period_lbl} | Mode: {mode.title()})', title_fmt)
        if mode == 'movement':
            v_headers = [
                'Vendor', 'Phone', 'Opening Pcs', 'Opening Wt (g)',
                'Inflow Pcs', 'Inflow Wt (g)', 'Outflow Pcs', 'Outflow Wt (g)',
                'Net Flow (g)', 'Closing Pcs', 'Closing Wt (g)', 'Closing Net Wt (g)', 'Closing Fine Wt (g)'
            ]
            for c, h in enumerate(v_headers):
                ws4.write(2, c, h, th_fmt)
            r = 3
            for v in vendor_data['vendors']:
                ws4.write(r, 0, v['vendor_name'], td_l)
                ws4.write(r, 1, v['vendor_phone'], td_c)
                ws4.write(r, 2, v['open_count'], td_int)
                ws4.write(r, 3, v['open_wt'], td_wt)
                ws4.write(r, 4, v['in_count'], td_int)
                ws4.write(r, 5, v['in_wt'], td_wt_in)
                ws4.write(r, 6, v['out_count'], td_int)
                ws4.write(r, 7, v['out_wt'], td_wt_out)
                ws4.write(r, 8, v['net_wt'], td_wt)
                ws4.write(r, 9, v['close_count'], td_int)
                ws4.write(r, 10, v['close_wt'], td_wt)
                ws4.write(r, 11, v['close_net_wt'], td_wt)
                ws4.write(r, 12, v['close_fine_wt'], td_wt)
                r += 1
            vk = vendor_data['kpis']
            ws4.write(r, 0, 'TOTAL', tot_l)
            ws4.write(r, 1, '', tot_l)
            ws4.write(r, 2, vk['open_count'], tot_int)
            ws4.write(r, 3, vk['open_wt'], tot_wt)
            ws4.write(r, 4, vk['in_count'], tot_int)
            ws4.write(r, 5, vk['in_wt'], tot_wt)
            ws4.write(r, 6, vk['out_count'], tot_int)
            ws4.write(r, 7, vk['out_wt'], tot_wt)
            ws4.write(r, 8, vk['net_wt'], tot_wt)
            ws4.write(r, 9, vk['close_count'], tot_int)
            ws4.write(r, 10, vk['close_wt'], tot_wt)
            ws4.write(r, 11, vk['close_net_wt'], tot_wt)
            ws4.write(r, 12, vk['close_fine_wt'], tot_wt)
        else:
            v_headers = [
                'Vendor', 'Phone', 'Total Labels', 'Active Pcs', 'Active Wt (g)',
                'Sold/Inactive Pcs', 'Inactive Wt (g)', 'Gross Wt (g)',
                'Stone Wt (g)', 'Diamond Wt (g)', 'Net Wt (g)', 'Fine Wt (g)'
            ]
            for c, h in enumerate(v_headers):
                ws4.write(2, c, h, th_fmt)
            r = 3
            for v in vendor_data['vendors']:
                ws4.write(r, 0, v['vendor_name'], td_l)
                ws4.write(r, 1, v['vendor_phone'], td_c)
                ws4.write(r, 2, v['total_count'], td_int)
                ws4.write(r, 3, v['active_count'], td_int)
                ws4.write(r, 4, v['active_wt'], td_wt_in)
                ws4.write(r, 5, v['inactive_count'], td_int)
                ws4.write(r, 6, v['inactive_wt'], td_wt_out)
                ws4.write(r, 7, v['gross_wt'], td_wt)
                ws4.write(r, 8, v['stone_wt'], td_wt)
                ws4.write(r, 9, v['diamond_wt'], td_wt)
                ws4.write(r, 10, v['net_wt'], td_wt)
                ws4.write(r, 11, v['fine_wt'], td_wt)
                r += 1
            vk = vendor_data['kpis']
            ws4.write(r, 0, 'TOTAL', tot_l)
            ws4.write(r, 1, '', tot_l)
            ws4.write(r, 2, vk['total_count'], tot_int)
            ws4.write(r, 3, vk['active_count'], tot_int)
            ws4.write(r, 4, vk['active_wt'], tot_wt)
            ws4.write(r, 5, vk['inactive_count'], tot_int)
            ws4.write(r, 6, vk['inactive_wt'], tot_wt)
            ws4.write(r, 7, vk['gross_wt'], tot_wt)
            ws4.write(r, 8, vk['stone_wt'], tot_wt)
            ws4.write(r, 9, vk['diamond_wt'], tot_wt)
            ws4.write(r, 10, vk['net_wt'], tot_wt)
            ws4.write(r, 11, vk['fine_wt'], tot_wt)

        ws4.set_column(0, 0, 34)
        ws4.set_column(1, 12, 16)
        ws4.freeze_panes(3, 1)

        # ------------------------------------------------------------------
        # Sheet 5: Vendor Label Details
        # ------------------------------------------------------------------
        ws5 = wb.add_worksheet('Vendor Label Details')
        ws5.write(0, 0, f'Vendor Label Details ({branch_lbl} | {period_lbl})', title_fmt)
        d_headers = [
            'Label Ref', 'Barcode', 'Vendor', 'Product / Variant', 'Purity',
            'Purchase Order', 'Branch', 'Location', 'Gross Wt (g)', 'Stone Wt (g)',
            'Diamond Wt (g)', 'Net Wt (g)', 'Fine Wt (g)', 'Period Flow', 'Status', 'Created Date'
        ]
        for c, h in enumerate(d_headers):
            ws5.write(2, c, h, th_fmt)
        r = 3
        for lb in label_data['lines']:
            ws5.write(r, 0, lb['label_name'], td_c)
            ws5.write(r, 1, lb['barcode'], td_c)
            ws5.write(r, 2, lb['vendor_name'], td_l)
            ws5.write(r, 3, lb['product_name'], td_l)
            ws5.write(r, 4, lb['purity_name'], td_c)
            ws5.write(r, 5, lb['purchase_name'], td_c)
            ws5.write(r, 6, lb['branch_name'], td_l)
            ws5.write(r, 7, lb['location_name'], td_l)
            ws5.write(r, 8, lb['gross_wt'], td_wt)
            ws5.write(r, 9, lb['stone_wt'], td_wt)
            ws5.write(r, 10, lb['diamond_wt'], td_wt)
            ws5.write(r, 11, lb['net_wt'], td_wt)
            ws5.write(r, 12, lb['fine_wt'], td_wt)
            ws5.write(r, 13, lb['period_flow_label'], td_c)
            ws5.write(r, 14, 'Active' if lb['active'] else 'Sold / Inactive', td_c)
            ws5.write(r, 15, lb['create_date'], td_c)
            r += 1
        ws5.set_column(0, 15, 18)
        ws5.set_column(2, 3, 30)
        ws5.freeze_panes(3, 1)

        wb.close()
        output.seek(0)

        safe_branch = (branch_lbl or 'All').replace(' ', '_').replace('/', '_')
        filename = f"Stock_Inflow_Outflow_{safe_branch}_{flow_data['date_from']}_to_{flow_data['date_to']}.xlsx"
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
            ],
        )

