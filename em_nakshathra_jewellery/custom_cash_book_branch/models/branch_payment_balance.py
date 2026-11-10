# -*- coding: utf-8 -*-
import io
import json
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class BranchPaymentBalanceReport(models.TransientModel):
    _name = 'branch.payment.balance.report'
    _description = 'Branch Treasury & Payment Balance Report (Bank, Cash, Card, UPI)'

    def _is_admin_user(self):
        """
        Check if current user belongs to Administration (Admin / Settings or Access Rights).
        """
        user = self.env.user
        return (
            user._is_admin()
            or user.has_group('base.group_system')
            or user.has_group('base.group_erp_manager')
        )

    def _get_allowed_branch_ids(self):
        """
        Returns allowed branch IDs for current user.
        If admin user group, returns None (all branches allowed and editable).
        For all other user groups, strictly returns the user's assigned branch(es) (non-editable).
        """
        if self._is_admin_user():
            return None

        user = self.env.user
        if hasattr(user, 'branch_ids') and user.branch_ids:
            return user.branch_ids.ids
        elif hasattr(user, 'branch_id') and user.branch_id:
            return [user.branch_id.id]
        elif hasattr(user, 'allowed_branch_ids') and user.allowed_branch_ids:
            return user.allowed_branch_ids.ids
        return [-1]

    @api.model
    def get_initial_data(self):
        """Returns metadata for initial view loading: branches, default dates, currency, editability."""
        is_admin = self._is_admin_user()
        allowed_branch_ids = self._get_allowed_branch_ids()

        branch_domain = []
        if allowed_branch_ids is not None:
            branch_domain = [('id', 'in', allowed_branch_ids)]
        
        branches = self.env['res.branch'].search_read(branch_domain, ['id', 'name', 'branch_code'], order='name asc')
        
        today = fields.Date.today()
        
        default_branch = False
        if not is_admin:
            # Non-admin user: strictly default to their assigned branch
            if allowed_branch_ids and len(allowed_branch_ids) > 0 and allowed_branch_ids[0] != -1:
                default_branch = allowed_branch_ids[0]
            elif hasattr(self.env.user, 'branch_id') and self.env.user.branch_id:
                default_branch = self.env.user.branch_id.id
            elif branches:
                default_branch = branches[0]['id']
            else:
                default_branch = 'all'
        else:
            # Admin user: can select any branch or 'all'
            if hasattr(self.env.user, 'branch_id') and self.env.user.branch_id:
                default_branch = self.env.user.branch_id.id
            else:
                default_branch = 'all'

        company = self.env.company
        currency_symbol = company.currency_id.symbol or '₹'

        default_branch_name = 'All Branches'
        if default_branch and default_branch != 'all':
            b_rec = self.env['res.branch'].browse(int(default_branch))
            if b_rec.exists():
                default_branch_name = b_rec.name
        elif branches and len(branches) == 1:
            default_branch_name = branches[0]['name']

        return {
            'branches': branches,
            'default_branch_id': default_branch or 'all',
            'default_branch_name': default_branch_name,
            'is_branch_editable': is_admin,
            'date_from': today.strftime('%Y-%m-%d'),
            'date_to': today.strftime('%Y-%m-%d'),
            'currency_symbol': currency_symbol,
            'company_name': company.name,
        }

    def _get_liquidity_account_ids(self):
        """
        Fetch all liquidity accounts (Bank & Cash accounts, Suspense, and Outstanding Payment/Receipt accounts).
        In Odoo 17, account.payment posts to Outstanding Receipts / Payments accounts (account_type = 'asset_current').
        """
        self.env.cr.execute("""
            SELECT DISTINCT aa.id
            FROM account_journal aj
            JOIN account_account aa ON (
                aa.id = aj.default_account_id 
                OR aa.id = aj.suspense_account_id
                OR aa.account_type = 'asset_cash'
            )
            WHERE aj.type IN ('bank', 'cash')
            UNION
            SELECT DISTINCT apml.payment_account_id
            FROM account_payment_method_line apml
            JOIN account_journal aj ON apml.journal_id = aj.id
            WHERE aj.type IN ('bank', 'cash') AND apml.payment_account_id IS NOT NULL
        """)
        account_ids = set(r[0] for r in self.env.cr.fetchall())
        for company in self.env['res.company'].search([]):
            if hasattr(company, 'account_journal_payment_debit_account_id') and company.account_journal_payment_debit_account_id:
                account_ids.add(company.account_journal_payment_debit_account_id.id)
            if hasattr(company, 'account_journal_payment_credit_account_id') and company.account_journal_payment_credit_account_id:
                account_ids.add(company.account_journal_payment_credit_account_id.id)
        return list(account_ids)

    @api.model
    def get_balance_summary(self, branch_id=None, date_from=None, date_to=None):
        """
        Calculates Opening Balance, Debit, Credit, and Closing Balance for:
        - Bank
        - Cash
        - Card
        - UPI
        according to the selected branch and date choosing.
        """
        today = fields.Date.today()
        if not date_from:
            date_from = today.strftime('%Y-%m-%d')
        if not date_to:
            date_to = today.strftime('%Y-%m-%d')

        # Check branch access restrictions
        allowed_branch_ids = self._get_allowed_branch_ids()
        if allowed_branch_ids is not None:
            if not branch_id or branch_id == 'all':
                branch_ids_to_filter = allowed_branch_ids
            else:
                try:
                    bid = int(branch_id)
                    branch_ids_to_filter = [bid] if bid in allowed_branch_ids else allowed_branch_ids
                except (ValueError, TypeError):
                    branch_ids_to_filter = allowed_branch_ids
        else:
            if branch_id and branch_id != 'all':
                try:
                    branch_ids_to_filter = [int(branch_id)]
                except (ValueError, TypeError):
                    branch_ids_to_filter = None
            else:
                branch_ids_to_filter = None

        liquidity_acc_ids = self._get_liquidity_account_ids()
        if not liquidity_acc_ids:
            return {'error': 'No liquidity accounts found.'}

        # Build branch filter clause
        branch_clause = ""
        params_open = [tuple(liquidity_acc_ids), date_from]
        params_period = [tuple(liquidity_acc_ids), date_from, date_to]

        if branch_ids_to_filter:
            branch_clause = "AND COALESCE(aml.branch_id, am.branch_id, aj.branch_id) IN %s"
            params_open.append(tuple(branch_ids_to_filter))
            params_period.append(tuple(branch_ids_to_filter))

        # Categorization SQL logic:
        # 1) Card: journal name/code contains card/pos or line contains card
        # 2) UPI: journal name/code contains upi/gpay/phonepe or line contains upi
        # 3) Cash: journal type is cash or name contains cash
        # 4) Bank: journal type is bank (default)
        cat_expression = """
            CASE 
                WHEN lower(aj.name::text) LIKE '%%card%%' OR lower(aj.code::text) LIKE '%%card%%' 
                     OR lower(COALESCE(aml.name, '')) LIKE '%%card%%' 
                     OR lower(COALESCE(aml.ref, '')) LIKE '%%card%%' THEN 'card'
                WHEN lower(aj.name::text) LIKE '%%upi%%' OR lower(aj.code::text) LIKE '%%upi%%' 
                     OR lower(aj.name::text) LIKE '%%gpay%%' OR lower(aj.name::text) LIKE '%%phonepe%%'
                     OR lower(COALESCE(aml.name, '')) LIKE '%%upi%%' 
                     OR lower(COALESCE(aml.ref, '')) LIKE '%%upi%%' THEN 'upi'
                WHEN aj.type = 'cash' OR lower(aj.name::text) LIKE '%%cash%%' THEN 'cash'
                ELSE 'bank'
            END
        """

        # 1. Opening balance query (date < date_from)
        open_sql = f"""
            SELECT 
                {cat_expression} as cat,
                aj.id as journal_id,
                COALESCE(aj.name->>'en_US', aj.name::text) as journal_name,
                aj.code as journal_code,
                COALESCE(rb.name, 'All / Shared') as branch_name,
                COALESCE(SUM(aml.debit - aml.credit), 0) as opening
            FROM account_move_line aml
            JOIN account_journal aj ON aml.journal_id = aj.id
            JOIN account_account aa ON aml.account_id = aa.id
            LEFT JOIN account_move am ON aml.move_id = am.id
            LEFT JOIN res_branch rb ON COALESCE(aml.branch_id, am.branch_id, aj.branch_id) = rb.id
            WHERE aml.parent_state = 'posted'
              AND aml.account_id IN %s
              AND aj.type IN ('bank', 'cash')
              AND aml.date < %s
              AND (
                  aa.account_type = 'asset_cash'
                  OR aa.id = aj.default_account_id
                  OR aml.reconciled = false
              )
              {branch_clause}
            GROUP BY cat, aj.id, journal_name, aj.code, branch_name
        """
        self.env.cr.execute(open_sql, params_open)
        open_rows = self.env.cr.fetchall()

        # 2. Period movement query (date_from <= date <= date_to)
        period_sql = f"""
            SELECT 
                {cat_expression} as cat,
                aj.id as journal_id,
                COALESCE(aj.name->>'en_US', aj.name::text) as journal_name,
                aj.code as journal_code,
                COALESCE(rb.name, 'All / Shared') as branch_name,
                COALESCE(SUM(aml.debit), 0) as debit,
                COALESCE(SUM(aml.credit), 0) as credit,
                COUNT(aml.id) as line_count
            FROM account_move_line aml
            JOIN account_journal aj ON aml.journal_id = aj.id
            JOIN account_account aa ON aml.account_id = aa.id
            LEFT JOIN account_move am ON aml.move_id = am.id
            LEFT JOIN res_branch rb ON COALESCE(aml.branch_id, am.branch_id, aj.branch_id) = rb.id
            WHERE aml.parent_state = 'posted'
              AND aml.account_id IN %s
              AND aj.type IN ('bank', 'cash')
              AND aml.date >= %s AND aml.date <= %s
              AND (
                  aa.account_type = 'asset_cash'
                  OR aa.id = aj.default_account_id
                  OR aml.reconciled = false
              )
              {branch_clause}
            GROUP BY cat, aj.id, journal_name, aj.code, branch_name
        """
        self.env.cr.execute(period_sql, params_period)
        period_rows = self.env.cr.fetchall()

        # Build Category structure
        categories = {
            'bank': {
                'key': 'bank',
                'name': 'Bank Balance',
                'icon': 'fa-university',
                'color': '#3b82f6',
                'gradient': 'linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%)',
                'accent': '#60a5fa',
                'opening': 0.0,
                'debit': 0.0,
                'credit': 0.0,
                'closing': 0.0,
                'line_count': 0,
                'journals': {},
            },
            'cash': {
                'key': 'cash',
                'name': 'Cash Balance',
                'icon': 'fa-money',
                'color': '#10b981',
                'gradient': 'linear-gradient(135deg, #065f46 0%, #10b981 100%)',
                'accent': '#34d399',
                'opening': 0.0,
                'debit': 0.0,
                'credit': 0.0,
                'closing': 0.0,
                'line_count': 0,
                'journals': {},
            },
            'card': {
                'key': 'card',
                'name': 'Card Balance',
                'icon': 'fa-credit-card',
                'color': '#8b5cf6',
                'gradient': 'linear-gradient(135deg, #4c1d95 0%, #8b5cf6 100%)',
                'accent': '#a78bfa',
                'opening': 0.0,
                'debit': 0.0,
                'credit': 0.0,
                'closing': 0.0,
                'line_count': 0,
                'journals': {},
            },
            'upi': {
                'key': 'upi',
                'name': 'UPI Balance',
                'icon': 'fa-qrcode',
                'color': '#f59e0b',
                'gradient': 'linear-gradient(135deg, #78350f 0%, #f59e0b 100%)',
                'accent': '#fbbf24',
                'opening': 0.0,
                'debit': 0.0,
                'credit': 0.0,
                'closing': 0.0,
                'line_count': 0,
                'journals': {},
            },
        }

        # Populate opening
        for cat, j_id, j_name, j_code, b_name, opening in open_rows:
            if cat not in categories:
                cat = 'bank'
            c_data = categories[cat]
            c_data['opening'] += float(opening or 0.0)
            if j_id not in c_data['journals']:
                c_data['journals'][j_id] = {
                    'id': j_id,
                    'name': j_name,
                    'code': j_code,
                    'branch_name': b_name,
                    'opening': 0.0,
                    'debit': 0.0,
                    'credit': 0.0,
                    'closing': 0.0,
                    'line_count': 0,
                }
            c_data['journals'][j_id]['opening'] += float(opening or 0.0)

        # Populate period movements
        for cat, j_id, j_name, j_code, b_name, debit, credit, count in period_rows:
            if cat not in categories:
                cat = 'bank'
            c_data = categories[cat]
            c_data['debit'] += float(debit or 0.0)
            c_data['credit'] += float(credit or 0.0)
            c_data['line_count'] += count
            if j_id not in c_data['journals']:
                c_data['journals'][j_id] = {
                    'id': j_id,
                    'name': j_name,
                    'code': j_code,
                    'branch_name': b_name,
                    'opening': 0.0,
                    'debit': 0.0,
                    'credit': 0.0,
                    'closing': 0.0,
                    'line_count': 0,
                }
            c_data['journals'][j_id]['debit'] += float(debit or 0.0)
            c_data['journals'][j_id]['credit'] += float(credit or 0.0)
            c_data['journals'][j_id]['line_count'] += count

        # Compute closing balances and prepare journal lists
        total = {
            'opening': 0.0,
            'debit': 0.0,
            'credit': 0.0,
            'closing': 0.0,
            'line_count': 0,
        }

        for cat_key, c_data in categories.items():
            c_data['closing'] = round(c_data['opening'] + c_data['debit'] - c_data['credit'], 2)
            c_data['opening'] = round(c_data['opening'], 2)
            c_data['debit'] = round(c_data['debit'], 2)
            c_data['credit'] = round(c_data['credit'], 2)

            total['opening'] += c_data['opening']
            total['debit'] += c_data['debit']
            total['credit'] += c_data['credit']
            total['closing'] += c_data['closing']
            total['line_count'] += c_data['line_count']

            # Convert journals dict to sorted list
            journal_list = list(c_data['journals'].values())
            for j in journal_list:
                j['closing'] = round(j['opening'] + j['debit'] - j['credit'], 2)
                j['opening'] = round(j['opening'], 2)
                j['debit'] = round(j['debit'], 2)
                j['credit'] = round(j['credit'], 2)
            journal_list.sort(key=lambda x: abs(x['closing']), reverse=True)
            c_data['journals_list'] = journal_list
            del c_data['journals']

        total['opening'] = round(total['opening'], 2)
        total['debit'] = round(total['debit'], 2)
        total['credit'] = round(total['credit'], 2)
        total['closing'] = round(total['closing'], 2)

        # Selected branch name for display
        selected_branch_name = "All Branches"
        if branch_ids_to_filter and len(branch_ids_to_filter) == 1:
            branch_rec = self.env['res.branch'].browse(branch_ids_to_filter[0])
            if branch_rec.exists():
                selected_branch_name = branch_rec.name

        return {
            'categories': categories,
            'total': total,
            'selected_branch_id': branch_id or 'all',
            'selected_branch_name': selected_branch_name,
            'is_branch_editable': self._is_admin_user(),
            'date_from': date_from,
            'date_to': date_to,
            'currency_symbol': self.env.company.currency_id.symbol or '₹',
        }

    @api.model
    def get_transaction_lines(self, branch_id=None, date_from=None, date_to=None, category=None, journal_id=None, limit=100, offset=0, search_query=None):
        """Fetch paginated transaction lines with detailed info."""
        today = fields.Date.today()
        if not date_from:
            date_from = today.strftime('%Y-%m-%d')
        if not date_to:
            date_to = today.strftime('%Y-%m-%d')

        allowed_branch_ids = self._get_allowed_branch_ids()
        if allowed_branch_ids is not None:
            if not branch_id or branch_id == 'all':
                branch_ids_to_filter = allowed_branch_ids
            else:
                try:
                    bid = int(branch_id)
                    branch_ids_to_filter = [bid] if bid in allowed_branch_ids else allowed_branch_ids
                except (ValueError, TypeError):
                    branch_ids_to_filter = allowed_branch_ids
        else:
            if branch_id and branch_id != 'all':
                try:
                    branch_ids_to_filter = [int(branch_id)]
                except (ValueError, TypeError):
                    branch_ids_to_filter = None
            else:
                branch_ids_to_filter = None

        liquidity_acc_ids = self._get_liquidity_account_ids()
        if not liquidity_acc_ids:
            return {'lines': [], 'total_count': 0}

        where_clauses = [
            "aml.parent_state = 'posted'",
            "aml.account_id IN %s",
            "aj.type IN ('bank', 'cash')",
            "aml.date >= %s",
            "aml.date <= %s",
            "(aa.account_type = 'asset_cash' OR aa.id = aj.default_account_id OR aml.reconciled = false)",
        ]
        params = [tuple(liquidity_acc_ids), date_from, date_to]

        if branch_ids_to_filter:
            where_clauses.append("COALESCE(aml.branch_id, am.branch_id, aj.branch_id) IN %s")
            params.append(tuple(branch_ids_to_filter))

        if journal_id:
            where_clauses.append("aj.id = %s")
            params.append(int(journal_id))

        cat_expression = """
            CASE 
                WHEN lower(aj.name::text) LIKE '%%card%%' OR lower(aj.code::text) LIKE '%%card%%' 
                     OR lower(COALESCE(aml.name, '')) LIKE '%%card%%' 
                     OR lower(COALESCE(aml.ref, '')) LIKE '%%card%%' THEN 'card'
                WHEN lower(aj.name::text) LIKE '%%upi%%' OR lower(aj.code::text) LIKE '%%upi%%' 
                     OR lower(aj.name::text) LIKE '%%gpay%%' OR lower(aj.name::text) LIKE '%%phonepe%%'
                     OR lower(COALESCE(aml.name, '')) LIKE '%%upi%%' 
                     OR lower(COALESCE(aml.ref, '')) LIKE '%%upi%%' THEN 'upi'
                WHEN aj.type = 'cash' OR lower(aj.name::text) LIKE '%%cash%%' THEN 'cash'
                ELSE 'bank'
            END
        """

        if category and category in ('bank', 'cash', 'card', 'upi'):
            where_clauses.append(f"({cat_expression}) = %s")
            params.append(category)

        if search_query:
            query_pattern = f"%{search_query.strip().lower()}%"
            where_clauses.append("""
                (lower(am.name) LIKE %s 
                 OR lower(COALESCE(aml.name, '')) LIKE %s 
                 OR lower(COALESCE(aml.ref, '')) LIKE %s 
                 OR lower(COALESCE(rp.name, '')) LIKE %s 
                 OR lower(COALESCE(aj.name->>'en_US', aj.name::text)) LIKE %s)
            """)
            params.extend([query_pattern] * 5)

        where_sql = " AND ".join(where_clauses)

        # Count total
        count_sql = f"""
            SELECT COUNT(aml.id)
            FROM account_move_line aml
            JOIN account_journal aj ON aml.journal_id = aj.id
            JOIN account_account aa ON aml.account_id = aa.id
            LEFT JOIN account_move am ON aml.move_id = am.id
            LEFT JOIN res_partner rp ON aml.partner_id = rp.id
            WHERE {where_sql}
        """
        self.env.cr.execute(count_sql, params)
        total_count = self.env.cr.fetchone()[0]

        # Fetch lines
        select_sql = f"""
            SELECT 
                aml.id,
                aml.date,
                am.id as move_id,
                am.name as move_name,
                COALESCE(aml.ref, am.ref, '') as ref,
                COALESCE(aml.name, '') as label,
                COALESCE(rp.name, '') as partner_name,
                COALESCE(aj.name->>'en_US', aj.name::text) as journal_name,
                aj.code as journal_code,
                COALESCE(rb.name, 'All / Shared') as branch_name,
                ({cat_expression}) as category,
                aml.debit,
                aml.credit
            FROM account_move_line aml
            JOIN account_journal aj ON aml.journal_id = aj.id
            JOIN account_account aa ON aml.account_id = aa.id
            LEFT JOIN account_move am ON aml.move_id = am.id
            LEFT JOIN res_branch rb ON COALESCE(aml.branch_id, am.branch_id, aj.branch_id) = rb.id
            LEFT JOIN res_partner rp ON aml.partner_id = rp.id
            WHERE {where_sql}
            ORDER BY aml.date DESC, aml.id DESC
            LIMIT %s OFFSET %s
        """
        fetch_params = params + [limit, offset]
        self.env.cr.execute(select_sql, fetch_params)
        raw_rows = self.env.cr.fetchall()

        lines = []
        for r in raw_rows:
            lines.append({
                'id': r[0],
                'date': r[1].strftime('%d-%m-%Y') if r[1] else '',
                'move_id': r[2],
                'move_name': r[3] or '/',
                'ref': r[4] or '',
                'label': r[5] or '',
                'partner_name': r[6] or '',
                'journal_name': r[7] or '',
                'journal_code': r[8] or '',
                'branch_name': r[9] or '',
                'category': r[10] or 'bank',
                'debit': float(r[11] or 0.0),
                'credit': float(r[12] or 0.0),
                'net': float((r[11] or 0.0) - (r[12] or 0.0)),
            })

        return {
            'lines': lines,
            'total_count': total_count,
            'limit': limit,
            'offset': offset,
        }
