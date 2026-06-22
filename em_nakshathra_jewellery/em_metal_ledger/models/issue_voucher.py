from odoo import models, fields, api
from odoo.exceptions import UserError

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
                    'branch_id': self.branch_id.id,
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

    def action_update_lab_purity(self):
        """Update lab_purity in the linked Refinery Lab Report records and
        recompute lab_fine_weight (lab_weight * lab_purity / 100)."""
        self.ensure_one()
        if not self.is_refinery:
            raise UserError("This action is only available for Refinery receive vouchers.")

        lab_reports = self.env['refinery.lab.report'].search([
            ('voucher_name', '=', self.name),
            ('type', '=', 'issue'),
        ])
        if not lab_reports:
            raise UserError(
                "No Refinery Lab Report records found for this voucher (%s). "
                "Please confirm the voucher first." % self.name
            )

        # Build a mapping: if there are multiple lines, match by order / purity.
        # For simplicity we update all matching lab report records using the
        # lab_purity from the first refinery line that has a lab_purity set.
        for report in lab_reports:
            # Try to find the matching receive voucher line by purity
            matching_line = self.line_ids.filtered(
                lambda l: l.purity_id.id == report.purity_id.id
            )
            if not matching_line:
                # Fall back to any line with a lab_purity value
                matching_line = self.line_ids.filtered(lambda l: l.lab_purity_id)

            if matching_line:
                line = matching_line[0]
                # Extract float percentage from the Many2one, or fallback to the manual float field
                new_purity = line.lab_purity_id.percentage if line.lab_purity_id else line.lab_purity
                
                report.write({
                    'lab_purity': new_purity,
                    'lab_weight': line.lab_weight,
                })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Lab Purity Updated',
                'message': 'Lab purity and lab fine weight have been updated in the Refinery Lab Report.',
                'type': 'success',
                'sticky': False,
            },
        }