from odoo.exceptions import ValidationError

from odoo import models, fields,api,_

class OldGoldBatch(models.Model):
    _inherit = 'old.gold.batch'

    refinery_issue_id = fields.Many2one(
            'old.gold.refinery.issue',
            string="Refinery Issue",
            readonly=True
        )
    # def action_create_refinery_issue(self):
    #     RefineryIssue = self.env['old.gold.refinery.issue']
    #     RefineryIssueLine = self.env['old.gold.refinery.issue.line']
    #
    #     # keep only batches which are NOT already linked
    #     batches = self.filtered(lambda b: not b.refinery_issue_id)
    #
    #     if not batches:
    #         return True
    #
    #     # Create single refinery issue
    #     # Use the first batch's branch_id — self may be a multi-record set
    #     # which would raise "Expected singleton" if accessed directly.
    #     issue = RefineryIssue.create({
    #         'issue_date': fields.Date.context_today(self),
    #         'branch_id': batches[0].branch_id.id,
    #     })
    #
    #     # Group by purity (weight + purchase amount)
    #     purity_map = {}
    #
    #     for batch in batches:
    #         purity_id = batch.purity_id.id
    #
    #         if purity_id not in purity_map:
    #             purity_map[purity_id] = {
    #                 'weight': 0.0,
    #                 'amount': 0.0,
    #             }
    #
    #         purity_map[purity_id]['weight'] += batch.total_grams
    #         purity_map[purity_id]['amount'] += batch.total_purchase_amount
    #
    #     # Create refinery issue lines
    #     for purity_id, values in purity_map.items():
    #         RefineryIssueLine.create({
    #             'issue_id': issue.id,
    #             'purity_id': purity_id,
    #             'issue_weight': values['weight'],
    #             'purchase_amount': values['amount'],  # 👈 make sure field exists
    #         })
    #
    #     # Link processed batches
    #     batches.write({'refinery_issue_id': issue.id})
    #
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'old.gold.refinery.issue',
    #         'view_mode': 'form',
    #         'res_id': issue.id,
    #     }