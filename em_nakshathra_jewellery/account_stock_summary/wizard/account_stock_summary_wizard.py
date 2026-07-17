# -*- coding: utf-8 -*-

import io
import base64

import xlsxwriter

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountStockSummaryWizard(models.TransientModel):
    _name = "account.stock.summary.wizard"
    _description = "Account Stock Summary"

    date_from = fields.Date(
        string="Start Date",
        required=True,
    )

    date_to = fields.Date(
        string="End Date",
        required=True,
    )

    branch_ids = fields.Many2many(
        "res.branch",
        "account_stock_summary_branch_rel",
        "wizard_id",
        "branch_id",
        string="Branches",
    )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(
                    _("Start Date should not be greater than End Date.")
                )

    def action_generate_report(self):

        self.ensure_one()

        report_data = self._get_report_data()

        output = self._generate_excel(report_data)

        attachment = self.env["ir.attachment"].create({
            "name": "Account Stock Summary.xlsx",
            "type": "binary",
            "datas": base64.b64encode(output.getvalue()),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })

        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }

    def _get_report_data(self):

        self.ensure_one()

        params = {
            "date_from": self.date_from,
            "date_to": self.date_to,
        }

        purchase_branch_filter = ""
        sale_branch_filter = ""

        if self.branch_ids:
            params["branch_ids"] = self.branch_ids.ids

            purchase_branch_filter = """
                AND po.branch_id = ANY(%(branch_ids)s)
            """

            sale_branch_filter = """
                AND so.branch_id = ANY(%(branch_ids)s)
            """

        sql = f""" WITH stock_movements AS (

    --------------------------------------------------------------------------
    -- PURCHASE RECEIPTS
    --------------------------------------------------------------------------

    SELECT

        sm.date::date                                    AS move_date,

        'IN'                                             AS move_type,

        po.branch_id,

        rb.name                                          AS branch_name,

        sml.product_id,

        pt.name->>'en_US' AS product_name,

        pol.purity_id,

        gp.name                                          AS purity_name,

        sml.quantity                                     AS gross_weight,

        CASE
            WHEN COALESCE(pol.product_qty,0)=0 THEN 0
            ELSE pol.stone_weight * sml.quantity / pol.product_qty
        END                                              AS stone_weight,

        CASE
            WHEN COALESCE(pol.product_qty,0)=0 THEN 0
            ELSE pol.diamond_weight_gm * sml.quantity / pol.product_qty
        END                                              AS diamond_weight,

        CASE
    WHEN COALESCE(pol.product_qty, 0) = 0 THEN 0
    ELSE (
        (pol.product_qty - COALESCE(pol.stone_weight, 0) - COALESCE(pol.diamond_weight_gm, 0))
        * sm.quantity
        / pol.product_qty
    )
END AS net_weight,

        pol.price_unit                                   AS rate,
        

        CASE
    WHEN COALESCE(pol.product_qty,0)=0 THEN 0
    ELSE (
        CASE
            WHEN COALESCE(pol.product_qty,0)=0 THEN 0
            ELSE (
                (pol.product_qty
                 - COALESCE(pol.stone_weight,0)
                 - COALESCE(pol.diamond_weight_gm,0))
                * sm.quantity
                / pol.product_qty
            )
        END
    ) * pol.price_unit
END AS value

    FROM stock_move_line sml

    INNER JOIN stock_move sm
        ON sm.id = sml.move_id

    INNER JOIN stock_picking sp
        ON sp.id = sm.picking_id

    INNER JOIN stock_picking_type spt
        ON spt.id = sp.picking_type_id

    INNER JOIN purchase_order_line pol
        ON pol.id = sm.purchase_line_id

    INNER JOIN purchase_order po
        ON po.id = pol.order_id

    INNER JOIN res_branch rb
        ON rb.id = po.branch_id

    INNER JOIN product_product pp
        ON pp.id = sml.product_id

    INNER JOIN product_template pt
        ON pt.id = pp.product_tmpl_id

    LEFT JOIN gold_purity gp
        ON gp.id = pol.purity_id

    WHERE
        sm.state = 'done'
        AND pt.detailed_type = 'product'
        AND spt.code = 'incoming'
        AND sm.date < (%(date_to)s::date + interval '1 day')

        {purchase_branch_filter}

    UNION ALL
            --------------------------------------------------------------------------
            -- SALES DELIVERY
            --------------------------------------------------------------------------

            SELECT

                sm.date::date                                    AS move_date,

                'OUT'                                            AS move_type,

                so.branch_id,

                rb.name                                          AS branch_name,

                sml.product_id,

                pt.name->>'en_US' AS product_name,

                sol.purity_id,

                gp.name                                          AS purity_name,

                sml.quantity                                     AS gross_weight,

                CASE
                    WHEN COALESCE(sol.product_uom_qty,0)=0 THEN 0
                    ELSE
                        sol.sale_stone_weight
                        * sml.quantity
                        / sol.product_uom_qty
                END                                              AS stone_weight,

                CASE
                    WHEN COALESCE(sol.product_uom_qty,0)=0 THEN 0
                    ELSE
                        sol.sale_diamond_weight_gm
                        * sml.quantity
                        / sol.product_uom_qty
                END                                              AS diamond_weight,

                CASE
    WHEN COALESCE(sol.product_uom_qty, 0) = 0 THEN 0
    ELSE (
        (sol.product_uom_qty - COALESCE(sol.sale_stone_weight, 0) - COALESCE(sol.sale_diamond_weight_gm, 0))
        * sm.quantity
        / sol.product_uom_qty
        )
    END AS net_weight,

                sol.price_unit                                   AS rate,

                CASE
    WHEN COALESCE(sol.product_uom_qty,0)=0 THEN 0
    ELSE (
        (
            (sol.product_uom_qty
             - COALESCE(sol.sale_stone_weight,0)
             - COALESCE(sol.sale_diamond_weight_gm,0))
            * sm.quantity
            / sol.product_uom_qty
        ) * sol.price_unit
    )
    END AS value

            FROM stock_move_line sml

            INNER JOIN stock_move sm
                ON sm.id = sml.move_id

            INNER JOIN stock_picking sp
                ON sp.id = sm.picking_id

            INNER JOIN stock_picking_type spt
                ON spt.id = sp.picking_type_id

            INNER JOIN sale_order_line sol
                ON sol.id = sm.sale_line_id

            INNER JOIN sale_order so
                ON so.id = sol.order_id

            INNER JOIN res_branch rb
                ON rb.id = so.branch_id

            INNER JOIN product_product pp
                ON pp.id = sml.product_id

            INNER JOIN product_template pt
                ON pt.id = pp.product_tmpl_id

            LEFT JOIN gold_purity gp
                ON gp.id = sol.purity_id

            WHERE
                sm.state = 'done'
                AND pt.detailed_type = 'product'
                AND spt.code = 'outgoing'
                AND sm.date < (%(date_to)s::date + interval '1 day')

                {sale_branch_filter}

        ), purchase_average AS (

    SELECT
        branch_id,
        product_id,
        purity_id,

        SUM(net_weight) AS purchased_net,

        SUM(net_weight * rate) AS purchased_value,

        CASE
            WHEN SUM(net_weight) = 0 THEN 0
            ELSE ROUND(
                SUM(net_weight * rate) / SUM(net_weight),
                2
            )
        END AS avg_rate

    FROM stock_movements

    WHERE move_type = 'IN'

    GROUP BY
        branch_id,
        product_id,
        purity_id
),
        report_data AS (


        SELECT

    branch_id,
    branch_name,
    
    product_id,
    product_name,
    
    purity_id,
    purity_name,

        ------------------------------------------------------------------
        -- OPENING
        ------------------------------------------------------------------

        SUM(
            CASE
                WHEN move_date < %(date_from)s
                     AND move_type='IN'
                THEN gross_weight
                WHEN move_date < %(date_from)s
                     AND move_type='OUT'
                THEN -gross_weight
                ELSE 0
            END
        ) AS opening_gross,

        SUM(
            CASE
                WHEN move_date < %(date_from)s
                     AND move_type='IN'
                THEN stone_weight
                WHEN move_date < %(date_from)s
                     AND move_type='OUT'
                THEN -stone_weight
                ELSE 0
            END
        ) AS opening_stone,

        SUM(
            CASE
                WHEN move_date < %(date_from)s
                     AND move_type='IN'
                THEN diamond_weight
                WHEN move_date < %(date_from)s
                     AND move_type='OUT'
                THEN -diamond_weight
                ELSE 0
            END
        ) AS opening_diamond,

        SUM(
            CASE
                WHEN move_date < %(date_from)s
                     AND move_type='IN'
                THEN net_weight
                WHEN move_date < %(date_from)s
                     AND move_type='OUT'
                THEN -net_weight
                ELSE 0
            END
        ) AS opening_net,

        SUM(
            CASE
                WHEN move_date < %(date_from)s
                     AND move_type='IN'
                THEN value
                WHEN move_date < %(date_from)s
                     AND move_type='OUT'
                THEN -value
                ELSE 0
            END
        ) AS opening_value,

        ------------------------------------------------------------------
        -- STOCK IN
        ------------------------------------------------------------------

        SUM(
            CASE
                WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                     AND move_type='IN'
                THEN gross_weight
                ELSE 0
            END
        ) AS in_gross,

        SUM(
            CASE
                WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                     AND move_type='IN'
                THEN stone_weight
                ELSE 0
            END
        ) AS in_stone,

        SUM(
            CASE
                WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                     AND move_type='IN'
                THEN diamond_weight
                ELSE 0
            END
        ) AS in_diamond,

        SUM(
            CASE
                WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                     AND move_type='IN'
                THEN net_weight
                ELSE 0
            END
        ) AS in_net,

        SUM(
            CASE
                WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                     AND move_type='IN'
                THEN value
                ELSE 0
            END
        ) AS in_value,

        ------------------------------------------------------------------
        -- STOCK OUT
        ------------------------------------------------------------------

        SUM(
            CASE
                WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                     AND move_type='OUT'
                THEN gross_weight
                ELSE 0
            END
        ) AS out_gross,

        SUM(
            CASE
                WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                     AND move_type='OUT'
                THEN stone_weight
                ELSE 0
            END
        ) AS out_stone,

        SUM(
            CASE
                WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                     AND move_type='OUT'
                THEN diamond_weight
                ELSE 0
            END
        ) AS out_diamond,

        SUM(
    CASE
        WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
             AND move_type='OUT'
        THEN net_weight
        ELSE 0
        END
    ) AS out_net,
    
    MAX(
        CASE
            WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                 AND move_type='OUT'
            THEN rate
        END
    ) AS out_rate,
    
    SUM(
        CASE
            WHEN move_date BETWEEN %(date_from)s AND %(date_to)s
                 AND move_type='OUT'
            THEN value
            ELSE 0
        END
    ) AS out_value

    FROM stock_movements

    GROUP BY
    branch_id,
    branch_name,
    product_id,
    product_name,
    purity_id,
    purity_name

)

SELECT

    rd.branch_id,
rd.branch_name,

rd.product_id,
rd.product_name,

rd.purity_id,
rd.purity_name,

    ------------------------------------------------------------
    -- Opening
    ------------------------------------------------------------

    rd.opening_gross,
rd.opening_stone,
rd.opening_diamond,
rd.opening_net,

    COALESCE(ROUND(pa.avg_rate,2),0) AS opening_rate,

    ROUND(rd.opening_net * COALESCE(pa.avg_rate,0),2) AS opening_value,
    ------------------------------------------------------------
    -- Stock In
    ------------------------------------------------------------

    rd.in_gross,
    rd.in_stone,
    rd.in_diamond,
    rd.in_net,

    COALESCE(ROUND(pa.avg_rate,2),0) AS in_rate,

    ROUND(rd.in_net * COALESCE(pa.avg_rate,0),2) AS in_value,
    ------------------------------------------------------------
    -- Stock Out
    ------------------------------------------------------------

    rd.out_gross,
    rd.out_stone,
    rd.out_diamond,
    rd.out_net,

    
    rd.out_rate,
    rd.out_value,
    
    ------------------------------------------------------------
    -- Closing
    ------------------------------------------------------------

    (rd.opening_gross + rd.in_gross - rd.out_gross) AS closing_gross,
    (rd.opening_stone + rd.in_stone - rd.out_stone)      AS closing_stone,

    (rd.opening_diamond + rd.in_diamond - rd.out_diamond) AS closing_diamond,

    (rd.opening_net + rd.in_net - rd.out_net)            AS closing_net,

    COALESCE(ROUND(pa.avg_rate,2),0) AS closing_rate,

            ROUND(
        (rd.opening_net + rd.in_net - rd.out_net)
        * COALESCE(pa.avg_rate,0),
        2
    ) AS closing_value
        
        FROM report_data rd
        
        LEFT JOIN purchase_average pa
        ON pa.branch_id = rd.branch_id
        AND pa.product_id = rd.product_id
        AND COALESCE(pa.purity_id,0)=COALESCE(rd.purity_id,0)
                
        ORDER BY
        
            branch_name,
            product_name,
            purity_name
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def _generate_excel(self, report_data):
        """
        Generate Excel Report
        """

        output = io.BytesIO()

        workbook = xlsxwriter.Workbook(output, {
            "in_memory": True,
        })

        worksheet = workbook.add_worksheet("Stock Summary")

        formats = self._get_formats(workbook)

        self._write_title(
            worksheet,
            formats,
        )

        start_row = self._write_headers(
            worksheet,
            formats,
        )

        last_row = self._write_data(
            worksheet,
            report_data,
            start_row,
            formats,
        )

        self._write_totals(
            worksheet,
            start_row,
            last_row,
            formats,
        )

        self._auto_fit_columns(worksheet)

        workbook.close()

        output.seek(0)

        return output

    def _get_formats(self, workbook):

        return {

            "title": workbook.add_format({
                "bold": True,
                "font_size": 16,
                "align": "center",
                "valign": "vcenter",
            }),

            "header": workbook.add_format({
                "bold": True,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "bg_color": "#D9EAD3",
            }),

            "text": workbook.add_format({
                "border": 1,
            }),

            "number": workbook.add_format({
                "border": 1,
                "num_format": "#,##0.000",
            }),

            "money": workbook.add_format({
                "border": 1,
                "num_format": "#,##0.00",
            }),

            "total": workbook.add_format({
                "bold": True,
                "border": 1,
                "bg_color": "#FFF2CC",
                "num_format": "#,##0.000",
            }),

            "total_money": workbook.add_format({
                "bold": True,
                "border": 1,
                "bg_color": "#FFF2CC",
                "num_format": "#,##0.00",
            }),

        }

    def _write_title(self, worksheet, formats):

        worksheet.merge_range(
            0,
            0,
            0,
            26,
            "Consolidated Stock Summary for Accounting",
            formats["title"],
        )

        worksheet.write(2, 0, "Date From", formats["header"])
        worksheet.write(2, 1, str(self.date_from))

        worksheet.write(2, 3, "Date To", formats["header"])
        worksheet.write(2, 4, str(self.date_to))

        worksheet.write(3, 0, "Branches", formats["header"])

        if self.branch_ids:
            worksheet.write(
                3,
                1,
                ", ".join(self.branch_ids.mapped("name")),
            )
        else:
            worksheet.write(
                3,
                1,
                "All Branches",
            )

    def _write_headers(self, worksheet, formats):

        row = 5

        worksheet.merge_range(row, 3, row, 8, "Opening", formats["header"])
        worksheet.merge_range(row, 9, row, 14, "Stock In", formats["header"])
        worksheet.merge_range(row, 15, row, 20, "Stock Out", formats["header"])
        worksheet.merge_range(row, 21, row, 26, "Closing", formats["header"])

        row += 1

        worksheet.write(row, 0, "Branch", formats["header"])
        worksheet.write(row, 1, "Product", formats["header"])
        worksheet.write(row, 2, "Caret", formats["header"])

        columns = [
            "Gross Wt (Grms)",
            "Stone Wt (Gms)",
            "Diamond Wt (CT)",
            "Net Wt (Gms)",
            "Unit Price",
            "Value",
        ]

        col = 3

        for _ in range(4):
            for column in columns:
                worksheet.write(
                    row,
                    col,
                    column,
                    formats["header"],
                )
                col += 1

        return row + 1

    def _write_data(
            self,
            worksheet,
            report_data,
            start_row,
            formats,
    ):

        row = start_row

        for rec in report_data:

            worksheet.write(
                row,
                0,
                rec.get("branch_name") or "",
                formats["text"],
            )

            worksheet.write(
                row,
                1,
                rec.get("product_name") or "",
                formats["text"],
            )

            worksheet.write(
                row,
                2,
                rec.get("purity_name") or "",
                formats["text"],
            )

            values = [

                # Opening
                rec.get("opening_gross", 0.0),
                rec.get("opening_stone", 0.0),
                rec.get("opening_diamond", 0.0),
                rec.get("opening_net", 0.0),
                rec.get("opening_rate", 0.0),
                rec.get("opening_value", 0.0),

                # Stock In
                rec.get("in_gross", 0.0),
                rec.get("in_stone", 0.0),
                rec.get("in_diamond", 0.0),
                rec.get("in_net", 0.0),
                rec.get("in_rate", 0.0),
                rec.get("in_value", 0.0),

                # Stock Out
                rec.get("out_gross", 0.0),
                rec.get("out_stone", 0.0),
                rec.get("out_diamond", 0.0),
                rec.get("out_net", 0.0),
                rec.get("out_rate", 0.0),
                rec.get("out_value", 0.0),

                # Closing
                rec.get("closing_gross", 0.0),
                rec.get("closing_stone", 0.0),
                rec.get("closing_diamond", 0.0),
                rec.get("closing_net", 0.0),
                rec.get("closing_rate", 0.0),
                rec.get("closing_value", 0.0),

            ]

            col = 3

            for idx, value in enumerate(values):
                fmt = formats["money"] if idx in (5, 11, 17, 23) else formats["number"]

                worksheet.write_number(
                    row,
                    col,
                    float(value or 0.0),
                    fmt,
                )

                col += 1

            row += 1

        return row

    def _write_totals(
            self,
            worksheet,
            start_row,
            end_row,
            formats,
    ):

        worksheet.write(
            end_row,
            0,
            "TOTAL",
            formats["header"],
        )

        for col in range(3, 27):
            column = xlsxwriter.utility.xl_col_to_name(col)

            fmt = (
                formats["total_money"]
                if col in (8, 14, 20, 26)
                else formats["total"]
            )

            worksheet.write_formula(
                end_row,
                col,
                f"=SUM({column}{start_row + 1}:{column}{end_row})",
                fmt,
            )

    def _auto_fit_columns(self, worksheet):

        worksheet.set_column(0, 0, 22)
        worksheet.set_column(1, 1, 35)
        worksheet.set_column(2, 2, 15)
        worksheet.set_column(3, 26, 14)
