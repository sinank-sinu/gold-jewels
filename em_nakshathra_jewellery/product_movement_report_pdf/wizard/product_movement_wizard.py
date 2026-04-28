from odoo import models, fields
from datetime import date


class ProductMovementWizard(models.TransientModel):
    _name = 'product.movement.wizard'
    _description = 'Product Movement Wizard'

    date_from = fields.Date(default=lambda self: date.today().replace(day=1), required=True)
    date_to = fields.Date(default=fields.Date.today, required=True)

    source = fields.Selection([
        ('all', 'Sales + POS'),
        ('sale', 'Sales Only'),
        ('pos', 'POS Only'),
    ], default='all', required=True)

    category_ids = fields.Many2many('product.category')

    def get_report_data(self):
        data = {}

        # ---- SALES ----
        if self.source in ('all', 'sale'):
            sale_domain = [
                ('order_id.state', 'in', ['sale', 'done']),
                ('order_id.date_order', '>=', self.date_from),
                ('order_id.date_order', '<=', self.date_to),
            ]
            if self.category_ids:
                sale_domain.append(('product_id.categ_id', 'in', self.category_ids.ids))
            sale_lines = self.env['sale.order.line'].read_group(
                sale_domain,
                ['product_id', 'product_uom_qty:sum'],
                ['product_id']
            )
            # sale_lines = self.env['sale.order.line'].read_group(
            #     [
            #         ('order_id.state', 'in', ['sale', 'done']),
            #         ('order_id.date_order', '>=', self.date_from),
            #         ('order_id.date_order', '<=', self.date_to)
            #     ],
            #     ['product_id', 'product_uom_qty:sum'],
            #     ['product_id']
            # )

            for line in sale_lines:
                pid = line['product_id'][0]
                data[pid] = data.get(pid, 0) + line['product_uom_qty']

        # ---- POS ----
        if self.source in ('all', 'pos'):
            pos_domain = [
                ('order_id.state', 'in', ['paid', 'done']),
                ('order_id.date_order', '>=', self.date_from),
                ('order_id.date_order', '<=', self.date_to),
            ]
            if self.category_ids:
                pos_domain.append(('product_id.categ_id', 'in', self.category_ids.ids))

            pos_lines = self.env['pos.order.line'].read_group(
                pos_domain,
                ['product_id', 'qty:sum'],
                ['product_id']
            )
            # pos_lines = self.env['pos.order.line'].read_group(
            #     [
            #         ('order_id.state', 'in', ['paid', 'done']),
            #         ('order_id.date_order', '>=', self.date_from),
            #         ('order_id.date_order', '<=', self.date_to),
            #         ],
            #     ['product_id', 'qty:sum'],
            #     ['product_id']
            # )

            for line in pos_lines:
                pid = line['product_id'][0]
                data[pid] = data.get(pid, 0) + line['qty']

        products = self.env['product.product'].browse(list(data.keys()))

        rows = []
        for p in products:
            rows.append({
                'name': p.display_name,
                'category': p.categ_id.complete_name or '',
                'qty': data[p.id],
            })

        rows.sort(key=lambda x: x['qty'], reverse=True)

        return rows

    def action_print(self):
        return self.env.ref(
            'product_movement_report_pdf.product_movement_report_action'
        ).report_action(self, data={
            'rows': self.get_report_data(),
            'date_from': str(self.date_from),
            'date_to': str(self.date_to),
        })
    
    def action_export_excel(self):
        return self.env.ref(
            'product_movement_report_pdf.product_movement_xlsx_action'
        ).report_action(self, data={
            'rows': self.get_report_data(),
            'date_from': str(self.date_from),
            'date_to': str(self.date_to),
        })