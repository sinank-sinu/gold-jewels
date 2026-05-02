from odoo import models, fields, api

class JewelleryIssueVoucher(models.Model):
    _inherit = 'jewellery.issue.voucher'

    job_type_selection = fields.Selection([
        ('gold_only', 'Gold Only'),
        ('gold_alloy', 'Gold + Alloy')
    ], string='Job Type')

    def action_done(self):
        res = super().action_done()
        for line in self.line_ids:
            if not self.is_refinery:
                # Job Work Report synchronization
                self.env['job.work.report'].create({
                    'date': self.confirmed_date or fields.Date.today(),
                    'voucher_name': self.name,
                    'type': 'issue',
                    'partner_id': self.job_worker_id.id,
                    'job_type': self.job_type_selection,
                    'gross_weight': line.gross_weight,
                    'stock_in': line.fine_weight, # Issue is stock_in for worker's account
                    'purity_id': line.purity_id.id,
                })
            else:
                # Refinery Lab Report synchronization
                self.env['refinery.lab.report'].create({
                    'date': self.confirmed_date or fields.Date.today(),
                    'voucher_name': self.name,
                    'type': 'issue',
                    'branch_id': self.branch_id.id,
                    'refinery_id': self.refinery_id.id,
                    'purity_id': line.purity_id.id,
                    'issued_weight': line.issued_weight,
                    'net_weight': line.qty, # 'qty' is labeled as Net Weight in base model
                    'lab_weight': line.lab_weight,
                    'lab_purity': line.lab_purity,
                    'fine_weight': line.refinery_fine_weight + line.lab_fine_weight,
                    'fine_amount': line.fine_issue_amount,
                    'fine_gms_price': line.fine_gms_price,
                })
        return res
