from odoo import models, fields, api

class SaleRegisterLine(models.Model):
    _name = 'sale.register.line'
    _description = 'Sale Register Line View'
    _auto = False

    so_number = fields.Char(string='SO Number')
    date_order = fields.Date(string='Date')
    partner_id = fields.Many2one('res.partner', string='Customer')
    salesperson_id = fields.Many2one('res.users', string='Salesperson')
    branch_id = fields.Many2one('res.branch', string='Branch')
    state = fields.Selection([
        ('draft', 'Quotation'),
        ('sent', 'Quotation Sent'),
        ('sale', 'Sales Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled'),
    ], string='Status')
    amount_total = fields.Monetary(string='Total Amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency')

    product_id = fields.Many2one('product.product', string='Product')
    quantity = fields.Float(string='Qty')
    qty_delivered = fields.Float(string='Delivered')
    price_unit = fields.Monetary(string='Unit Price', currency_field='currency_id')
    price_subtotal = fields.Monetary(string='Subtotal', currency_field='currency_id')
    price_tax = fields.Monetary(string='Tax', currency_field='currency_id')
    product_uom_id = fields.Many2one('uom.uom', string='UoM')
    purity_id = fields.Many2one('gold.purity', string='Purity')

    net_weight = fields.Float(string='Net Wt (g)')
    fine_weight = fields.Float(string='Fine Wt (g)')
    gold_rate = fields.Float(string='Gold Rate')
    metal_amount = fields.Float(string='Metal Amt')
    mc_percent_actual = fields.Float(string='MC%')
    mc_amount_actual = fields.Float(string='MC Amount')
    mc_discount = fields.Float(string='Discount')

    sale_return_price = fields.Monetary(string='Sales Return Amt', currency_field='currency_id')
    old_gold_amount = fields.Monetary(string='Old Gold Amt', currency_field='currency_id')
    bank_amount = fields.Monetary(string='Bank Amt', currency_field='currency_id')
    cash_amount = fields.Monetary(string='Cash Amt', currency_field='currency_id')
    card_amount = fields.Monetary(string='Card Amt', currency_field='currency_id')
    upi_amount = fields.Monetary(string='UPI Amt', currency_field='currency_id')

    def init(self):
        self.env.cr.execute("""
            DROP VIEW IF EXISTS sale_register_line CASCADE;
            CREATE VIEW sale_register_line AS (
                WITH payment_data AS (
                    SELECT
                        sol_p.order_id,
                        SUM(CASE WHEN lower(aj.name::text) LIKE '%%card%%' OR lower(aj.code::text) LIKE '%%card%%' THEN apr.amount ELSE 0 END) AS card_amount,
                        SUM(CASE WHEN lower(aj.name::text) NOT LIKE '%%card%%' AND lower(aj.code::text) NOT LIKE '%%card%%' AND (lower(aj.name::text) LIKE '%%upi%%' OR lower(aj.code::text) LIKE '%%upi%%') THEN apr.amount ELSE 0 END) AS upi_amount,
                        SUM(CASE WHEN lower(aj.name::text) NOT LIKE '%%card%%' AND lower(aj.code::text) NOT LIKE '%%card%%' AND lower(aj.name::text) NOT LIKE '%%upi%%' AND lower(aj.code::text) NOT LIKE '%%upi%%' AND (lower(aj.name::text) LIKE '%%cash%%' OR lower(aj.code::text) LIKE '%%cash%%') THEN apr.amount ELSE 0 END) AS cash_amount,
                        SUM(CASE WHEN lower(aj.name::text) NOT LIKE '%%card%%' AND lower(aj.code::text) NOT LIKE '%%card%%' AND lower(aj.name::text) NOT LIKE '%%upi%%' AND lower(aj.code::text) NOT LIKE '%%upi%%' AND lower(aj.name::text) NOT LIKE '%%cash%%' AND lower(aj.code::text) NOT LIKE '%%cash%%' AND (lower(aj.name::text) LIKE '%%bank%%' OR lower(aj.code::text) LIKE '%%bank%%') THEN apr.amount ELSE 0 END) AS bank_amount
                    FROM sale_order_line sol_p
                    JOIN sale_order_line_invoice_rel slir ON slir.order_line_id = sol_p.id
                    JOIN account_move_line aml_inv ON aml_inv.id = slir.invoice_line_id
                    JOIN account_move am ON am.id = aml_inv.move_id AND am.move_type IN ('out_invoice', 'out_refund') AND am.state = 'posted'
                    JOIN account_move_line aml ON aml.move_id = am.id
                    JOIN account_account aa ON aa.id = aml.account_id AND aa.account_type = 'asset_receivable'
                    JOIN account_partial_reconcile apr ON apr.debit_move_id = aml.id OR apr.credit_move_id = aml.id
                    JOIN account_move_line aml2 ON aml2.id = (CASE WHEN apr.debit_move_id = aml.id THEN apr.credit_move_id ELSE apr.debit_move_id END)
                    JOIN account_move am2 ON am2.id = aml2.move_id AND am2.payment_id IS NOT NULL
                    JOIN account_payment ap ON ap.id = am2.payment_id
                    JOIN account_journal aj ON aj.id = am2.journal_id
                    GROUP BY sol_p.order_id
                ),
                invoice_data AS (
                    SELECT
                        sol_i.order_id,
                        COALESCE(am_i.sale_return_price, 0) AS sale_return_price
                    FROM sale_order_line sol_i
                    JOIN sale_order_line_invoice_rel slir_i ON slir_i.order_line_id = sol_i.id
                    JOIN account_move_line aml_inv_i ON aml_inv_i.id = slir_i.invoice_line_id
                    JOIN account_move am_i ON am_i.id = aml_inv_i.move_id AND am_i.move_type IN ('out_invoice', 'out_refund') AND am_i.state = 'posted'
                    GROUP BY sol_i.order_id, am_i.sale_return_price
                ),
                old_gold_data AS (
                    SELECT
                        sale_id,
                        SUM(amount) AS total_old_gold
                    FROM sale_old_gold_line
                    GROUP BY sale_id
                ),
                line_rank AS (
                    SELECT
                        sol.id,
                        ROW_NUMBER() OVER (PARTITION BY sol.order_id ORDER BY sol.id) AS rn
                    FROM sale_order_line sol
                    JOIN sale_order so ON sol.order_id = so.id
                    WHERE so.state IN ('sale', 'done')
                )
                SELECT
                    sol.id,
                    so.id AS order_id,
                    so.name AS so_number,
                    so.date_order::date AS date_order,
                    so.partner_id,
                    so.user_id AS salesperson_id,
                    so.branch_id,
                    so.state,
                    so.amount_total,
                    so.currency_id,
                    sol.product_id,
                    sol.product_uom_qty AS quantity,
                    sol.qty_delivered,
                    sol.price_unit,
                    sol.price_subtotal,
                    sol.price_tax,
                    sol.product_uom AS product_uom_id,
                    sol.purity_id,

                    (COALESCE(sol.sale_gross_weight, sol.product_uom_qty, 0) - COALESCE(sol.sale_stone_weight, 0) - COALESCE(sol.sale_diamond_weight_gm, 0))::numeric AS net_weight,

                    ((COALESCE(sol.sale_gross_weight, sol.product_uom_qty, 0) - COALESCE(sol.sale_stone_weight, 0) - COALESCE(sol.sale_diamond_weight_gm, 0)) * 
                     COALESCE(gp.percentage, CASE 
                        WHEN gp.name LIKE '%%(92)%%' THEN 92.0 
                        WHEN gp.name LIKE '%%(91.6)%%' THEN 91.6 
                        WHEN gp.name LIKE '%%(75.5)%%' THEN 75.5 
                        WHEN gp.name LIKE '%%(75)%%' THEN 75.0 
                        WHEN gp.name LIKE '%%(87.5)%%' THEN 87.5 
                        WHEN gp.name LIKE '%%(99.99)%%' THEN 99.99 
                        WHEN gp.name LIKE '%%(99.9)%%' THEN 99.9 
                        WHEN gp.name LIKE '%%(99.5)%%' THEN 99.5 
                        ELSE 92.0 
                     END) / 100.0)::numeric AS fine_weight,

                    COALESCE(sol.gold_rate, 0)::numeric AS gold_rate,
                    COALESCE(sol.metal_amount, 0)::numeric AS metal_amount,
                    COALESCE(sol.mc_percent_actual, 0)::numeric AS mc_percent_actual,

                    COALESCE(
                        NULLIF(sol.metal_amount * (sol.mc_percent_actual / 100.0), 0),
                        NULLIF(sol.price_subtotal - sol.metal_amount, 0),
                        0
                    )::numeric AS mc_amount_actual,

                    (COALESCE(sol.price_subtotal_actual, 0) - COALESCE(sol.price_subtotal, 0))::numeric AS mc_discount,

                    CASE WHEN lr.rn = 1 THEN COALESCE(id.sale_return_price, 0) ELSE 0 END AS sale_return_price,
                    CASE WHEN lr.rn = 1 THEN COALESCE(ogd.total_old_gold, 0) ELSE 0 END AS old_gold_amount,
                    CASE WHEN lr.rn = 1 THEN COALESCE(pd.bank_amount, 0) ELSE 0 END AS bank_amount,
                    CASE WHEN lr.rn = 1 THEN COALESCE(pd.cash_amount, 0) ELSE 0 END AS cash_amount,
                    CASE WHEN lr.rn = 1 THEN COALESCE(pd.card_amount, 0) ELSE 0 END AS card_amount,
                    CASE WHEN lr.rn = 1 THEN COALESCE(pd.upi_amount, 0) ELSE 0 END AS upi_amount

                FROM sale_order_line sol
                JOIN sale_order so ON sol.order_id = so.id
                JOIN line_rank lr ON lr.id = sol.id
                LEFT JOIN gold_purity gp ON sol.purity_id = gp.id
                LEFT JOIN payment_data pd ON pd.order_id = so.id
                LEFT JOIN invoice_data id ON id.order_id = so.id
                LEFT JOIN old_gold_data ogd ON ogd.sale_id = so.id
                WHERE so.state IN ('sale', 'done')
            );
        """)
