from odoo.exceptions import ValidationError

from odoo import models, fields,api,_

class OldGoldBatch(models.Model):
    _name = 'old.gold.batch'
    _description = 'Old Gold Batch'

    name = fields.Char(readonly=True)
    batch_date = fields.Date(required=True)

    branch_id = fields.Many2one(
        'res.branch',
        required=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='branch_id.company_id',
        store=True,
        readonly=True,
    )

    purity_id = fields.Many2one(
        'gold.purity',
        required=True
    )

    total_grams = fields.Float(readonly=True,digits=(16, 3))
    total_purchase_amount = fields.Float(readonly=True)
    refinery_issue_id = fields.Many2one(
            'old.gold.refinery.issue',
            string="Refinery Issue",
            readonly=True
        )
    mo_id = fields.Many2one('mrp.production', string="Manufacturing Order", readonly=True)
    line_ids = fields.One2many('sale.old.gold.line', 'batch_id', string="Lines")


    def action_create_refinery_issue(self):
        RefineryIssue = self.env['old.gold.refinery.issue']
        RefineryIssueLine = self.env['old.gold.refinery.issue.line']

        if not self:
            return True

        batches = self

        # Validation: Check if batches from different companies are selected together
        companies = batches.mapped('branch_id.company_id')
        if len(companies) > 1:
            raise ValidationError(
                _("Cannot create melting: Selected batches belong to different companies (%s). "
                  "Please remove batches belonging to other companies and choose batches from the same company branches.")
                % ", ".join(companies.mapped('name'))
            )

        # Validation: Check if chosen batches belong to another company than active company
        current_company = self.env.company
        other_company_batches = batches.filtered(lambda b: b.branch_id.company_id != current_company)
        if other_company_batches:
            other_branches = ", ".join(set(other_company_batches.mapped('branch_id.name')))
            other_companies = ", ".join(set(other_company_batches.mapped('branch_id.company_id.name')))
            raise ValidationError(
                _("Cannot create melting: Batches from another company branch were chosen (%s - %s). "
                  "Please remove them and choose batches from the same company branches (%s).")
                % (other_branches, other_companies, current_company.name)
            )
        target_company = companies[0]
        user_branch = self.env.user.branch_id
        issue_branch = user_branch if user_branch and user_branch.company_id == target_company else batches[0].branch_id

        # Create single refinery issue
        issue = RefineryIssue.create({
            'issue_date': fields.Date.context_today(self),
            'branch_id': issue_branch.id,
            'company_id': target_company.id,
        })

        # Group by purity (weight + purchase amount)
        purity_map = {}

        for batch in batches:
            purity_id = batch.purity_id.id

            if purity_id not in purity_map:
                purity_map[purity_id] = {
                    'weight': 0.0,
                    'amount': 0.0,
                }

            purity_map[purity_id]['weight'] += batch.total_grams
            purity_map[purity_id]['amount'] += batch.total_purchase_amount

        # Create refinery issue lines
        for purity_id, values in purity_map.items():
            purity = self.env['gold.purity'].browse(purity_id)
            is_diamond = purity.is_diamond_og if purity else False
            product = RefineryIssueLine._get_company_old_gold_product(
                target_company.id, is_diamond_og=is_diamond
            )
            RefineryIssueLine.create({
                'issue_id': issue.id,
                'purity_id': purity_id,
                'product_id': product.id if product else False,
                'issue_weight': values['weight'],
                'purchase_amount': values['amount'],  # 👈 make sure field exists
            })

        # Link processed batches
        batches.write({'refinery_issue_id': issue.id})

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'old.gold.refinery.issue',
            'view_mode': 'form',
            'res_id': issue.id,
        }
