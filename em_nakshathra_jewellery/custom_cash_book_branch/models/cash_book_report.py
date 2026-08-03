# -*- coding: utf-8 -*-
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models
from odoo.tools import date_utils

class CashBookReport(models.TransientModel):
    _inherit = 'cash.book.report'

    def _get_user_allowed_branch_ids(self):
        """
        Returns allowed branch IDs for the current user.
        If user is Billing Staff (and not Manager/Admin), restrict strictly to assigned branch(es).
        Otherwise returns None (unrestricted).
        """
        user = self.env.user
        is_billing_staff = user.has_group('em_jewellery_management.group_jewellery_billing_staff')
        is_manager = user.has_group('em_jewellery_management.group_jewellery_manager') or user.has_group('base.group_system')

        if is_billing_staff and not is_manager:
            if hasattr(user, 'branch_ids') and user.branch_ids:
                return user.branch_ids.ids
            elif hasattr(user, 'branch_id') and user.branch_id:
                return [user.branch_id.id]
            return [-1]  # No branch assigned -> return non-matching ID
        return None

    def _summary_from_filters(self, partner_id=None, date_range=None, account_list=None, options=None, branch_list=None):
        allowed_branch_ids = self._get_user_allowed_branch_ids()
        if allowed_branch_ids is not None:
            if branch_list:
                branch_list = [b for b in branch_list if b in allowed_branch_ids]
            else:
                branch_list = allowed_branch_ids
        return super(CashBookReport, self)._summary_from_filters(
            partner_id=partner_id, date_range=date_range, account_list=account_list, options=options, branch_list=branch_list
        )

    @api.model
    def get_account_lines(self, account_id, journal_id=None, partner_id=None,
                          date_range=None, options=None, branch_ids=None,
                          limit=500, offset=0, known_total=None):
        allowed_branch_ids = self._get_user_allowed_branch_ids()
        if allowed_branch_ids is not None:
            if branch_ids:
                branch_ids = [b for b in branch_ids if b in allowed_branch_ids]
            else:
                branch_ids = allowed_branch_ids
        return super(CashBookReport, self).get_account_lines(
            account_id=account_id, journal_id=journal_id, partner_id=partner_id,
            date_range=date_range, options=options, branch_ids=branch_ids,
            limit=limit, offset=offset, known_total=known_total
        )

    @api.model
    def view_report(self):
        res = super(CashBookReport, self).view_report()

        journals = self.env['account.journal'].search([('type', '=', 'cash')])
        account_move_lines = self.env['account.move.line'].search([
            ('parent_state', '=', 'posted'),
            ('journal_id', 'in', journals.ids)
        ])

        for account_key in list(res.keys()):
            if account_key in ['move_lines_total', 'accounts']:
                continue

            for raw_data in res[account_key]:
                line_id = raw_data.get('id')
                if line_id:
                    line = account_move_lines.browse(line_id)
                    if line.move_id and hasattr(line.move_id, 'branch_id') and line.move_id.branch_id:
                        raw_data['branch_id'] = [line.move_id.branch_id.id, line.move_id.branch_id.name]
                    else:
                        raw_data['branch_id'] = False

        allowed_branch_ids = self._get_user_allowed_branch_ids()
        if allowed_branch_ids is not None:
            branches = self.env['res.branch'].search([('id', 'in', allowed_branch_ids)]).read(['id', 'name'])
        else:
            branches = self.env['res.branch'].search([]).read(['id', 'name'])
        res['branches'] = branches
        return res

    @api.model
    def get_filter_values(self, partner_id, data_range, account_list, options, branch_list=None):
        res = self._summary_from_filters(partner_id, data_range, account_list, options, branch_list)
        allowed_branch_ids = self._get_user_allowed_branch_ids()
        if allowed_branch_ids is not None:
            branches = self.env['res.branch'].search([('id', 'in', allowed_branch_ids)]).read(['id', 'name'])
        else:
            branches = self.env['res.branch'].search([]).read(['id', 'name'])
        res['branches'] = branches
        return res