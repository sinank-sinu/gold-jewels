# -*- coding: utf-8 -*-
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _


class JwBusinessDashboard(models.Model):
    _name = 'jw.business.dashboard'
    _description = 'JW Business Dashboard'

    # ─────────────────────────────────────────────────────────────────────────
    # Helper
    # ─────────────────────────────────────────────────────────────────────────
    def _date_range(self, period):
        today = date.today()
        if period == 'today':
            return today, today
        elif period == 'this_week':
            start = today - timedelta(days=today.weekday())
            return start, today
        elif period == 'this_month':
            return today.replace(day=1), today
        elif period == 'last_month':
            first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            last = today.replace(day=1) - timedelta(days=1)
            return first, last
        elif period == 'this_year':
            return today.replace(month=1, day=1), today
        elif period == 'last_6_months':
            return today - relativedelta(months=6), today
        else:
            return today.replace(month=1, day=1), today

    # ─────────────────────────────────────────────────────────────────────────
    # Main dashboard data entry point
    # ─────────────────────────────────────────────────────────────────────────

    def _has_essl_column(self):
        """Return True if hr_employee.essl_location_id column exists in this DB."""
        cr = self._cr
        cr.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='hr_employee' AND column_name='essl_location_id'
            )
        """)
        return bool(cr.fetchone()[0])

    @staticmethod
    def _emp_branch_sql(essl_exists, emp_alias='e', user_alias='u', loc_alias='sl'):
        """Return the COALESCE SQL fragment for resolving an employee branch.
        Omits essl_location_id when that column does not exist."""
        if essl_exists:
            return (f"COALESCE({emp_alias}.essl_location_id,"
                    f" {user_alias}.branch_id, {loc_alias}.branch_id)")
        return f"COALESCE({user_alias}.branch_id, {loc_alias}.branch_id)"

    @api.model
    def get_dashboard_data(self, period='this_month', date_from=None, date_to=None, branch_id=None):
        cr = self._cr

        # Detect optional custom column once per RPC call
        essl = self._has_essl_column()

        # Fetch branch list if table exists
        branches = []
        cr.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'res_branch')")
        if cr.fetchone()[0]:
            cr.execute("SELECT id, name FROM res_branch ORDER BY name")
            branches = [{'id': r[0], 'name': r[1]} for r in cr.fetchall()]

        # Parse branch_id
        b_id = int(branch_id) if (branch_id and str(branch_id).isdigit()) else None

        if date_from and date_to:
            try:
                d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                d_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            except Exception:
                d_from, d_to = self._date_range(period)
        else:
            d_from, d_to = self._date_range(period)

        return {
            'kpis': self._get_kpis(d_from, d_to, b_id, essl),
            'sales_monthly': self._get_sales_monthly(d_from, d_to, b_id),
            'purchase_monthly': self._get_purchase_monthly(d_from, d_to, b_id),
            'expense_monthly': self._get_expense_monthly(b_id, essl),
            'inventory_category': self._get_inventory_by_category(b_id),
            'product_category': self._get_product_category_distribution(b_id),
            'jewellery_purity': self._get_jewellery_purity_breakdown(b_id),
            'top_products': self._get_top_selling_products(d_from, d_to, b_id),
            'sales_by_salesman': self._get_sales_by_salesman(d_from, d_to, b_id),
            'date_branch_collection': self._get_date_branch_collection(d_from, d_to, b_id),
            'branch_wise_target': self._get_branch_wise_target(d_from, d_to, b_id),
            'top_sale_orders': self._get_top_sale_orders(d_from, d_to, b_id),
            'invoiced_kpis': self._get_invoiced_kpis(d_from, d_to, b_id),
            'invoiced_monthly': self._get_invoiced_monthly(d_from, d_to, b_id),
            'invoiced_top_invoices': self._get_invoiced_top_invoices(d_from, d_to, b_id),
            'invoiced_top_categories': self._get_invoiced_top_categories(d_from, d_to, b_id),
            'invoiced_top_salespeople': self._get_invoiced_top_salespeople(d_from, d_to, b_id),
            'top_quotations': self._get_top_quotations(d_from, d_to, b_id),
            'sales_state_distribution': self._get_sales_state_distribution(d_from, d_to, b_id),
            'stock_balance_products': self._get_top_products_stock_balance(b_id),
            'sales_by_branch': self._get_sales_by_branch(d_from, d_to),
            'top_rfqs': self._get_top_rfqs(d_from, d_to, b_id),
            'top_purchase_orders': self._get_top_purchase_orders(d_from, d_to, b_id),
            'top_vendors': self._get_top_vendors(d_from, d_to, b_id),
            'top_buyers': self._get_top_buyers(d_from, d_to, b_id),
            'least_purchase_orders': self._get_least_purchase_orders(d_from, d_to, b_id),
            'least_vendors': self._get_least_vendors(d_from, d_to, b_id),
            'best_sellers_by_revenue': self._get_top_selling_products(d_from, d_to, b_id),
            'best_sellers_by_qty': self._get_best_sellers_by_qty(d_from, d_to, b_id),
            'best_selling_categories': self._get_best_selling_categories(d_from, d_to, b_id),
            'stock_by_location': self._get_stock_by_location(b_id),
            'top_expenses': self._get_top_expenses(d_from, d_to, b_id, essl),
            'top_expense_categories': self._get_top_expense_categories(d_from, d_to, b_id, essl),
            'top_expense_employees': self._get_top_expense_employees(d_from, d_to, b_id, essl),
            'expense_bullet_data': self._get_expense_bullet_data(d_from, d_to, b_id, essl),
            'schemes_kpis': self._get_schemes_kpis(d_from, d_to, b_id),
            'schemes_monthly_trend': self._get_schemes_monthly_trend(d_from, d_to, b_id),
            'schemes_running': self._get_schemes_by_state('running', d_from, d_to, b_id),
            'schemes_completed': self._get_schemes_by_state('completed', d_from, d_to, b_id),
            'schemes_redeemed': self._get_schemes_by_state('redeemed', d_from, d_to, b_id),
            'employee_data': self._get_employee_attendance_data(d_from, d_to, b_id),

            'period': {'from': str(d_from), 'to': str(d_to)},
            'branches': branches,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # KPIs
    # ─────────────────────────────────────────────────────────────────────────
    def _get_kpis(self, d_from, d_to, branch_id=None, essl=True):
        cr = self._cr

        # Sales revenue
        q = """
            SELECT COALESCE(SUM(amount_total), 0)
            FROM sale_order
            WHERE state IN ('sale','done')
              AND date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        sale_revenue = cr.fetchone()[0] or 0.0

        # Sales weight
        q = """
            SELECT COALESCE(SUM(sol.product_uom_qty), 0)
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        sale_weight = cr.fetchone()[0] or 0.0

        # Sales count
        q = """
            SELECT COUNT(id) FROM sale_order
            WHERE state IN ('sale','done')
              AND date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        sale_count = cr.fetchone()[0] or 0

        # Quotation count
        q = """
            SELECT COUNT(id) FROM sale_order
            WHERE state IN ('draft','sent')
              AND date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        quotation_count = cr.fetchone()[0] or 0

        # Quotation total
        q = """
            SELECT COALESCE(SUM(amount_total), 0)
            FROM sale_order
            WHERE state IN ('draft','sent')
              AND date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        quotation_total = cr.fetchone()[0] or 0.0

        # Quotation weight
        q = """
            SELECT COALESCE(SUM(sol.product_uom_qty), 0)
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            WHERE so.state IN ('draft','sent')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        quotation_weight = cr.fetchone()[0] or 0.0

        # Purchase total
        q = """
            SELECT COALESCE(SUM(amount_total), 0)
            FROM purchase_order
            WHERE state IN ('purchase','done')
              AND date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        purchase_total = cr.fetchone()[0] or 0.0

        # Purchase total weight
        q = """
            SELECT COALESCE(SUM(pol.product_qty), 0)
            FROM purchase_order_line pol
            JOIN purchase_order po ON po.id = pol.order_id
            WHERE po.state IN ('purchase','done')
              AND po.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND po.branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        purchase_total_weight = cr.fetchone()[0] or 0.0

        # Purchase count
        q = """
            SELECT COUNT(id) FROM purchase_order
            WHERE state IN ('purchase','done')
              AND date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        purchase_count = cr.fetchone()[0] or 0

        # Total products
        q = "SELECT COUNT(id) FROM product_template WHERE active=TRUE"
        params = []
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        product_count = cr.fetchone()[0] or 0

        # Stock value
        q = """
            SELECT COALESCE(SUM(sq.quantity * COALESCE(ip.value_float, 0)), 0)
            FROM stock_quant sq
            JOIN product_product pp ON pp.id = sq.product_id
            JOIN stock_location sl ON sl.id = sq.location_id
            LEFT JOIN (
                SELECT DISTINCT ON (res_id) res_id, value_float
                FROM ir_property
                WHERE name = 'standard_price'
                  AND (company_id = %s OR company_id IS NULL)
                ORDER BY res_id, company_id DESC NULLS LAST
            ) ip ON ip.res_id = 'product.product,' || pp.id
            WHERE sl.usage = 'internal'
        """
        params = [self.env.company.id]
        if branch_id:
            q += " AND sl.branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        stock_value = cr.fetchone()[0] or 0.0

        # Stock qty
        q = """
            SELECT COALESCE(SUM(sq.quantity), 0)
            FROM stock_quant sq
            JOIN stock_location sl ON sl.id = sq.location_id
            WHERE sl.usage = 'internal'
        """
        params = []
        if branch_id:
            q += " AND sl.branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        stock_qty = cr.fetchone()[0] or 0.0

        # Expense total
        q = """
            SELECT COALESCE(SUM(hes.total_amount), 0)
            FROM hr_expense_sheet hes
            LEFT JOIN hr_employee emp ON emp.id = hes.employee_id
            LEFT JOIN res_users u ON u.id = emp.user_id
            LEFT JOIN stock_location sl ON sl.id = emp.label_location_id
            WHERE hes.state IN ('post','done')
              AND hes.accounting_date BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += f" AND {self._emp_branch_sql(essl, 'emp', 'u', 'sl')} = %s"
            params.append(branch_id)
        cr.execute(q, params)
        expense_total = cr.fetchone()[0] or 0.0

        # Jewellery items (purity-classified products)
        jewellery_count = 0
        cr.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'gold_purity')")
        if cr.fetchone()[0]:
            q = """
                SELECT COUNT(DISTINCT pt.id)
                FROM product_template pt
                JOIN gold_purity p ON p.id = pt.purity_id
                WHERE pt.active = TRUE
            """
            params = []
            if branch_id:
                q += " AND pt.branch_id = %s"
                params.append(branch_id)
            cr.execute(q, params)
            row = cr.fetchone()
            jewellery_count = row[0] if row else 0

        # Customers
        q = """
            SELECT COUNT(DISTINCT partner_id) FROM sale_order
            WHERE state IN ('sale','done')
              AND date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        customer_count = cr.fetchone()[0] or 0

        net_profit = sale_revenue - purchase_total - expense_total
        return {
            'sale_revenue': round(float(sale_revenue), 2),
            'sale_weight': round(float(sale_weight), 2),
            'sale_count': int(sale_count),
            'quotation_count': int(quotation_count),
            'quotation_total': round(float(quotation_total), 2),
            'quotation_weight': round(float(quotation_weight), 2),
            'purchase_total': round(float(purchase_total), 2),
            'purchase_total_weight': round(float(purchase_total_weight), 2),
            'purchase_count': int(purchase_count),
            'product_count': int(product_count),
            'stock_value': round(float(stock_value), 2),
            'stock_qty': round(float(stock_qty), 2),
            'expense_total': round(float(expense_total), 2),
            'jewellery_count': int(jewellery_count),
            'customer_count': int(customer_count),
            'net_profit': round(float(net_profit), 2),
            'purchase_average': round(float(purchase_total / purchase_count if purchase_count > 0 else 0.0), 2),
            'purchase_average_weight': round(float(purchase_total_weight / purchase_count if purchase_count > 0 else 0.0), 2),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Monthly Sales (12 months) – Line Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_sales_monthly(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                to_char(so.date_order, 'Mon YYYY') AS month,
                date_trunc('month', so.date_order) AS month_start,
                COALESCE(SUM(sol.product_uom_qty), 0) AS revenue,
                COUNT(DISTINCT so.id) AS orders
            FROM sale_order so
            LEFT JOIN sale_order_line sol ON sol.order_id = so.id
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY month, month_start ORDER BY month_start"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'month': r[0], 'revenue': round(float(r[2]), 3), 'orders': int(r[3])} for r in rows]

    # ─────────────────────────────────────────────────────────────────────────
    # Monthly Purchase (12 months) – Bar Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_purchase_monthly(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                to_char(po.date_order, 'Mon YYYY') AS month,
                date_trunc('month', po.date_order) AS month_start,
                COALESCE(SUM(pol.product_qty), 0) AS total,
                COUNT(DISTINCT po.id) AS orders
            FROM purchase_order po
            LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
            WHERE po.state IN ('purchase','done')
              AND po.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND po.branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY month, month_start ORDER BY month_start"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'month': r[0], 'total': round(float(r[2]), 3), 'orders': int(r[3])} for r in rows]


    # ─────────────────────────────────────────────────────────────────────────
    # Monthly Expense (12 months) – Bar Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_expense_monthly(self, branch_id=None, essl=True):
        cr = self._cr
        q = """
            SELECT
                to_char(hes.accounting_date, 'Mon YYYY') AS month,
                date_trunc('month', hes.accounting_date) AS month_start,
                COALESCE(SUM(hes.total_amount), 0) AS total
            FROM hr_expense_sheet hes
            LEFT JOIN hr_employee emp ON emp.id = hes.employee_id
            LEFT JOIN res_users u ON u.id = emp.user_id
            LEFT JOIN stock_location sl ON sl.id = emp.label_location_id
            WHERE hes.state IN ('post','done')
              AND hes.accounting_date >= NOW() - INTERVAL '12 months'
        """
        params = []
        if branch_id:
            q += f" AND {self._emp_branch_sql(essl, 'emp', 'u', 'sl')} = %s"
            params.append(branch_id)
        q += " GROUP BY month, month_start ORDER BY month_start"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'month': r[0], 'total': round(float(r[2]), 2)} for r in rows]

    # ─────────────────────────────────────────────────────────────────────────
    # Expense Analysis Methods
    # ─────────────────────────────────────────────────────────────────────────
    def _get_top_expenses(self, d_from, d_to, branch_id=None, essl=True):
        cr = self._cr
        q = """
            SELECT 
                he.id AS expense_id,
                he.name AS expense_name,
                COALESCE(pt.name->>'en_US', pt.name->>'en_US') AS category_name,
                emp.name AS employee_name,
                he.total_amount,
                he.date
            FROM hr_expense he
            JOIN hr_employee emp ON emp.id = he.employee_id
            LEFT JOIN res_users u ON u.id = emp.user_id
            LEFT JOIN stock_location sl ON sl.id = emp.label_location_id
            LEFT JOIN product_product pp ON pp.id = he.product_id
            LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE he.state IN ('reported', 'approved', 'done')
              AND he.date BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += f" AND {self._emp_branch_sql(essl, 'emp', 'u', 'sl')} = %s"
            params.append(branch_id)
        q += " ORDER BY he.total_amount DESC LIMIT 10"
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            cat_name = r[2]
            if isinstance(cat_name, dict):
                cat_name = list(cat_name.values())[0] if cat_name else 'Other'
            result.append({
                'id': int(r[0]),
                'name': r[1],
                'category': str(cat_name or 'Other'),
                'employee': r[3],
                'amount': round(float(r[4] or 0.0), 2),
                'date': str(r[5]) if r[5] else ''
            })
        return result

    def _get_top_expense_categories(self, d_from, d_to, branch_id=None, essl=True):
        cr = self._cr
        q = """
            SELECT 
                pt.id AS category_id,
                COALESCE(pt.name->>'en_US', pt.name->>'en_US') AS category_name,
                SUM(he.total_amount) AS total_amount,
                COUNT(he.id) AS expense_count
            FROM hr_expense he
            LEFT JOIN product_product pp ON pp.id = he.product_id
            LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN hr_employee emp ON emp.id = he.employee_id
            LEFT JOIN res_users u ON u.id = emp.user_id
            LEFT JOIN stock_location sl ON sl.id = emp.label_location_id
            WHERE he.state IN ('reported', 'approved', 'done')
              AND he.date BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += f" AND {self._emp_branch_sql(essl, 'emp', 'u', 'sl')} = %s"
            params.append(branch_id)
        q += " GROUP BY pt.id, pt.name ORDER BY total_amount DESC"
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[1]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Other'
            result.append({
                'id': int(r[0]) if r[0] else None,
                'category': str(name or 'Other'),
                'amount': round(float(r[2]), 3),
                'count': int(r[3])
            })
        return result

    def _get_top_expense_employees(self, d_from, d_to, branch_id=None, essl=True):
        cr = self._cr
        q = """
            SELECT 
                emp.id AS employee_id,
                emp.name AS employee_name,
                SUM(he.total_amount) AS total_amount,
                COUNT(he.id) AS expense_count
            FROM hr_expense he
            JOIN hr_employee emp ON emp.id = he.employee_id
            LEFT JOIN res_users u ON u.id = emp.user_id
            LEFT JOIN stock_location sl ON sl.id = emp.label_location_id
            WHERE he.state IN ('reported', 'approved', 'done')
              AND he.date BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += f" AND {self._emp_branch_sql(essl, 'emp', 'u', 'sl')} = %s"
            params.append(branch_id)
        q += " GROUP BY emp.id, emp.name ORDER BY total_amount DESC"
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            result.append({
                'id': int(r[0]),
                'employee': r[1],
                'amount': round(float(r[2]), 3),
                'count': int(r[3])
            })
        return result

    def _get_expense_bullet_data(self, d_from, d_to, branch_id=None, essl=True):
        categories = self._get_top_expense_categories(d_from, d_to, branch_id, essl)
        result = []
        for c in categories:
            cat = c['category']
            amt = c['amount']
            # Determine target dynamically based on category name
            target = 3000.0
            cat_lower = cat.lower()
            if 'travel' in cat_lower or 'car' in cat_lower or 'air' in cat_lower:
                target = 5000.0
            elif 'hotel' in cat_lower or 'lodging' in cat_lower or 'stay' in cat_lower:
                target = 8000.0
            elif 'lunch' in cat_lower or 'meal' in cat_lower or 'food' in cat_lower or 'pizza' in cat_lower or 'drink' in cat_lower:
                target = 2000.0
            
            result.append({
                'category': cat,
                'actual': amt,
                'target': target,
                'range_low': round(target * 0.5, 2),
                'range_med': round(target * 0.85, 2),
                'range_high': target
            })
        return result


    # ─────────────────────────────────────────────────────────────────────────
    # Inventory by Category – Pie Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_inventory_by_category(self, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                COALESCE(p.name, 'Unknown') AS purity,
                COALESCE(SUM(sq.quantity), 0) AS qty
            FROM stock_quant sq
            JOIN product_product pp ON pp.id = sq.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN stock_location sl ON sl.id = sq.location_id
            LEFT JOIN gold_purity p ON p.id = pt.purity_id
            WHERE sl.usage = 'internal'
        """
        params = []
        if branch_id:
            q += " AND sl.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY p.name
            ORDER BY qty DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            label = r[0]
            if isinstance(label, dict):
                label = list(label.values())[0] if label else 'Unknown'
            result.append({
                'label': str(label or 'Unknown'),
                'value': round(float(r[1]), 3)
            })
        return result


    # ─────────────────────────────────────────────────────────────────────────
    # Product Category Distribution – Doughnut
    # ─────────────────────────────────────────────────────────────────────────
    def _get_product_category_distribution(self, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                COALESCE(pc.complete_name, 'Uncategorized') AS category,
                COALESCE(SUM(pl.sale_gross_weight), 0) AS total_gross_weight
            FROM product_label pl
            JOIN product_product pp ON pp.id = pl.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            WHERE pt.active = TRUE
        """
        params = []
        if branch_id:
            q += " AND pl.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY pc.complete_name
            ORDER BY total_gross_weight DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'label': r[0], 'value': round(float(r[1]), 3)} for r in rows]

    # ─────────────────────────────────────────────────────────────────────────
    # Jewellery Purity Breakdown – Pie Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_jewellery_purity_breakdown(self, branch_id=None):
        cr = self._cr
        cr.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'gold_purity')")
        if not cr.fetchone()[0]:
            return []
        try:
            q = """
                SELECT
                    COALESCE(p.name, 'Unknown') AS purity,
                    COUNT(DISTINCT pt.id) AS product_count,
                    COALESCE(SUM(sq.quantity), 0) AS qty,
                    COALESCE(SUM(sq.quantity * COALESCE(ip.value_float, 0)), 0) AS value
                FROM product_template pt
                JOIN gold_purity p ON p.id = pt.purity_id
                JOIN product_product pp2 ON pp2.product_tmpl_id = pt.id
                LEFT JOIN stock_quant sq ON sq.product_id = pp2.id
                    AND sq.location_id IN (
                        SELECT id FROM stock_location WHERE usage = 'internal'
                    )
                LEFT JOIN (
                    SELECT DISTINCT ON (res_id) res_id, value_float
                    FROM ir_property
                    WHERE name = 'standard_price'
                      AND (company_id = %s OR company_id IS NULL)
                    ORDER BY res_id, company_id DESC NULLS LAST
                ) ip ON ip.res_id = 'product.product,' || pp2.id
                WHERE pt.active = TRUE
            """
            params = [self.env.company.id]
            if branch_id:
                q += " AND pt.branch_id = %s"
                params.append(branch_id)
            q += """
                GROUP BY p.name
                ORDER BY qty DESC
            """
            cr.execute(q, params)
            rows = cr.fetchall()
            result = []
            for r in rows:
                label = r[0]
                if isinstance(label, dict):
                    label = list(label.values())[0] if label else 'Unknown'
                result.append({
                    'label': str(label),
                    'product_count': int(r[1]),
                    'qty': round(float(r[2]), 3),
                    'value': round(float(r[3]), 2),
                })
            return result
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # Top Selling Products – Table
    # ─────────────────────────────────────────────────────────────────────────
    def _get_top_selling_products(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                pt.id AS pt_id,
                pt.name AS product_name,
                COALESCE(SUM(sol.product_uom_qty), 0) AS qty_sold,
                COALESCE(SUM(sol.price_subtotal), 0) AS revenue
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            JOIN product_product pp ON pp.id = sol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY pt.id, pt.name
            ORDER BY qty_sold DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[1]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Product'
            result.append({
                'id': int(r[0]),
                'name': str(name),
                'qty': round(float(r[2]), 3),
                'revenue': round(float(r[3]), 2),
            })
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Sales by Salesman – Bar Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_sales_by_salesman(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                COALESCE(rp.name, 'Unknown') AS salesman,
                COALESCE(SUM(sol.product_uom_qty), 0) AS revenue,
                COUNT(DISTINCT so.id) AS orders,
                ru.id AS user_id
            FROM sale_order so
            JOIN sale_order_line sol ON sol.order_id = so.id
            JOIN res_users ru ON ru.id = so.user_id
            JOIN res_partner rp ON rp.id = ru.partner_id
            LEFT JOIN gold_purity gp ON gp.id = sol.purity_id
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
              AND UPPER(TRIM(gp.name)) IN ('22K', '18CT', '22KT')
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY rp.name, ru.id
            ORDER BY revenue DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[0]
            user_id = r[3]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Unknown'
            
            # Fetch target for this user in the period
            target_q = """
                SELECT COALESCE(SUM(target_gms_22k + target_gms_18ct + target_gms_22kt), 0)
                FROM salesman_target
                WHERE salesman_id = %s
                  AND (date_from <= %s AND date_to >= %s)
            """
            target_params = [user_id, d_to, d_from]
            if branch_id:
                target_q += " AND branch_id = %s"
                target_params.append(branch_id)
            cr.execute(target_q, target_params)
            target_val = cr.fetchone()
            target_amount = float(target_val[0]) if target_val else 0.0

            result.append({
                'salesman': str(name),
                'revenue': round(float(r[1]), 3),
                'orders': int(r[2]),
                'target': round(target_amount, 3),
            })
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Sales by Sales Team – Pie Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_sales_by_team(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                COALESCE(ct.name->>'en_US', 'No Sales Team') AS team_name,
                COALESCE(SUM(so.amount_total), 0) AS revenue
            FROM sale_order so
            LEFT JOIN crm_team ct ON ct.id = so.team_id
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY ct.name->>'en_US'
            ORDER BY revenue DESC
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[0]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'No Sales Team'
            result.append({
                'label': str(name),
                'value': round(float(r[1]), 2),
            })
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Top Sale Orders – Table
    # ─────────────────────────────────────────────────────────────────────────
    def _get_top_sale_orders(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                so.id AS id,
                so.name AS ref,
                rp.name AS customer,
                so.date_order::DATE AS date,
                so.state AS state,
                COALESCE(SUM(sol.product_uom_qty), 0) AS total_weight
            FROM sale_order so
            JOIN res_partner rp ON rp.id = so.partner_id
            LEFT JOIN sale_order_line sol ON sol.order_id = so.id
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY so.id, so.name, rp.name, so.date_order, so.state
            ORDER BY total_weight DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            ref = r[1]
            cust = r[2]
            if isinstance(ref, dict):
                ref = list(ref.values())[0] if ref else 'New'
            if isinstance(cust, dict):
                cust = list(cust.values())[0] if cust else 'Unknown'
            result.append({
                'id': int(r[0]),
                'ref': str(ref),
                'customer': str(cust),
                'date': str(r[3]),
                'state': str(r[4]),
                'total_weight': round(float(r[5]), 3),
            })
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Top Quotations – Table
    # ─────────────────────────────────────────────────────────────────────────
    def _get_top_quotations(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                so.id AS id,
                so.name AS ref,
                rp.name AS customer,
                so.date_order::DATE AS date,
                so.state AS state,
                COALESCE(SUM(sol.product_uom_qty), 0) AS total_weight
            FROM sale_order so
            JOIN res_partner rp ON rp.id = so.partner_id
            LEFT JOIN sale_order_line sol ON sol.order_id = so.id
            WHERE so.state IN ('draft','sent')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY so.id, so.name, rp.name, so.date_order, so.state
            ORDER BY total_weight DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            ref = r[1]
            cust = r[2]
            if isinstance(ref, dict):
                ref = list(ref.values())[0] if ref else 'New'
            if isinstance(cust, dict):
                cust = list(cust.values())[0] if cust else 'Unknown'
            result.append({
                'id': int(r[0]),
                'ref': str(ref),
                'customer': str(cust),
                'date': str(r[3]),
                'state': str(r[4]),
                'total_weight': round(float(r[5]), 3),
            })
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Sales Order State Distribution – Pie/Donut Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_sales_state_distribution(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT so.state, COUNT(so.id)
            FROM sale_order so
            WHERE so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY so.state"
        cr.execute(q, params)
        rows = cr.fetchall()
        state_map = {
            'draft': 'Quotation',
            'sent': 'Quotation Sent',
            'sale': 'Sales Order',
            'done': 'Locked',
            'cancel': 'Cancelled'
        }
        return [{'label': state_map.get(r[0], r[0]), 'value': int(r[1])} for r in rows]

    # ─────────────────────────────────────────────────────────────────────────
    # Top Products Stock Balance – Bar Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_top_products_stock_balance(self, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                p.id AS purity_id,
                COALESCE(p.name, 'Unknown') AS purity_name,
                SUM(sq.quantity) AS stock_qty
            FROM stock_quant sq
            JOIN product_product pp ON pp.id = sq.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN stock_location sl ON sl.id = sq.location_id
            LEFT JOIN gold_purity p ON p.id = pt.purity_id
            WHERE sl.usage = 'internal'
        """
        params = []
        if branch_id:
            q += " AND sl.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY p.id, p.name
            HAVING SUM(sq.quantity) > 0
            ORDER BY stock_qty DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[1]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Unknown'
            result.append({
                'id': int(r[0]) if r[0] else 0,
                'name': str(name or 'Unknown'),
                'qty': round(float(r[2]), 2)
            })
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Stock by Location – Pie Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_stock_by_location(self, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                sl.id AS location_id,
                COALESCE(sl.complete_name, sl.name) AS location_name,
                SUM(sq.quantity) AS stock_qty
            FROM stock_quant sq
            JOIN stock_location sl ON sl.id = sq.location_id
            WHERE sl.usage = 'internal'
        """
        params = []
        if branch_id:
            q += " AND sl.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY sl.id, sl.complete_name, sl.name
            HAVING SUM(sq.quantity) > 0
            ORDER BY stock_qty DESC
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[1]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Unknown'
            result.append({
                'id': int(r[0]),
                'location': str(name),
                'qty': round(float(r[2]), 2)
            })
        return result


    # ─────────────────────────────────────────────────────────────────────────
    # Sales by Branch – Bar Chart
    # ─────────────────────────────────────────────────────────────────────────
    def _get_sales_by_branch(self, d_from, d_to):
        cr = self._cr
        q = """
            SELECT rb.name, COALESCE(SUM(sol.product_uom_qty), 0)
            FROM res_branch rb
            LEFT JOIN sale_order so ON so.branch_id = rb.id AND so.state IN ('sale','done') AND so.date_order::DATE BETWEEN %s AND %s
            LEFT JOIN sale_order_line sol ON sol.order_id = so.id
            GROUP BY rb.name
            ORDER BY COALESCE(SUM(sol.product_uom_qty), 0) DESC
        """
        cr.execute(q, [d_from, d_to])
        rows = cr.fetchall()
        return [{'name': r[0], 'revenue': round(float(r[1]), 3)} for r in rows]

    # ─────────────────────────────────────────────────────────────────────────
    # Purchase dashboard metrics
    # ─────────────────────────────────────────────────────────────────────────
    def _get_top_rfqs(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT po.id, po.name, rp.name, po.date_order::DATE, COALESCE(SUM(pol.product_qty), 0) AS total_weight
            FROM purchase_order po
            JOIN res_partner rp ON rp.id = po.partner_id
            LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
            WHERE po.state IN ('draft','sent')
              AND po.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND po.branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY po.id, po.name, rp.name, po.date_order ORDER BY total_weight DESC LIMIT 10"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'id': r[0], 'ref': r[1], 'vendor': r[2], 'date': str(r[3]), 'total': round(float(r[4]), 3)} for r in rows]

    def _get_top_purchase_orders(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT po.id, po.name, rp.name, po.date_order::DATE, COALESCE(SUM(pol.product_qty), 0) AS total_weight
            FROM purchase_order po
            JOIN res_partner rp ON rp.id = po.partner_id
            LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
            WHERE po.state IN ('purchase','done')
              AND po.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND po.branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY po.id, po.name, rp.name, po.date_order ORDER BY total_weight DESC LIMIT 10"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'id': r[0], 'ref': r[1], 'vendor': r[2], 'date': str(r[3]), 'total': round(float(r[4]), 3)} for r in rows]

    def _get_top_vendors(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT rp.id, rp.name, COALESCE(SUM(pol.product_qty), 0) AS total_weight
            FROM purchase_order po
            JOIN purchase_order_line pol ON pol.order_id = po.id
            JOIN res_partner rp ON rp.id = po.partner_id
            WHERE po.state IN ('purchase','done')
              AND po.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND po.branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY rp.id, rp.name ORDER BY total_weight DESC LIMIT 10"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'id': r[0], 'vendor': r[1], 'name': r[1], 'total': round(float(r[2]), 3)} for r in rows]

    def _get_top_buyers(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT rp.id, rp.name, COALESCE(SUM(pol.product_qty), 0) AS total_weight
            FROM purchase_order po
            JOIN purchase_order_line pol ON pol.order_id = po.id
            JOIN res_users ru ON ru.id = po.user_id
            JOIN res_partner rp ON rp.id = ru.partner_id
            WHERE po.state IN ('purchase','done')
              AND po.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND po.branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY rp.id, rp.name ORDER BY total_weight DESC LIMIT 10"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'id': r[0], 'name': r[1], 'total': round(float(r[2]), 3)} for r in rows]

    def _get_least_purchase_orders(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT po.id, po.name, rp.name, po.date_order::DATE, COALESCE(SUM(pol.product_qty), 0) AS total_weight
            FROM purchase_order po
            JOIN res_partner rp ON rp.id = po.partner_id
            LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
            WHERE po.state IN ('purchase','done')
              AND po.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND po.branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY po.id, po.name, rp.name, po.date_order HAVING COALESCE(SUM(pol.product_qty), 0) > 0 ORDER BY total_weight ASC LIMIT 10"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'id': r[0], 'ref': r[1], 'vendor': r[2], 'date': str(r[3]), 'total': round(float(r[4]), 3)} for r in rows]

    def _get_least_vendors(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT rp.id, rp.name, COALESCE(SUM(pol.product_qty), 0) AS total_weight
            FROM purchase_order po
            JOIN purchase_order_line pol ON pol.order_id = po.id
            JOIN res_partner rp ON rp.id = po.partner_id
            WHERE po.state IN ('purchase','done')
              AND po.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND po.branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY rp.id, rp.name HAVING COALESCE(SUM(pol.product_qty), 0) > 0 ORDER BY total_weight ASC LIMIT 10"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'id': r[0], 'vendor': r[1], 'name': r[1], 'total': round(float(r[2]), 3)} for r in rows]

    def _get_best_sellers_by_qty(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                pt.name AS product_name,
                COALESCE(SUM(sol.product_uom_qty), 0) AS qty_sold,
                COALESCE(SUM(sol.price_subtotal), 0) AS revenue
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            JOIN product_product pp ON pp.id = sol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY pt.name
            ORDER BY qty_sold DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[0]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Product'
            result.append({
                'name': str(name),
                'qty': round(float(r[1]), 2),
                'revenue': round(float(r[2]), 2),
            })
        return result

    def _get_best_selling_categories(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                gp.id AS category_id,
                COALESCE(gp.name, 'Unknown Purity') AS category_name,
                COALESCE(SUM(sol.product_uom_qty), 0) AS qty_sold,
                COALESCE(SUM(sol.price_subtotal), 0) AS revenue
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            JOIN product_product pp ON pp.id = sol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN gold_purity gp ON gp.id = COALESCE(sol.purity_id, pt.purity_id)
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY gp.id, gp.name
            ORDER BY qty_sold DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[1]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Purity'
            result.append({
                'id': int(r[0]) if r[0] else 0,
                'name': str(name or 'Other'),
                'qty': round(float(r[2]), 3),
                'revenue': round(float(r[3]), 2),
            })
        return result

    def _get_invoiced_kpis(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT
                COALESCE(SUM(aml.quantity), 0) AS total_invoiced,
                COALESCE(SUM(CASE WHEN am.payment_state = 'paid' THEN aml.quantity ELSE 0 END), 0) AS total_paid,
                COALESCE(SUM(CASE WHEN am.payment_state != 'paid' THEN aml.quantity ELSE 0 END), 0) AS total_unpaid,
                COUNT(DISTINCT am.id) AS invoice_count
            FROM account_move am
            JOIN account_move_line aml ON aml.move_id = am.id
            WHERE am.move_type = 'out_invoice' 
              AND am.state = 'posted'
              AND aml.display_type = 'product'
              AND am.invoice_date BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND am.branch_id = %s"
            params.append(branch_id)
        cr.execute(q, params)
        res = cr.fetchone()
        
        total_invoiced = float(res[0] or 0)
        total_paid = float(res[1] or 0)
        total_unpaid = float(res[2] or 0)
        invoice_count = int(res[3] or 0)
        avg_invoice = total_invoiced / invoice_count if invoice_count > 0 else 0
        
        return {
            'total_invoiced': round(total_invoiced, 3),
            'total_paid': round(total_paid, 3),
            'total_unpaid': round(total_unpaid, 3),
            'avg_invoice': round(avg_invoice, 3),
            'invoice_count': invoice_count,
        }

    def _get_invoiced_monthly(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT 
                to_char(am.invoice_date, 'Mon YYYY') AS month,
                date_trunc('month', am.invoice_date) AS month_start,
                COALESCE(gp.name, 'Unknown') AS purity,
                COALESCE(sum(aml.quantity), 0) AS total
            FROM account_move am
            JOIN account_move_line aml ON aml.move_id = am.id
            LEFT JOIN product_product pp ON pp.id = aml.product_id
            LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN gold_purity gp ON gp.id = pt.purity_id
            WHERE am.move_type = 'out_invoice' 
              AND am.state = 'posted'
              AND aml.display_type = 'product'
              AND am.invoice_date IS NOT NULL
              AND am.invoice_date BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND am.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY to_char(am.invoice_date, 'Mon YYYY'), date_trunc('month', am.invoice_date), COALESCE(gp.name, 'Unknown')
            ORDER BY month_start, purity
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'month': r[0], 'purity': r[2], 'weight': round(float(r[3]), 3)} for r in rows]

    def _get_invoiced_top_invoices(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT 
                am.id AS invoice_id,
                am.name AS name,
                rp.name AS partner_name,
                am.invoice_date AS date,
                COALESCE(sum(aml.quantity), 0) AS weight,
                am.payment_state AS payment_state
            FROM account_move am
            LEFT JOIN res_partner rp ON am.partner_id = rp.id
            JOIN account_move_line aml ON aml.move_id = am.id
            WHERE am.move_type = 'out_invoice' 
              AND am.state = 'posted'
              AND aml.display_type = 'product'
              AND am.invoice_date BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND am.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY am.id, rp.name
            ORDER BY weight DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{
            'id': r[0],
            'name': r[1] or 'Draft/Unnamed',
            'partner': r[2] or 'Unknown Partner',
            'date': str(r[3]) if r[3] else '',
            'amount': round(float(r[4]), 3),
            'status': r[5] or 'draft'
        } for r in rows]

    def _get_invoiced_top_categories(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT 
                pc.name AS category_name,
                COALESCE(sum(aml.quantity), 0) AS total
            FROM account_move_line aml
            JOIN account_move am ON aml.move_id = am.id
            JOIN product_product pp ON aml.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            LEFT JOIN product_category pc ON pt.categ_id = pc.id
            WHERE am.move_type = 'out_invoice' 
              AND am.state = 'posted'
              AND aml.display_type = 'product'
              AND am.invoice_date BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND am.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY pc.name
            ORDER BY total DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[0]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Other'
            result.append({
                'name': name or 'Other',
                'value': round(float(r[1]), 3)
            })
        return result

    def _get_invoiced_top_salespeople(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT 
                ru.id AS user_id,
                rp.name AS salesperson_name,
                COALESCE(sum(aml.quantity), 0) AS total
            FROM account_move am
            JOIN account_move_line aml ON aml.move_id = am.id
            JOIN res_users ru ON am.invoice_user_id = ru.id
            JOIN res_partner rp ON ru.partner_id = rp.id
            WHERE am.move_type = 'out_invoice' 
              AND am.state = 'posted'
              AND aml.display_type = 'product'
              AND am.invoice_date BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND am.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY ru.id, rp.name
            ORDER BY total DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{
            'id': int(r[0]),
            'name': r[1] or 'Unknown',
            'value': round(float(r[2]), 3)
        } for r in rows]

    def _get_date_branch_collection(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT 
                TO_CHAR(so.date_order, 'YYYY-MM') AS month_key,
                TO_CHAR(so.date_order, 'Mon') AS month_name,
                rb.name AS branch_name,
                SUM(so.amount_total) AS total_amount,
                SUM(COALESCE((SELECT SUM(product_uom_qty) FROM sale_order_line WHERE order_id = so.id), 0)) AS total_weight
            FROM sale_order so
            JOIN res_branch rb ON rb.id = so.branch_id
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY TO_CHAR(so.date_order, 'YYYY-MM'), TO_CHAR(so.date_order, 'Mon'), rb.name
            ORDER BY month_key ASC, rb.name ASC
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            month_key = str(r[0])
            month_name = str(r[1])
            branch = r[2]
            if isinstance(branch, dict):
                branch = list(branch.values())[0] if branch else 'Unknown'
            result.append({
                'month_key': month_key,
                'date': month_name,
                'branch': str(branch or 'Unknown'),
                'amount': round(float(r[3]), 2),
                'weight': round(float(r[4]), 3)
            })
        return result

    def _get_branch_wise_target(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT 
                rb.id,
                rb.name,
                COALESCE(act.actual_weight, 0.0) AS actual_weight,
                COALESCE(tgt.target_weight, 0.0) AS target_weight
            FROM res_branch rb
            LEFT JOIN (
                SELECT
                    so.branch_id,
                    COALESCE(SUM(sol.product_uom_qty), 0) AS actual_weight
                FROM sale_order so
                JOIN sale_order_line sol ON sol.order_id = so.id
                LEFT JOIN gold_purity gp ON gp.id = sol.purity_id
                WHERE so.state IN ('sale','done')
                  AND so.date_order::DATE BETWEEN %s AND %s
                  AND UPPER(TRIM(gp.name)) IN ('22K', '18CT', '22KT')
                GROUP BY so.branch_id
            ) act ON act.branch_id = rb.id
            LEFT JOIN (
                SELECT
                    branch_id,
                    COALESCE(SUM(target_gms_22k + target_gms_18ct + target_gms_22kt), 0) AS target_weight
                FROM salesman_target
                WHERE (date_from <= %s AND date_to >= %s)
                GROUP BY branch_id
            ) tgt ON tgt.branch_id = rb.id
            WHERE 1=1
        """
        params = [d_from, d_to, d_to, d_from]
        if branch_id:
            q += " AND rb.id = %s"
            params.append(branch_id)
        q += " ORDER BY actual_weight DESC"
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            branch = r[1]
            if isinstance(branch, dict):
                branch = list(branch.values())[0] if branch else 'Unknown'
            result.append({
                'branch_id': int(r[0]),
                'branch': str(branch or 'Unknown'),
                'actual': round(float(r[2]), 3),
                'target': round(float(r[3]), 3),
            })
        return result

    def _get_schemes_kpis(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT 
                state,
                COUNT(*),
                COALESCE(SUM(total_paid), 0)
            FROM jewellery_scheme_enrollment
            WHERE date_of_joining BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        q += " GROUP BY state"
        cr.execute(q, params)
        rows = cr.fetchall()
        
        kpis = {
            'running': {'count': 0, 'total_paid': 0.0},
            'completed': {'count': 0, 'total_paid': 0.0},
            'redeemed': {'count': 0, 'total_paid': 0.0},
            'total': {'count': 0, 'total_paid': 0.0}
        }
        for r in rows:
            state = r[0]
            count = int(r[1] or 0)
            total_paid = float(r[2] or 0.0)
            if state in kpis:
                kpis[state] = {'count': count, 'total_paid': round(total_paid, 2)}
            kpis['total']['count'] += count
            kpis['total']['total_paid'] += total_paid
        kpis['total']['total_paid'] = round(kpis['total']['total_paid'], 2)
        return kpis

    def _get_schemes_monthly_trend(self, d_from, d_to, branch_id=None):
        cr = self._cr
        q = """
            SELECT 
                to_char(date_of_joining, 'Mon YYYY') AS month,
                date_trunc('month', date_of_joining) AS month_start,
                COUNT(*) AS count
            FROM jewellery_scheme_enrollment
            WHERE date_of_joining BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY to_char(date_of_joining, 'Mon YYYY'), date_trunc('month', date_of_joining)
            ORDER BY month_start
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'label': r[0], 'value': int(r[2] or 0)} for r in rows]

    def _get_schemes_by_state(self, state, d_from, d_to, branch_id=None):
        cr = self._cr
        if state == 'running':
            from datetime import date
            d_from = d_to = date.today()

        q = """
            SELECT 
                e.id,
                e.name,
                COALESCE(rp.name, 'Unknown') AS customer,
                e.date_of_joining,
                COALESCE(e.total_paid, 0) AS total_paid,
                COALESCE(e.balance_amount, 0) AS balance_amount
            FROM jewellery_scheme_enrollment e
            LEFT JOIN res_partner rp ON rp.id = e.partner_id
            WHERE e.state = %s 
              AND e.date_of_joining BETWEEN %s AND %s
        """
        params = [state, d_from, d_to]
        if branch_id:
            q += " AND e.branch_id = %s"
            params.append(branch_id)
        q += " ORDER BY e.date_of_joining DESC LIMIT 10"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{
            'id': r[0],
            'ref': r[1],
            'customer': r[2],
            'date': str(r[3]),
            'total_paid': round(float(r[4]), 2),
            'balance': round(float(r[5]), 2)
        } for r in rows]

    def _get_employee_attendance_data(self, d_from, d_to, branch_id=None):
        import pytz
        from datetime import datetime, timedelta, date

        # Get active employees
        domain = [('active', '=', True)]
        if branch_id:
            domain.extend([
                '|',
                ('essl_location_id', '=', branch_id),
                '|',
                ('user_id.branch_id', '=', branch_id),
                ('label_location_id.branch_id', '=', branch_id)
            ])
        employees = self.env['hr.employee'].sudo().search(domain)
        total_employees = len(employees)
        if not employees:
            return {
                'kpis': {
                    'total': 0,
                    'present': 0,
                    'absent': 0,
                    'leave': 0,
                    'half_day': 0
                },
                'summary': []
            }

        # Timezone settings
        timezone_name = self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.timezone') or 'Asia/Kolkata'
        try:
            local_tz = pytz.timezone(timezone_name)
        except Exception:
            local_tz = pytz.timezone('Asia/Kolkata')

        # Widen search to cover local/UTC boundaries
        start_utc = local_tz.localize(datetime.combine(d_from, datetime.min.time())).astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = local_tz.localize(datetime.combine(d_to, datetime.max.time())).astimezone(pytz.utc).replace(tzinfo=None)

        # Retrieve attendances
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', employees.ids),
            ('check_in', '>=', start_utc),
            ('check_in', '<=', end_utc)
        ])

        # Map to dict: { (employee_id, local_date): attendance }
        att_by_emp_date = {}
        for att in attendances:
            check_in_local = pytz.utc.localize(att.check_in).astimezone(local_tz)
            local_date = check_in_local.date()
            existing_att = att_by_emp_date.get((att.employee_id.id, local_date))
            if not existing_att or att.worked_hours > existing_att.worked_hours:
                att_by_emp_date[(att.employee_id.id, local_date)] = att

        # Retrieve approved leaves
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', 'in', employees.ids),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', d_to),
            ('request_date_to', '>=', d_from)
        ])

        # Map to dict: { (employee_id, date): 'leave' / 'half_day' }
        leave_by_emp_date = {}
        for leave in leaves:
            curr_date = max(leave.request_date_from, d_from)
            end_date = min(leave.request_date_to, d_to)
            while curr_date <= end_date:
                key = (leave.employee_id.id, curr_date)
                if not leave.request_unit_half:
                    leave_by_emp_date[key] = 'leave'
                else:
                    if leave_by_emp_date.get(key) != 'leave':
                        leave_by_emp_date[key] = 'half_day'
                curr_date += timedelta(days=1)

        # Track summaries per employee
        emp_summary = {
            emp.id: {
                'id': emp.id,
                'name': emp.name,
                'code': emp.essl_emp_code or emp.identification_id or emp.barcode or '',
                'department': emp.department_id.name or 'Not Specified',
                'present': 0,
                'absent': 0,
                'leave': 0,
                'half_day': 0,
                'worked_hours': 0.0
            } for emp in employees
        }

        days_count = 0
        total_present = 0
        total_absent = 0
        total_leave = 0
        total_half_day = 0

        curr_date = d_from
        while curr_date <= d_to:
            days_count += 1
            for emp in employees:
                att = att_by_emp_date.get((emp.id, curr_date))
                leave_status = leave_by_emp_date.get((emp.id, curr_date))

                summary = emp_summary[emp.id]
                if att:
                    summary['worked_hours'] += att.worked_hours
                    if att.half_day_leave or leave_status == 'half_day':
                        total_half_day += 1
                        summary['half_day'] += 1
                    else:
                        total_present += 1
                        summary['present'] += 1
                else:
                    if leave_status == 'leave':
                        total_leave += 1
                        summary['leave'] += 1
                    elif leave_status == 'half_day':
                        total_half_day += 1
                        summary['half_day'] += 1
                        summary['worked_hours'] += 4.0
                    else:
                        total_absent += 1
                        summary['absent'] += 1

            curr_date += timedelta(days=1)

        # Average counts per day
        avg_present = round(total_present / days_count, 1) if days_count > 0 else 0
        avg_absent = round(total_absent / days_count, 1) if days_count > 0 else 0
        avg_leave = round(total_leave / days_count, 1) if days_count > 0 else 0
        avg_half_day = round(total_half_day / days_count, 1) if days_count > 0 else 0

        # Sort summary by employee name
        summary_list = list(emp_summary.values())
        summary_list.sort(key=lambda x: x['name'])

        # Round worked hours to 2 decimals
        for s in summary_list:
            s['worked_hours'] = round(s['worked_hours'], 2)

        return {
            'kpis': {
                'total': total_employees,
                'present': avg_present,
                'absent': avg_absent,
                'leave': avg_leave,
                'half_day': avg_half_day
            },
            'summary': summary_list
        }



