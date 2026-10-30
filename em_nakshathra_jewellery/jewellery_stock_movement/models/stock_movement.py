# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StockMovementReport(models.Model):
    _name = 'stock.movement.report'
    _description = 'Stock Movement Report by Warehouse & Variant'
    _order = 'product_tmpl_id asc, product_id asc'

    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', readonly=True, index=True)
    product_tmpl_id = fields.Many2one('product.template', string='Product', readonly=True, index=True)
    product_id = fields.Many2one('product.product', string='Variant / Product', readonly=True, index=True)
    categ_id = fields.Many2one('product.category', string='Category', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', readonly=True)
    qty_in = fields.Float(string='Stock In', digits=(16, 3), readonly=True)
    qty_out = fields.Float(string='Stock Out', digits=(16, 3), readonly=True)
    balance = fields.Float(string='Balance', digits=(16, 3), readonly=True)
    weight = fields.Float(string='Weight (g)', digits=(16, 3), readonly=True)

    @api.model
    def compute_report_data(self, warehouse_id=False, date_from=False, date_to=False):
        """
        Generate dynamic movement data for the current user and return summary stats.
        """
        cr = self.env.cr
        uid = self.env.user.id

        # Delete previous lines for this user
        cr.execute("DELETE FROM stock_movement_report WHERE create_uid = %s", [uid])

        import re

        if warehouse_id:
            try:
                warehouse_id = int(warehouse_id)
            except (ValueError, TypeError):
                warehouse_id = False

        if date_from and not re.match(r'^\d{4}-\d{2}-\d{2}$', str(date_from)):
            date_from = False
        if date_to and not re.match(r'^\d{4}-\d{2}-\d{2}$', str(date_to)):
            date_to = False

        # Prepare date filter clauses
        date_clauses_in = []
        date_clauses_out = []
        if date_from:
            dt_from = f"{date_from} 00:00:00"
            date_clauses_in.append(f"sm.date >= '{dt_from}'")
            date_clauses_out.append(f"sm.date >= '{dt_from}'")
        if date_to:
            dt_to = f"{date_to} 23:59:59"
            date_clauses_in.append(f"sm.date <= '{dt_to}'")
            date_clauses_out.append(f"sm.date <= '{dt_to}'")

        extra_date_in = ("AND " + " AND ".join(date_clauses_in)) if date_clauses_in else ""
        extra_date_out = ("AND " + " AND ".join(date_clauses_out)) if date_clauses_out else ""

        # Prepare warehouse filter clauses
        wh_dest = f"AND dest_loc.warehouse_id = {warehouse_id}" if warehouse_id else ""
        wh_src = f"AND src_loc.warehouse_id = {warehouse_id}" if warehouse_id else ""
        wh_bal = f"AND loc.warehouse_id = {warehouse_id}" if warehouse_id else ""

        insert_sql = f"""
            INSERT INTO stock_movement_report (
                warehouse_id, product_tmpl_id, product_id, categ_id, uom_id,
                qty_in, qty_out, balance, weight,
                create_uid, write_uid, create_date, write_date
            )
            WITH internal_locs AS (
                SELECT sl.id, sl.warehouse_id
                FROM stock_location sl
                WHERE sl.usage = 'internal' AND sl.warehouse_id IS NOT NULL
            ),
            moves_in AS (
                SELECT 
                    dest_loc.warehouse_id,
                    sm.product_id,
                    SUM(sm.quantity) AS qty_in
                FROM stock_move sm
                JOIN internal_locs dest_loc ON sm.location_dest_id = dest_loc.id {wh_dest}
                LEFT JOIN internal_locs src_loc ON sm.location_id = src_loc.id AND src_loc.warehouse_id = dest_loc.warehouse_id
                WHERE sm.state = 'done'
                  AND src_loc.id IS NULL
                  {extra_date_in}
                GROUP BY dest_loc.warehouse_id, sm.product_id
            ),
            moves_out AS (
                SELECT 
                    src_loc.warehouse_id,
                    sm.product_id,
                    SUM(sm.quantity) AS qty_out
                FROM stock_move sm
                JOIN internal_locs src_loc ON sm.location_id = src_loc.id {wh_src}
                LEFT JOIN internal_locs dest_loc ON sm.location_dest_id = dest_loc.id AND dest_loc.warehouse_id = src_loc.warehouse_id
                WHERE sm.state = 'done'
                  AND dest_loc.id IS NULL
                  {extra_date_out}
                GROUP BY src_loc.warehouse_id, sm.product_id
            ),
            balances AS (
                SELECT 
                    loc.warehouse_id,
                    sq.product_id,
                    SUM(sq.quantity) AS balance
                FROM stock_quant sq
                JOIN internal_locs loc ON sq.location_id = loc.id {wh_bal}
                GROUP BY loc.warehouse_id, sq.product_id
            )
            SELECT 
                coalesce(mi.warehouse_id, mo.warehouse_id, b.warehouse_id) AS warehouse_id,
                pp.product_tmpl_id AS product_tmpl_id,
                coalesce(mi.product_id, mo.product_id, b.product_id) AS product_id,
                pt.categ_id AS categ_id,
                pt.uom_id AS uom_id,
                COALESCE(mi.qty_in, 0.0) AS qty_in,
                COALESCE(mo.qty_out, 0.0) AS qty_out,
                COALESCE(b.balance, 0.0) AS balance,
                CASE 
                    WHEN COALESCE(uom.name->>'en_US', uom.name::text) ILIKE '%gm%' 
                      OR COALESCE(uom.name->>'en_US', uom.name::text) ILIKE '%gram%'
                    THEN COALESCE(b.balance, 0.0)
                    ELSE COALESCE(b.balance, 0.0) * COALESCE(pt.weight, 0.0)
                END AS weight,
                {uid}, {uid}, NOW(), NOW()
            FROM moves_in mi
            FULL OUTER JOIN moves_out mo 
                ON mi.warehouse_id = mo.warehouse_id AND mi.product_id = mo.product_id
            FULL OUTER JOIN balances b 
                ON coalesce(mi.warehouse_id, mo.warehouse_id) = b.warehouse_id 
               AND coalesce(mi.product_id, mo.product_id) = b.product_id
            JOIN product_product pp ON pp.id = coalesce(mi.product_id, mo.product_id, b.product_id)
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN uom_uom uom ON pt.uom_id = uom.id
            WHERE coalesce(mi.warehouse_id, mo.warehouse_id, b.warehouse_id) IS NOT NULL
        """
        cr.execute(insert_sql)

        # Compute summary counters
        cr.execute("""
            SELECT 
                COUNT(DISTINCT product_tmpl_id),
                COUNT(DISTINCT product_id),
                COALESCE(SUM(weight), 0.0)
            FROM stock_movement_report
            WHERE create_uid = %s
        """, [uid])
        res = cr.fetchone() or (0, 0, 0.0)

        return {
            'total_products': res[0],
            'total_variants': res[1],
            'total_weight': round(res[2], 3),
        }
