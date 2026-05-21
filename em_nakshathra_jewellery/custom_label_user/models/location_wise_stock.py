from odoo import models, fields, api
from odoo.osv import expression

class LocationWiseStock(models.Model):
    _name = 'location.wise.stock'
    _description = 'Location Wise Stock'
    _auto = False
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', string="Product")
    product_tmpl_id = fields.Many2one('product.template', string="Product Template")
    location_id = fields.Many2one('stock.location', string="Location")

    quantity = fields.Float(string="On Hand")
    available_quantity = fields.Float(string="Free To Use")

    uom_id = fields.Many2one('uom.uom', string="UOM")

    def init(self):
        self._cr.execute("""
            DROP VIEW IF EXISTS location_wise_stock;
        """)

        self._cr.execute("""
            CREATE OR REPLACE VIEW location_wise_stock AS (

                SELECT
                    sq.id as id,
                    sq.product_id as product_id,
                    pp.product_tmpl_id as product_tmpl_id,
                    sq.location_id as location_id,
                    sq.quantity as quantity,
                    (sq.quantity - sq.reserved_quantity) as available_quantity,
                    pt.uom_id as uom_id

                FROM stock_quant sq

                JOIN product_product pp
                    ON pp.id = sq.product_id

                JOIN product_template pt
                    ON pt.id = pp.product_tmpl_id

                WHERE sq.quantity > 0
            )
        """)

    @api.model
    def _search(self,domain,offset=0,limit=None,order=None,access_rights_uid=None):
        """Override search to filter stock based on the logged-in employee's label location."""
        employee = self.env.user.employee_id
        if employee and employee.label_location_id:
            domain = expression.AND([
                domain,
                [('location_id', '=', employee.label_location_id.id)]
            ])
        return super()._search(
            domain,
            offset=offset,
            limit=limit,
            order=order,
            access_rights_uid=access_rights_uid
        )