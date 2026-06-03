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


