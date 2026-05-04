from odoo import models, fields
from datetime import date, datetime, time

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

    def action_view_tree(self):

        # clear old data
        self.env['product.movement.line'].search([]).unlink()

        data = {}

        date_from = datetime.combine(self.date_from, time.min)
        date_to = datetime.combine(self.date_to, time.max)

        # -------- SALES --------
        if self.source in ('all', 'sale'):
            sale_lines = self.env['sale.order.line'].read_group(
                [
                    ('order_id.state', 'in', ['sale', 'done']),
                    ('order_id.date_order', '>=', date_from),
                    ('order_id.date_order', '<=', date_to),
                ],
                ['product_id', 'product_uom_qty:sum'],
                ['product_id']
            )

            for line in sale_lines:
                pid = line['product_id'][0]
                data[pid] = data.get(pid, 0) + line['product_uom_qty']

        # -------- POS --------
        if self.source in ('all', 'pos'):
            pos_lines = self.env['pos.order.line'].read_group(
                [
                    ('order_id.state', 'in', ['paid', 'done']),
                    ('order_id.date_order', '>=', date_from),
                    ('order_id.date_order', '<=', date_to),
                ],
                ['product_id', 'qty:sum'],
                ['product_id']
            )

            for line in pos_lines:
                pid = line['product_id'][0]
                data[pid] = data.get(pid, 0) + line['qty']

        # -------- BUILD TREE --------
        lines_model = self.env['product.movement.line']
        templates = {}

        for pid, qty in data.items():
            product = self.env['product.product'].browse(pid)
            tmpl = product.product_tmpl_id

            # create parent if not exists
            if tmpl.id not in templates:
                parent = lines_model.create({
                    'product_tmpl_id': tmpl.id,
                    'category_id': tmpl.categ_id.id,
                    'qty': 0,
                    'is_parent': True,
                })
                templates[tmpl.id] = parent
            else:
                parent = templates[tmpl.id]

            # create child (variant)
            lines_model.create({
                'product_id': pid,
                'product_tmpl_id': tmpl.id,
                'category_id': tmpl.categ_id.id,
                'qty': qty,
                'parent_id': parent.id
            })

            # update total
            parent.qty += qty

        return {
            'type': 'ir.actions.act_window',
            'name': 'Product Movement',
            'res_model': 'product.movement.line',
            'view_mode': 'tree',
            'target': 'current',
        }