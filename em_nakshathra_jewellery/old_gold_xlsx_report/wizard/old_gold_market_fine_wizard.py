# -*- coding: utf-8 -*-
from odoo import models, fields


class OldGoldMarketFineWizard(models.TransientModel):
    _name = 'old.gold.market.fine.wizard'
    _description = 'Old Gold Purchase vs Market Fine Report Wizard'

    date_from = fields.Date(string="From Date", required=True, default=fields.Date.context_today)
    date_to = fields.Date(string="To Date", required=True, default=fields.Date.context_today)
    branch_ids = fields.Many2many('res.branch', string="Branches")

    def action_print_report(self):
        return self.env.ref(
            'old_gold_xlsx_report.old_gold_market_fine_xlsx_report'
        ).report_action(self)
