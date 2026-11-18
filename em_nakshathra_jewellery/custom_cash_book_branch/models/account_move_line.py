# -*- coding: utf-8 -*-
from datetime import date, datetime
from decimal import Decimal

from odoo import api, fields, models
from odoo.osv import expression


def _to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    running_balance = fields.Monetary(
        string='Running Balance',
        compute='_compute_running_balance',
        currency_field='company_currency_id',
        exportable=False,
        help="Chronological running balance accumulating line balances from oldest to newest, including prior-date opening balance when filtered by a start date.",
    )

    @api.model
    def _parse_domain_ast(self, tokens):
        """Parse a normalized Odoo prefix domain into an AST."""
        def _parse(idx):
            token = tokens[idx]
            if token == expression.NOT_OPERATOR:
                child, next_idx = _parse(idx + 1)
                return (expression.NOT_OPERATOR, child), next_idx
            if token in (expression.AND_OPERATOR, expression.OR_OPERATOR):
                left, next_idx = _parse(idx + 1)
                right, next_idx = _parse(next_idx)
                return (token, left, right), next_idx
            return ('LEAF', token), idx + 1

        ast, _ = _parse(0)
        return ast

    @api.model
    def _serialize_domain_ast(self, node):
        """Serialize a domain AST node back into a prefix token list."""
        kind = node[0]
        if kind == 'LEAF':
            return [node[1]]
        if kind == expression.NOT_OPERATOR:
            return [expression.NOT_OPERATOR] + self._serialize_domain_ast(node[1])
        return [kind] + self._serialize_domain_ast(node[1]) + self._serialize_domain_ast(node[2])

    @api.model
    def _flatten_and_ast(self, node):
        """Flatten top-level '&' AST nodes into a list of conjunct nodes."""
        if node[0] == expression.AND_OPERATOR:
            return self._flatten_and_ast(node[1]) + self._flatten_and_ast(node[2])
        return [node]

    @api.model
    def _coerce_domain_date(self, value):
        """Convert a domain date operand to a datetime.date, or None if invalid."""
        if isinstance(value, bool) or value is None:
            return None
        try:
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            return fields.Date.to_date(value)
        except (ValueError, TypeError):
            return None

    @api.model
    def _extract_date_lower_bound(self, node):
        """Return (is_pure_date_expr, lower_bound) for a domain AST node.

        ``lower_bound`` is ``None`` when unbounded below, or ``(min_date, is_strict_gt)``.
        """
        kind = node[0]
        if kind == 'LEAF':
            leaf = node[1]
            if not isinstance(leaf, (list, tuple)) or len(leaf) != 3:
                return False, None
            field, op, val = leaf
            if field not in ('date', 'move_id.date'):
                return False, None
            if op in ('>=', '>', '='):
                parsed = self._coerce_domain_date(val)
                if not parsed:
                    return False, None
                return True, (parsed, op == '>')
            if op in ('<=', '<'):
                parsed = self._coerce_domain_date(val)
                if not parsed:
                    return False, None
                return True, None
            if op == 'in' and isinstance(val, (list, tuple)) and val:
                parsed_dates = [self._coerce_domain_date(v) for v in val]
                if all(parsed_dates):
                    return True, (min(parsed_dates), False)
                return False, None
            return False, None

        if kind == expression.AND_OPERATOR:
            l_pure, l_lb = self._extract_date_lower_bound(node[1])
            r_pure, r_lb = self._extract_date_lower_bound(node[2])
            if not (l_pure and r_pure):
                return False, None
            if l_lb is None:
                return True, r_lb
            if r_lb is None:
                return True, l_lb
            return True, max(l_lb, r_lb)

        if kind == expression.OR_OPERATOR:
            l_pure, l_lb = self._extract_date_lower_bound(node[1])
            r_pure, r_lb = self._extract_date_lower_bound(node[2])
            if not (l_pure and r_pure):
                return False, None
            if l_lb is None or r_lb is None:
                return True, None
            return True, min(l_lb, r_lb)

        return False, None

    @api.model
    def _get_running_balance_opening_domain(self, domain):
        """Build the prior-period domain strictly before the filtered start date.

        Returns ``None`` if the domain imposes no lower bound on ``date``.
        """
        if not domain:
            return None
        normalized = expression.normalize_domain(list(domain))
        ast = self._parse_domain_ast(normalized)
        conjuncts = self._flatten_and_ast(ast)

        base_domains = []
        effective_lb = None
        for conjunct in conjuncts:
            is_pure, lb = self._extract_date_lower_bound(conjunct)
            if is_pure and lb is not None:
                effective_lb = lb if effective_lb is None else max(effective_lb, lb)
            else:
                base_domains.append(self._serialize_domain_ast(conjunct))

        if effective_lb is None:
            return None

        min_date, is_strict_gt = effective_lb
        prior_op = '<=' if is_strict_gt else '<'
        return expression.AND(base_domains + [[('date', prior_op, min_date)]])

    @api.model
    def _get_running_balance_opening_amount(self, domain):
        """Compute the cumulative balance prior to the domain's start date."""
        opening_domain = self._get_running_balance_opening_domain(domain)
        if opening_domain is None or expression.is_false(self, opening_domain):
            return Decimal('0')
        opening_query = self._where_calc(opening_domain)
        self._apply_ir_rules(opening_query, 'read')
        open_from, open_where, open_params = opening_query.get_sql()
        open_sql = f"""
            SELECT COALESCE(SUM(account_move_line.balance), 0.0)
            FROM {open_from}
            WHERE {open_where or 'TRUE'}
        """
        self.env.cr.execute(open_sql, open_params or None)
        row = self.env.cr.fetchone()
        return _to_decimal(row[0] if row else 0)

    @api.depends_context('order_cumulated_balance', 'domain_cumulated_balance', 'allowed_company_ids')
    def _compute_running_balance(self):
        """Compute chronological cumulative running balance including prior opening balance."""
        if not self.ids:
            self.running_balance = 0.0
            return

        order_by = self.env.context.get('order_cumulated_balance')
        if not order_by or any(not isinstance(record_id, int) for record_id in self.ids):
            running = Decimal('0')
            for record in self.sorted(key=lambda r: (r.date or date.min, r.move_name or '', r.id if isinstance(r.id, int) else 0)):
                running += _to_decimal(record.balance)
                record.running_balance = float(running)
            return

        domain = list(self.env.context.get('domain_cumulated_balance') or [])
        opening_balance = self._get_running_balance_opening_amount(domain)

        query = self._where_calc(domain)
        self._apply_ir_rules(query, 'read')
        sql_order = self._order_to_sql('date asc, move_name asc, id asc', query, reverse=False)
        order_string = self.env.cr.mogrify(sql_order).decode()
        from_clause, where_clause, where_clause_params = query.get_sql()
        sql = f"""
            SELECT aml.id, aml.running_balance
            FROM (
                SELECT
                    account_move_line.id,
                    SUM(account_move_line.balance) OVER (
                        ORDER BY {order_string}
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS running_balance
                FROM {from_clause}
                WHERE {where_clause or 'TRUE'}
            ) aml
            WHERE aml.id = ANY(%s)
        """
        self.env.cr.execute(sql, where_clause_params + [self.ids])
        result = dict(self.env.cr.fetchall())
        for record in self:
            record.running_balance = float(opening_balance + _to_decimal(result.get(record.id, 0)))

