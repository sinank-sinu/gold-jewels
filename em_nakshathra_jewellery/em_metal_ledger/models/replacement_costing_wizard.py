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
    
    excel_file = fields.Binary('Excel Report')
    file_name = fields.Char('File Name')

    def action_print_excel(self):
        if not xlsxwriter:
            raise UserError("The Python library xlsxwriter is required.")
        
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet("Replacement Costing")
        
        bold_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
        date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
        
        headers = [
            'Date', 'Salesman', 'Voucher', 'Label', 'Product Name', 'Caret', 'Purity', 'Branch', 'PCS',
            'PO GW (g)', 'PO NW (g)', 'PO Dia Wt (g)', 'PO Stone Wt (g)',
            'PO MC %', 'PO Metal Rate', 'PO Dia Amt', 'PO Stone Amt', 'PO MC Fine',
            'Next Day 1PM Rate', 'Metal Qty On Fine', 'PO Metal Amt',
            'PO MC On Fine Qty', 'PO MC Value', 'PO Taxable Amt',
            'PO Metal Amt On Fine', 'Po MC Amt On Fine',
            'Sale Metal Rate', 'Sale Metal Amt', 'Sale MC %', 'Sale MC Amt',
            'Sale Dia Amt', 'Sale Stone Amt', 'Sale Taxable Amt',
            'Metal Profit', 'MC Profit', 'Diamond Profit', 'Stone Profit', 'Total GP'
        ]
        
        for i, header in enumerate(headers):
            sheet.write(0, i, header, bold_format)
            sheet.set_column(i, i, 15)
            
        domain = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
            
        items = self.env['replacement.costing.item'].search(domain, order='date asc')
        
        row = 1
        for item in items:
            sheet.write(row, 0, item.date, date_format)
            sheet.write(row, 1, item.salesman_id.name if item.salesman_id else '')
            sheet.write(row, 2, item.sales_voucher_name or '')
            sheet.write(row, 3, item.label_id.name if item.label_id else '')
            sheet.write(row, 4, item.product_id.name if item.product_id else '')
            sheet.write(row, 5, item.purity_id.name if item.purity_id else '')
            sheet.write(row, 6, item.purity)
            sheet.write(row, 7, item.branch_id.name if item.branch_id else '')
            
            sheet.write(row, 8, item.pcs_from_sale)
            
            sheet.write(row, 9, item.gross_weight_purchase)
            sheet.write(row, 10, item.net_weight_purchase)
            sheet.write(row, 11, item.diamond_weight_purchase)
            sheet.write(row, 12, item.stone_weight_purchase)
            sheet.write(row, 13, item.purchase_mc_percent_fine)
            sheet.write(row, 14, item.purchase_metal_rate)
            sheet.write(row, 15, item.diamond_amount_purchase)
            sheet.write(row, 16, item.stone_amount_purchase)
            sheet.write(row, 17, item.purchase_mc_fine)
            sheet.write(row, 18, item.rate_fine_next_day_1pm)
            sheet.write(row, 19, item.metal_qty_on_fine)
            sheet.write(row, 20, item.metal_amount_purchase)
            sheet.write(row, 21, item.purchase_mc_on_fine_qty)
            sheet.write(row, 22, item.purchase_mc_value)
            sheet.write(row, 23, item.taxable_amount_purchase)
            sheet.write(row, 24, item.purchase_metal_amount_on_fine)
            sheet.write(row, 25, item.purchase_mc_amount_on_fine)
            
            sheet.write(row, 26, item.sale_metal_rate_manual)
            sheet.write(row, 27, item.metal_amount_sale)
            sheet.write(row, 28, item.sale_mc_percent)
            sheet.write(row, 29, item.mc_amount_sale)
            sheet.write(row, 30, item.diamond_amount_sale)
            sheet.write(row, 31, item.stone_amount_sale)
            sheet.write(row, 32, item.sale_taxable_amount)
            
            sheet.write(row, 33, item.metal_profit)
            sheet.write(row, 34, item.mc_profit)
            sheet.write(row, 35, item.diamond_profit)
            sheet.write(row, 36, item.stone_profit)
            sheet.write(row, 37, item.total_gp)
            
            row += 1
            
        workbook.close()
        output.seek(0)
        
        self.file_name = f'Replacement_Costing_{self.date_from}_to_{self.date_to}.xlsx'
        self.excel_file = base64.b64encode(output.read())
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'replacement.costing.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
