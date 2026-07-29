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
    @api.model
    def get_dashboard_data(self, period='this_month', date_from=None, date_to=None, branch_id=None):
        cr = self._cr
        
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
            'kpis': self._get_kpis(d_from, d_to, b_id),
            'sales_monthly': self._get_sales_monthly(d_from, d_to, b_id),
            'purchase_monthly': self._get_purchase_monthly(d_from, d_to, b_id),
            'expense_monthly': self._get_expense_monthly(b_id),
            'inventory_category': self._get_inventory_by_category(b_id),
            'product_category': self._get_product_category_distribution(b_id),
            'jewellery_purity': self._get_jewellery_purity_breakdown(b_id),
            'top_products': self._get_top_selling_products(d_from, d_to, b_id),
            'sales_by_salesman': self._get_sales_by_salesman(d_from, d_to, b_id),
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
            'best_sellers_by_revenue': self._get_top_selling_products(d_from, d_to, b_id),
            'best_sellers_by_qty': self._get_best_sellers_by_qty(d_from, d_to, b_id),
            'best_selling_categories': self._get_best_selling_categories(d_from, d_to, b_id),
            'stock_by_location': self._get_stock_by_location(b_id),
            'top_expenses': self._get_top_expenses(d_from, d_to, b_id),
            'top_expense_categories': self._get_top_expense_categories(d_from, d_to, b_id),
            'top_expense_employees': self._get_top_expense_employees(d_from, d_to, b_id),
            'expense_bullet_data': self._get_expense_bullet_data(d_from, d_to, b_id),
            'employees_by_department': self._get_employees_by_department(d_from, d_to, b_id),
            'attendance_trend': self._get_attendance_trend(d_from, d_to, b_id),
            'department_attendance_summary': self._get_department_attendance_summary(d_from, d_to, b_id),
            'branch_attendance_summary': self._get_branch_attendance_summary(d_from, d_to),
            'period': {'from': str(d_from), 'to': str(d_to)},
            'branches': branches,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # KPIs
    # ─────────────────────────────────────────────────────────────────────────
    def _get_kpis(self, d_from, d_to, branch_id=None):
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
            q += " AND COALESCE(emp.essl_location_id, u.branch_id, sl.branch_id) = %s"
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

        # HR / Employee KPIs
        emp_q = """
            SELECT COUNT(DISTINCT e.id) FROM hr_employee e
            LEFT JOIN res_users u ON u.id = e.user_id
            LEFT JOIN stock_location sl ON sl.id = e.label_location_id
            WHERE e.active = TRUE
              AND (e.joining_date <= %s OR e.joining_date IS NULL)
              AND (e.departure_date >= %s OR e.departure_date IS NULL)
        """
        emp_params = [d_to, d_from]
        if branch_id:
            emp_q += " AND COALESCE(e.essl_location_id, u.branch_id, sl.branch_id) = %s"
            emp_params.append(branch_id)
        cr.execute(emp_q, emp_params)
        employee_count = cr.fetchone()[0] or 0

        dept_q = """
            SELECT COUNT(DISTINCT e.department_id) FROM hr_employee e
            LEFT JOIN res_users u ON u.id = e.user_id
            LEFT JOIN stock_location sl ON sl.id = e.label_location_id
            WHERE e.active = TRUE AND e.department_id IS NOT NULL
              AND (e.joining_date <= %s OR e.joining_date IS NULL)
              AND (e.departure_date >= %s OR e.departure_date IS NULL)
        """
        dept_params = [d_to, d_from]
        if branch_id:
            dept_q += " AND COALESCE(e.essl_location_id, u.branch_id, sl.branch_id) = %s"
            dept_params.append(branch_id)
        cr.execute(dept_q, dept_params)
        department_count = cr.fetchone()[0] or 0

        pres_q = """
            SELECT COUNT(DISTINCT a.employee_id) 
            FROM hr_attendance a
            JOIN hr_employee e ON e.id = a.employee_id
            LEFT JOIN res_users u ON u.id = e.user_id
            LEFT JOIN stock_location sl ON sl.id = e.label_location_id
            WHERE a.check_in::DATE BETWEEN %s AND %s
        """
        pres_params = [d_from, d_to]
        if branch_id:
            pres_q += " AND COALESCE(e.essl_location_id, u.branch_id, sl.branch_id) = %s"
            pres_params.append(branch_id)
        cr.execute(pres_q, pres_params)
        present_count = cr.fetchone()[0] or 0

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
            'employee_count': int(employee_count),
            'department_count': int(department_count),
            'present_count': int(present_count),
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
    def _get_expense_monthly(self, branch_id=None):
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
            q += " AND COALESCE(emp.essl_location_id, u.branch_id, sl.branch_id) = %s"
            params.append(branch_id)
        q += " GROUP BY month, month_start ORDER BY month_start"
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'month': r[0], 'total': round(float(r[2]), 2)} for r in rows]

    # ─────────────────────────────────────────────────────────────────────────
    # Expense Analysis Methods
    # ─────────────────────────────────────────────────────────────────────────
    def _get_top_expenses(self, d_from, d_to, branch_id=None):
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
            q += " AND COALESCE(emp.essl_location_id, u.branch_id, sl.branch_id) = %s"
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

    def _get_top_expense_categories(self, d_from, d_to, branch_id=None):
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
            q += " AND COALESCE(emp.essl_location_id, u.branch_id, sl.branch_id) = %s"
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

    def _get_top_expense_employees(self, d_from, d_to, branch_id=None):
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
            q += " AND COALESCE(emp.essl_location_id, u.branch_id, sl.branch_id) = %s"
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

    def _get_expense_bullet_data(self, d_from, d_to, branch_id=None):
        categories = self._get_top_expense_categories(d_from, d_to, branch_id)
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
                COALESCE(pc.complete_name, 'Uncategorized') AS category,
                COALESCE(SUM(sq.quantity), 0) AS qty
            FROM stock_quant sq
            JOIN product_product pp ON pp.id = sq.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN stock_location sl ON sl.id = sq.location_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            WHERE sl.usage = 'internal'
        """
        params = []
        if branch_id:
            q += " AND sl.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY pc.complete_name
            ORDER BY qty DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'label': r[0], 'value': round(float(r[1]), 3)} for r in rows]

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
                pt.id AS pt_id,
                pt.name AS product_name,
                SUM(sq.quantity) AS stock_qty
            FROM stock_quant sq
            JOIN product_product pp ON pp.id = sq.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN stock_location sl ON sl.id = sq.location_id
            WHERE sl.usage = 'internal'
        """
        params = []
        if branch_id:
            q += " AND sl.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY pt.id, pt.name
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
                'id': int(r[0]),
                'name': str(name),
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
                pc.id AS category_id,
                pc.name AS category_name,
                COALESCE(SUM(sol.product_uom_qty), 0) AS qty_sold,
                COALESCE(SUM(sol.price_subtotal), 0) AS revenue
            FROM sale_order_line sol
            JOIN sale_order so ON so.id = sol.order_id
            JOIN product_product pp ON pp.id = sol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            LEFT JOIN product_category pc ON pc.id = pt.categ_id
            WHERE so.state IN ('sale','done')
              AND so.date_order::DATE BETWEEN %s AND %s
        """
        params = [d_from, d_to]
        if branch_id:
            q += " AND so.branch_id = %s"
            params.append(branch_id)
        q += """
            GROUP BY pc.id, pc.name
            ORDER BY qty_sold DESC
            LIMIT 10
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[1]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Category'
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
                COALESCE(sum(aml.quantity), 0) AS total
            FROM account_move am
            JOIN account_move_line aml ON aml.move_id = am.id
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
            GROUP BY to_char(am.invoice_date, 'Mon YYYY'), date_trunc('month', am.invoice_date)
            ORDER BY month_start
        """
        cr.execute(q, params)
        rows = cr.fetchall()
        return [{'label': r[0], 'value': round(float(r[2]), 3)} for r in rows]

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

    # ─────────────────────────────────────────────────────────────────────────
    # Employee Tab aggregation methods
    # ─────────────────────────────────────────────────────────────────────────
    def _get_employees_by_department(self, d_from=None, d_to=None, branch_id=None):
        cr = self._cr
        q = """
            SELECT 
                d.name,
                COUNT(e.id) AS emp_count
            FROM hr_department d
            LEFT JOIN (
                SELECT emp.id, emp.department_id, emp.joining_date, emp.departure_date, emp.active,
                       u.branch_id AS user_branch_id, sl.branch_id AS loc_branch_id, emp.essl_location_id
                FROM hr_employee emp
                LEFT JOIN res_users u ON u.id = emp.user_id
                LEFT JOIN stock_location sl ON sl.id = emp.label_location_id
            ) e ON e.department_id = d.id AND e.active = TRUE
                AND (%s::date IS NULL OR e.joining_date <= %s OR e.joining_date IS NULL)
                AND (%s::date IS NULL OR e.departure_date >= %s OR e.departure_date IS NULL)
                AND (%s::integer IS NULL OR COALESCE(e.essl_location_id, e.user_branch_id, e.loc_branch_id) = %s)
            WHERE d.active = TRUE
            GROUP BY d.id, d.name
            ORDER BY emp_count DESC
        """
        cr.execute(q, [d_to, d_to, d_from, d_from, branch_id, branch_id])
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[0]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Department'
            result.append({
                'department': str(name),
                'count': int(r[1])
            })
        return result

    def _get_attendance_trend(self, d_from, d_to, branch_id=None):
        cr = self._cr
        delta_days = (d_to - d_from).days
        if delta_days > 90:
            q = """
                SELECT
                    to_char(a.check_in, 'Mon YYYY') AS period,
                    date_trunc('month', a.check_in) AS period_start,
                    COUNT(DISTINCT a.employee_id) AS present_count
                FROM hr_attendance a
                JOIN hr_employee e ON e.id = a.employee_id
                LEFT JOIN res_users u ON u.id = e.user_id
                LEFT JOIN stock_location sl ON sl.id = e.label_location_id
                WHERE a.check_in::DATE BETWEEN %s AND %s
                  AND (%s::integer IS NULL OR COALESCE(e.essl_location_id, u.branch_id, sl.branch_id) = %s)
                GROUP BY period, period_start
                ORDER BY period_start
            """
        else:
            q = """
                SELECT
                    to_char(a.check_in, 'YYYY-MM-DD') AS period,
                    date_trunc('day', a.check_in) AS period_start,
                    COUNT(DISTINCT a.employee_id) AS present_count
                FROM hr_attendance a
                JOIN hr_employee e ON e.id = a.employee_id
                LEFT JOIN res_users u ON u.id = e.user_id
                LEFT JOIN stock_location sl ON sl.id = e.label_location_id
                WHERE a.check_in::DATE BETWEEN %s AND %s
                  AND (%s::integer IS NULL OR COALESCE(e.essl_location_id, u.branch_id, sl.branch_id) = %s)
                GROUP BY period, period_start
                ORDER BY period_start
            """
        cr.execute(q, [d_from, d_to, branch_id, branch_id])
        rows = cr.fetchall()
        return [{'period': r[0], 'count': int(r[2])} for r in rows]

    def _get_department_attendance_summary(self, d_from, d_to, branch_id=None):
        cr = self._cr
        num_days = (d_to - d_from).days + 1
        if num_days <= 0:
            num_days = 1
        q = """
            SELECT 
                d.name AS dept_name,
                COUNT(DISTINCT e.id) AS total_employees,
                COUNT(DISTINCT a.employee_id) AS present_employees,
                COUNT(DISTINCT CONCAT(a.employee_id, '_', a.check_in::DATE)) AS present_days_count,
                COUNT(a.id) AS attendance_count
            FROM hr_department d
            LEFT JOIN (
                SELECT emp.id, emp.department_id, emp.joining_date, emp.departure_date, emp.active,
                       u.branch_id AS user_branch_id, sl.branch_id AS loc_branch_id, emp.essl_location_id
                FROM hr_employee emp
                LEFT JOIN res_users u ON u.id = emp.user_id
                LEFT JOIN stock_location sl ON sl.id = emp.label_location_id
            ) e ON e.department_id = d.id AND e.active = TRUE
                AND (e.joining_date <= %s OR e.joining_date IS NULL)
                AND (e.departure_date >= %s OR e.departure_date IS NULL)
                AND (%s::integer IS NULL OR COALESCE(e.essl_location_id, e.user_branch_id, e.loc_branch_id) = %s)
            LEFT JOIN hr_attendance a ON a.employee_id = e.id AND a.check_in::DATE BETWEEN %s AND %s
            WHERE d.active = TRUE
            GROUP BY d.id, d.name
            ORDER BY total_employees DESC, present_employees DESC
        """
        cr.execute(q, [d_to, d_from, branch_id, branch_id, d_from, d_to])
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[0]
            if isinstance(name, dict):
                name = list(name.values())[0] if name else 'Department'
            total_emp = int(r[1])
            present_emp = int(r[2])
            present_days = int(r[3])
            att_count = int(r[4])
            
            # Expected person-days of attendance
            expected_person_days = total_emp * num_days
            if expected_person_days > 0:
                rate = round((present_days / expected_person_days * 100.0), 1)
                rate = min(rate, 100.0)
            else:
                rate = 0.0

            result.append({
                'department': str(name),
                'total_employees': total_emp,
                'present_employees': present_emp,
                'attendance_count': att_count,
                'attendance_rate': rate
            })
        return result

    def _get_branch_attendance_summary(self, d_from, d_to):
        cr = self._cr
        cr.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'res_branch')")
        if not cr.fetchone()[0]:
            return []
            
        num_days = (d_to - d_from).days + 1
        if num_days <= 0:
            num_days = 1
        q = """
            SELECT 
                b.name AS branch_name,
                COUNT(DISTINCT e.id) AS total_employees,
                COUNT(DISTINCT a.employee_id) AS present_employees,
                COUNT(DISTINCT CONCAT(a.employee_id, '_', a.check_in::DATE)) AS present_days_count,
                COUNT(a.id) AS attendance_count,
                b.id AS branch_id
            FROM res_branch b
            LEFT JOIN (
                SELECT emp.id, emp.joining_date, emp.departure_date, emp.active,
                       u.branch_id AS user_branch_id, sl.branch_id AS loc_branch_id, emp.essl_location_id
                FROM hr_employee emp
                LEFT JOIN res_users u ON u.id = emp.user_id
                LEFT JOIN stock_location sl ON sl.id = emp.label_location_id
            ) e ON COALESCE(e.essl_location_id, e.user_branch_id, e.loc_branch_id) = b.id AND e.active = TRUE
                AND (e.joining_date <= %s OR e.joining_date IS NULL)
                AND (e.departure_date >= %s OR e.departure_date IS NULL)
            LEFT JOIN hr_attendance a ON a.employee_id = e.id AND a.check_in::DATE BETWEEN %s AND %s
            GROUP BY b.id, b.name
            ORDER BY total_employees DESC, present_employees DESC, b.name
        """
        cr.execute(q, [d_to, d_from, d_from, d_to])
        rows = cr.fetchall()
        result = []
        for r in rows:
            name = r[0]
            total_emp = int(r[1])
            present_emp = int(r[2])
            present_days = int(r[3])
            att_count = int(r[4])
            
            # Expected person-days of attendance
            expected_person_days = total_emp * num_days
            if expected_person_days > 0:
                rate = round((present_days / expected_person_days * 100.0), 1)
                rate = min(rate, 100.0)
            else:
                rate = 0.0

            result.append({
                'id': int(r[5]),
                'branch': str(name),
                'total_employees': total_emp,
                'present_employees': present_emp,
                'attendance_count': att_count,
                'attendance_rate': rate
            })
        return result



