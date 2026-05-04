from odoo import models, fields, tools


class ProductMovementLine(models.Model):
    _name = 'product.movement.line'
    _description = 'Product Movement'
    _auto = False
    _order = 'qty desc'

    product_id = fields.Many2one('product.product', string="Variant")
    product_tmpl_id = fields.Many2one('product.template', string="Product")
    category_id = fields.Many2one('product.category', string="Category")
    weight = fields.Float(string="Weight (g)", digits=(16,3))
    qty = fields.Float(string="Quantity")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)

        self.env.cr.execute("""
            CREATE OR REPLACE VIEW product_movement_line AS (

                SELECT
                    row_number() OVER (ORDER BY pt.id, p.id) AS id,
                    p.id AS product_id,
                    pt.id AS product_tmpl_id,
                    pt.categ_id AS category_id,
                    (pt.weight * 1000) AS weight,
                    SUM(qty) AS qty
                    
                FROM (
                    -- SALES
                    SELECT sol.product_id, sol.product_uom_qty AS qty
                    FROM sale_order_line sol
                    JOIN sale_order so ON sol.order_id = so.id
                    WHERE so.state IN ('sale','done')

                    UNION ALL

                    -- POS
                    SELECT pol.product_id, pol.qty
                    FROM pos_order_line pol
                    JOIN pos_order po ON pol.order_id = po.id
                    WHERE po.state IN ('paid','done')
                ) data

                JOIN product_product p ON p.id = data.product_id
                JOIN product_template pt ON pt.id = p.product_tmpl_id

                GROUP BY p.id, pt.id, pt.categ_id
            )
        """)