import io
import base64
from odoo import models, fields, api
from odoo.exceptions import UserError
try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

class ReplacementCostingWizard(models.TransientModel):
    _name = 'replacement.costing.wizard'
    _description = 'Replacement Costing Wizard'

    date_from = fields.Date(string='Date From', required=True, default=fields.Date.context_today)
    date_to = fields.Date(string='Date To', required=True, default=fields.Date.context_today)
    branch_ids = fields.Many2many('res.branch', string='Branches')
    
    only_vault = fields.Boolean('Vault Items Only', default=False)
    excel_file = fields.Binary('Excel Report')
    file_name = fields.Char('File Name')

    def action_print_excel(self):
        if not xlsxwriter:
            raise UserError("The Python library xlsxwriter is required.")
        
        is_vault = self.only_vault or self.env.context.get('default_only_vault', False) or self.env.context.get('only_vault', False)
        
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet_title = "Replacement Costing Vault" if is_vault else "Replacement Costing"
        sheet = workbook.add_worksheet(sheet_title)
        
        bold_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
        date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
        
        headers = ['Date', 'Salesman', 'Voucher']
        if not is_vault:
            headers.append('Label')
        headers.extend(['Product Name', 'Caret', 'Purity', 'Branch'])
        if not is_vault:
            headers.append('PCS')
        headers.extend([
            'PO GW (g)', 'PO NW (g)', 'PO Dia Wt (g)', 'PO Stone Wt (g)', 'PO MC Type',
            'PO MC %',
        ])
        if not is_vault:
            headers.extend(['PO MC Amount', 'PO Metal Rate', 'PO Dia Amt', 'PO Stone Amt'])

        headers.extend([
            'PO MC Fine', 'Metal Qty On Fine',
        ])

        if not is_vault:
            headers.extend(['PO Metal Amt', 'PO MC On Fine Qty', 'PO MC Value', 'PO Taxable Amt'])

        headers.extend([
            'Next Day 1PM Rate',
            'RPC Metal Amt', 'RPC MC Amt',
            'Sale Metal Rate', 'Sale Metal Amt', 'Sale MC %', 'Sale MC Amt',
            'Sale Dia Amt', 'Sale Stone Amt', 'Sale Taxable Amt',
            'Metal Profit', 'MC Profit', 'Diamond Profit', 'Stone Profit', 'Total GP'
        ])
        
        for i, header in enumerate(headers):
            sheet.write(0, i, header, bold_format)
            sheet.set_column(i, i, 15)
            
        domain = [
            ('sale_date', '>=', self.date_from),
            ('sale_date', '<=', self.date_to),
            ('product_id.is_vault_item', '=', True if is_vault else False),
        ]
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
            
        items = self.env['replacement.costing.item'].search(domain, order='sale_date asc')
        if items:
            if is_vault:
                items._update_vault_po_details()
            items._update_rates_next_day_1pm()
            items._compute_all_fields()

        row = 1
        for item in items:
            if is_vault:
                if item.product_id and not getattr(item.product_id, 'is_vault_item', False):
                    continue
            else:
                if item.product_id and getattr(item.product_id, 'is_vault_item', False):
                    continue
            col = 0
            sheet.write(row, col, item.sale_date, date_format); col += 1
            sheet.write(row, col, item.salesman_id.name if item.salesman_id else ''); col += 1
            sheet.write(row, col, item.sales_voucher_name or ''); col += 1
            if not is_vault:
                sheet.write(row, col, item.label_id.name if item.label_id else ''); col += 1
            sheet.write(row, col, item.product_id.name if item.product_id else ''); col += 1
            sheet.write(row, col, item.purity_id.name if item.purity_id else ''); col += 1
            sheet.write(row, col, item.purity); col += 1
            sheet.write(row, col, item.branch_id.name if item.branch_id else ''); col += 1
            if not is_vault:
                sheet.write(row, col, item.pcs_from_sale); col += 1
            
            sheet.write(row, col, item.gross_weight_purchase); col += 1
            sheet.write(row, col, item.net_weight_purchase); col += 1
            sheet.write(row, col, item.diamond_weight_purchase); col += 1
            sheet.write(row, col, item.stone_weight_purchase); col += 1
            
            selection_dict = dict(
                item._fields['purchase_making_charge_type'].selection
            )
            sheet.write(row, col, selection_dict.get(item.purchase_making_charge_type, '')); col += 1
            
            sheet.write(
                row, col,
                item.purchase_mc_percent_fine
                if item.purchase_making_charge_type == 'percent'
                else ''
            ); col += 1

            if not is_vault:
                sheet.write(
                    row, col,
                    item.purchase_mc_amount
                    if item.purchase_making_charge_type in ('amount', 'rate_per_gram')
                    else ''
                ); col += 1
                sheet.write(row, col, item.purchase_metal_rate); col += 1
                sheet.write(row, col, item.diamond_amount_purchase); col += 1
                sheet.write(row, col, item.stone_amount_purchase); col += 1

            sheet.write(row, col, item.purchase_mc_fine); col += 1
            sheet.write(row, col, item.metal_qty_on_fine); col += 1

            if not is_vault:
                sheet.write(row, col, item.metal_amount_purchase); col += 1
                sheet.write(row, col, item.purchase_mc_on_fine_qty); col += 1
                sheet.write(row, col, item.purchase_mc_value); col += 1
                sheet.write(row, col, item.taxable_amount_purchase); col += 1

            sheet.write(row, col, item.rate_fine_next_day_1pm); col += 1
            sheet.write(row, col, item.purchase_metal_amount_on_fine); col += 1
            sheet.write(row, col, item.purchase_mc_amount_on_fine); col += 1
            
            sheet.write(row, col, item.sale_metal_rate_manual); col += 1
            sheet.write(row, col, item.metal_amount_sale); col += 1
            sheet.write(row, col, item.sale_mc_percent); col += 1
            sheet.write(row, col, item.mc_amount_sale); col += 1
            sheet.write(row, col, item.diamond_amount_sale); col += 1
            sheet.write(row, col, item.stone_amount_sale); col += 1
            sheet.write(row, col, item.sale_taxable_amount); col += 1
            
            sheet.write(row, col, item.metal_profit); col += 1
            sheet.write(row, col, item.mc_profit); col += 1
            sheet.write(row, col, item.diamond_profit); col += 1
            sheet.write(row, col, item.stone_profit); col += 1
            sheet.write(row, col, item.total_gp); col += 1
            
            row += 1
            
        workbook.close()
        output.seek(0)
        
        prefix = 'Replacement_Costing_Vault' if is_vault else 'Replacement_Costing'
        self.file_name = f'{prefix}_{self.date_from}_to_{self.date_to}.xlsx'
        self.excel_file = base64.b64encode(output.read())
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'replacement.costing.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
