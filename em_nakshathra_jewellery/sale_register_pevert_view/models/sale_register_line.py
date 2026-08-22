# -*- coding: utf-8 -*-
from odoo import models, fields, tools


class SaleRegisterLine(models.Model):
    _name = 'sale.register.line'
    _description = 'Sale Register Line (Pivot View)'
    _auto = False
    _rec_name = 'so_number'
    _order = 'date_order desc, so_number'

    # Order-level
    so_number       = fields.Char('SO Number', readonly=True)
    order_id        = fields.Many2one('sale.order', 'Sale Order', readonly=True)
    date_order      = fields.Date('Date', readonly=True)
    partner_id      = fields.Many2one('res.partner', 'Customer', readonly=True)
    salesperson_id  = fields.Many2one('res.users', 'Salesperson', readonly=True)
    branch_id       = fields.Many2one('res.branch', 'Branch', readonly=True)
    state           = fields.Selection([
        ('draft', 'Quotation'), ('sent', 'Quotation Sent'),
        ('sale', 'Sales Order'), ('done', 'Locked'), ('cancel', 'Cancelled'),
    ], string='Status', readonly=True)
    amount_total    = fields.Float('Total Amount', readonly=True)
    currency_id     = fields.Many2one('res.currency', 'Currency', readonly=True)

    # Line-level
    product_id      = fields.Many2one('product.product', 'Product', readonly=True)
    quantity        = fields.Float('Quantity', readonly=True)
    qty_delivered   = fields.Float('Delivered', readonly=True)
    price_unit      = fields.Float('Unit Price', readonly=True)
    price_subtotal  = fields.Float('Subtotal', readonly=True)
    price_tax       = fields.Float('Tax', readonly=True)
    product_uom_id  = fields.Many2one('uom.uom', 'UoM', readonly=True)

    # Jewellery
    purity_id       = fields.Many2one('gold.purity', 'Purity', readonly=True)
    net_weight      = fields.Float('Net Weight (g)', digits=(16, 3), readonly=True)
    fine_weight     = fields.Float('Fine Weight (g)', digits=(16, 3), readonly=True)
    gold_rate       = fields.Float('Gold Rate (g)', readonly=True)
    metal_amount    = fields.Float('Metal Amount', readonly=True)
    mc_percent_actual = fields.Float('MC%', readonly=True)
    mc_amount_actual  = fields.Float('MC Amount', readonly=True)
    mc_discount     = fields.Float('Discount', readonly=True)
    sale_return_price = fields.Float('Sale Return Price', readonly=True)

    # Payments (first line per order only, to avoid pivot double-count)
    old_gold_amount = fields.Float('Old Gold Amount', readonly=True)
    bank_amount     = fields.Float('Bank', readonly=True)
    cash_amount     = fields.Float('Cash', readonly=True)
    card_amount     = fields.Float('Card', readonly=True)
    upi_amount      = fields.Float('UPI', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)

        def has_column(table_name, col_name):
            self.env.cr.execute(f"""
                SELECT 1 FROM information_schema.columns
                WHERE table_name='{table_name}' AND column_name='{col_name}'
            """)
            return bool(self.env.cr.fetchone())

        old_gold_expr = "COALESCE(so.old_gold_bill_amount, 0)" if has_column('sale_order', 'old_gold_bill_amount') else "0::numeric"

        has_purity = has_column('sale_order_line', 'purity_id')
        purity_expr = "sol.purity_id" if has_purity else "NULL::integer"
        purity_join = "LEFT JOIN gold_purity gp ON gp.id = sol.purity_id" if has_purity else "LEFT JOIN gold_purity gp ON 1=0"

        has_net_weight = has_column('sale_order_line', 'net_weight')
        has_fine_weight = has_column('sale_order_line', 'fine_weight')
        has_gold_rate = has_column('sale_order_line', 'gold_rate')
        has_metal_amount = has_column('sale_order_line', 'metal_amount')
        has_mc_percent = has_column('sale_order_line', 'mc_percent_actual')
        has_mc_amount = has_column('sale_order_line', 'mc_amount_actual')
        has_mc_discount = has_column('sale_order_line', 'mc_discount')

        has_stone_wt = has_column('sale_order_line', 'sale_stone_weight')
        has_diamond_wt = has_column('sale_order_line', 'sale_diamond_weight_gm')
        has_stone_rate = has_column('sale_order_line', 'sale_stone_rate')
        has_diamond_rate = has_column('sale_order_line', 'sale_diamond_rate')
        has_other_wt_amt = has_column('sale_order_line', 'other_weight_amount')
        has_is_scheme = has_column('sale_order_line', 'is_scheme_line')

        stone_wt_sql = "COALESCE(sol.sale_stone_weight, 0)" if has_stone_wt else "0::numeric"
        diamond_wt_sql = "COALESCE(sol.sale_diamond_weight_gm, 0)" if has_diamond_wt else "0::numeric"
        stone_rate_sql = "COALESCE(sol.sale_stone_rate, 0)" if has_stone_rate else "0::numeric"
        diamond_rate_sql = "COALESCE(sol.sale_diamond_rate, 0)" if has_diamond_rate else "0::numeric"
        other_wt_amt_sql = "COALESCE(sol.other_weight_amount, 0)" if has_other_wt_amt else "0::numeric"
        is_scheme_sql = "sol.is_scheme_line" if has_is_scheme else "FALSE"

        gold_rate_expr = "COALESCE(sol.gold_rate, 0)" if has_gold_rate else "0::numeric"
        mc_percent_expr = "COALESCE(sol.mc_percent_actual, 0)" if has_mc_percent else "0::numeric"
        mc_discount_expr = "COALESCE(sol.mc_discount, 0)" if has_mc_discount else "0::numeric"

        net_wt_fallback = f"GREATEST(0, COALESCE(sol.product_uom_qty, 0) - {stone_wt_sql} - {diamond_wt_sql})"
        if has_net_weight:
            net_weight_expr = f"""
                CASE
                    WHEN {is_scheme_sql} IS TRUE THEN 0
                    WHEN sol.net_weight IS NOT NULL AND sol.net_weight > 0 THEN sol.net_weight
                    ELSE {net_wt_fallback}
                END
            """
        else:
            net_weight_expr = f"""
                CASE
                    WHEN {is_scheme_sql} IS TRUE THEN 0
                    ELSE {net_wt_fallback}
                END
            """

        if has_fine_weight:
            fine_weight_expr = f"""
                CASE
                    WHEN {is_scheme_sql} IS TRUE THEN 0
                    WHEN sol.fine_weight IS NOT NULL AND sol.fine_weight > 0 THEN sol.fine_weight
                    WHEN gp.percentage IS NOT NULL AND gp.percentage > 0 THEN
                        ({net_weight_expr}) * (gp.percentage / 100.0)
                    ELSE 0
                END
            """
        else:
            fine_weight_expr = f"""
                CASE
                    WHEN {is_scheme_sql} IS TRUE THEN 0
                    WHEN gp.percentage IS NOT NULL AND gp.percentage > 0 THEN
                        ({net_weight_expr}) * (gp.percentage / 100.0)
                    ELSE 0
                END
            """

        if has_metal_amount:
            metal_amount_expr = f"""
                CASE
                    WHEN {is_scheme_sql} IS TRUE THEN 0
                    WHEN sol.metal_amount IS NOT NULL AND sol.metal_amount > 0 THEN sol.metal_amount
                    ELSE ({net_weight_expr}) * {gold_rate_expr}
                END
            """
        else:
            metal_amount_expr = f"""
                CASE
                    WHEN {is_scheme_sql} IS TRUE THEN 0
                    ELSE ({net_weight_expr}) * {gold_rate_expr}
                END
            """

        if has_mc_amount:
            mc_amount_expr = f"""
                CASE
                    WHEN {is_scheme_sql} IS TRUE THEN 0
                    WHEN sol.mc_amount_actual IS NOT NULL AND sol.mc_amount_actual > 0 THEN sol.mc_amount_actual
                    WHEN {mc_percent_expr} > 0 THEN ({metal_amount_expr}) * ({mc_percent_expr} / 100.0)
                    WHEN sol.price_subtotal IS NOT NULL AND sol.price_subtotal > ({metal_amount_expr}) THEN
                        GREATEST(0, sol.price_subtotal - ({metal_amount_expr}) - {stone_rate_sql} - {diamond_rate_sql} - {other_wt_amt_sql})
                    ELSE 0
                END
            """
        else:
            mc_amount_expr = f"""
                CASE
                    WHEN {is_scheme_sql} IS TRUE THEN 0
                    WHEN {mc_percent_expr} > 0 THEN ({metal_amount_expr}) * ({mc_percent_expr} / 100.0)
                    WHEN sol.price_subtotal IS NOT NULL AND sol.price_subtotal > ({metal_amount_expr}) THEN
                        GREATEST(0, sol.price_subtotal - ({metal_amount_expr}) - {stone_rate_sql} - {diamond_rate_sql} - {other_wt_amt_sql})
                    ELSE 0
                END
            """

        # In Odoo 17, sale.order.invoice_ids is computed (no M2M table).
        # Real link: sale_order_line -> sale_order_line_invoice_rel -> account_move_line -> account_move
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW sale_register_line AS (
                WITH payment_data AS (
                    SELECT
                        sol_p.order_id,
                        SUM(CASE WHEN lower(aj.name::text) LIKE '%%card%%'
                                   OR lower(aj.code::text) LIKE '%%card%%'
                             THEN apr.amount ELSE 0 END) AS card_amount,
                        SUM(CASE WHEN lower(aj.name::text) NOT LIKE '%%card%%'
                                  AND lower(aj.code::text) NOT LIKE '%%card%%'
                                  AND (lower(aj.name::text) LIKE '%%upi%%'
                                    OR lower(aj.code::text) LIKE '%%upi%%')
                             THEN apr.amount ELSE 0 END) AS upi_amount,
                        SUM(CASE WHEN lower(aj.name::text) NOT LIKE '%%card%%'
                                  AND lower(aj.code::text) NOT LIKE '%%card%%'
                                  AND lower(aj.name::text) NOT LIKE '%%upi%%'
                                  AND lower(aj.code::text) NOT LIKE '%%upi%%'
                                  AND (lower(aj.name::text) LIKE '%%cash%%'
                                    OR lower(aj.code::text) LIKE '%%cash%%')
                             THEN apr.amount ELSE 0 END) AS cash_amount,
                        SUM(CASE WHEN lower(aj.name::text) NOT LIKE '%%card%%'
                                  AND lower(aj.code::text) NOT LIKE '%%card%%'
                                  AND lower(aj.name::text) NOT LIKE '%%upi%%'
                                  AND lower(aj.code::text) NOT LIKE '%%upi%%'
                                  AND lower(aj.name::text) NOT LIKE '%%cash%%'
                                  AND lower(aj.code::text) NOT LIKE '%%cash%%'
                                  AND (lower(aj.name::text) LIKE '%%bank%%'
                                    OR lower(aj.code::text) LIKE '%%bank%%')
                             THEN apr.amount ELSE 0 END) AS bank_amount
                    FROM sale_order_line sol_p
                    JOIN sale_order_line_invoice_rel slir
                        ON slir.order_line_id = sol_p.id
                    JOIN account_move_line aml_inv
                        ON aml_inv.id = slir.invoice_line_id
                    JOIN account_move am
                        ON am.id = aml_inv.move_id
                       AND am.move_type IN ('out_invoice', 'out_refund')
                       AND am.state = 'posted'
                    JOIN account_move_line aml
                        ON aml.move_id = am.id
                    JOIN account_account aa
                        ON aa.id = aml.account_id
                       AND aa.account_type = 'asset_receivable'
                    JOIN account_partial_reconcile apr
                        ON (apr.debit_move_id = aml.id OR apr.credit_move_id = aml.id)
                    JOIN account_move_line aml2
                        ON aml2.id = CASE
                            WHEN apr.debit_move_id = aml.id THEN apr.credit_move_id
                            ELSE apr.debit_move_id END
                    JOIN account_move am2
                        ON am2.id = aml2.move_id AND am2.payment_id IS NOT NULL
                    JOIN account_payment ap
                        ON ap.id = am2.payment_id
                    JOIN account_journal aj ON aj.id = am2.journal_id
                    GROUP BY sol_p.order_id
                ),
                invoice_data AS (
                    SELECT
                        sol_i.order_id,
                        COALESCE(am_i.sale_return_price, 0) AS sale_return_price
                    FROM sale_order_line sol_i
                    JOIN sale_order_line_invoice_rel slir_i
                        ON slir_i.order_line_id = sol_i.id
                    JOIN account_move_line aml_inv_i
                        ON aml_inv_i.id = slir_i.invoice_line_id
                    JOIN account_move am_i
                        ON am_i.id = aml_inv_i.move_id
                       AND am_i.move_type IN ('out_invoice', 'out_refund')
                       AND am_i.state = 'posted'
                    GROUP BY sol_i.order_id, am_i.sale_return_price
                ),
                line_rank AS (
                    SELECT sol.id,
                           ROW_NUMBER() OVER (PARTITION BY sol.order_id ORDER BY sol.id) AS rn
                    FROM sale_order_line sol
                    JOIN sale_order so ON sol.order_id = so.id
                    WHERE so.state IN ('sale', 'done')
                )
                SELECT
                    sol.id,
                    so.id                              AS order_id,
                    so.name                            AS so_number,
                    so.date_order::date                AS date_order,
                    so.partner_id,
                    so.user_id                         AS salesperson_id,
                    so.branch_id,
                    so.state,
                    so.amount_total,
                    so.currency_id,
                    sol.product_id,
                    sol.product_uom_qty                AS quantity,
                    sol.qty_delivered,
                    sol.price_unit,
                    sol.price_subtotal,
                    sol.price_tax,
                    sol.product_uom                    AS product_uom_id,
                    """ + purity_expr + """             AS purity_id,
                    """ + net_weight_expr + """         AS net_weight,
                    """ + fine_weight_expr + """        AS fine_weight,
                    """ + gold_rate_expr + """          AS gold_rate,
                    """ + metal_amount_expr + """       AS metal_amount,
                    """ + mc_percent_expr + """         AS mc_percent_actual,
                    """ + mc_amount_expr + """          AS mc_amount_actual,
                    """ + mc_discount_expr + """        AS mc_discount,
                    CASE WHEN lr.rn = 1 THEN COALESCE(id.sale_return_price, 0)
                         ELSE 0 END                    AS sale_return_price,
                    CASE WHEN lr.rn = 1 THEN """ + old_gold_expr + """
                         ELSE 0 END                    AS old_gold_amount,
                    CASE WHEN lr.rn = 1 THEN COALESCE(pd.bank_amount, 0)
                         ELSE 0 END                    AS bank_amount,
                    CASE WHEN lr.rn = 1 THEN COALESCE(pd.cash_amount, 0)
                         ELSE 0 END                    AS cash_amount,
                    CASE WHEN lr.rn = 1 THEN COALESCE(pd.card_amount, 0)
                         ELSE 0 END                    AS card_amount,
                    CASE WHEN lr.rn = 1 THEN COALESCE(pd.upi_amount, 0)
                         ELSE 0 END                    AS upi_amount
                FROM sale_order_line sol
                JOIN sale_order so   ON sol.order_id = so.id
                JOIN line_rank lr    ON lr.id = sol.id
                """ + purity_join + """
                LEFT JOIN payment_data pd ON pd.order_id = so.id
                LEFT JOIN invoice_data id ON id.order_id = so.id
                WHERE so.state IN ('sale', 'done')
            )
        """)
