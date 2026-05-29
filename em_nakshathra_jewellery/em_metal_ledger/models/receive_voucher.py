from odoo import models, fields, api
from odoo.exceptions import UserError

class JewelleryReceiveVoucher(models.Model):
    _inherit = 'jewellery.receive.voucher'

    def action_done(self):
        res = super(JewelleryReceiveVoucher, self).action_done()
        for line in self.line_ids:
            if not self.is_refinery:
                # Job Work Report synchronization for Receipt
                self.env['job.work.report'].create({
                    'date': self.confirmed_date or fields.Date.today(),
                    'voucher_name': self.name,
                    'type': 'receive',
                    'partner_id': self.job_worker_id.id,
                    'job_type': self.job_type_selection,
                    'gross_weight': line.gross_weight,
                    'stock_out': line.total_fine, # Receipt is stock_out (worker's account reduces)
                    'purity_id': line.purity_id.id,
                })
            else:
                # Refinery Lab Report synchronization for Receipt
                self.env['refinery.lab.report'].create({
                    'date': self.confirmed_date or fields.Date.today(),
                    'voucher_name': self.name,
                    'type': 'receive',
                    'branch_id': self.branch_id.id,
                    'refinery_id': self.refinery_id.id,
                    'purity_id': line.purity_id.id,
                    'issued_weight': line.issue_voucher_line_id.issued_weight if line.issue_voucher_line_id else 0.0,
                    'net_weight': line.net_weight, # Use received net weight
                    'lab_weight': line.issue_voucher_line_id.lab_weight if line.issue_voucher_line_id else 0.0,
                    'lab_purity': line.lab_purity,
                    'fine_weight': line.fine_weight,
                    'fine_amount': line.total_receive_fine_amount,
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
            ('type', '=', 'receive'),
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
                lambda l: l.purity_id.id == report.purity_id.id and l.lab_purity
            )
            if not matching_line:
                # Fall back to any line with a lab_purity value
                matching_line = self.line_ids.filtered(lambda l: l.lab_purity)

            if matching_line:
                new_purity = matching_line[0].lab_purity
                report.write({'lab_purity': new_purity})
                # lab_fine_weight is a stored computed field and will be
                # recalculated automatically via _compute_lab_fine_weight.

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

