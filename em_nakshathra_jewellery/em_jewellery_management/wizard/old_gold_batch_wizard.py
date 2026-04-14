from odoo import models, fields, _
from odoo.exceptions import ValidationError


class OldGoldBatchWizard(models.TransientModel):
    _name = 'old.gold.batch.wizard'
    _description = 'Old Gold Batch Creation Wizard'

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)

    def action_create_batches(self):
        self.ensure_one()

        Batch = self.env['old.gold.batch']

        ho_lines = self.env['old.gold.purchase'].search([
            ('date', '>=', self.start_date),
            ('date', '<=', self.end_date),
            ('state', '=', 'done'),
        ])

        grouped = {}
        for rec in ho_lines:
            for line in rec.old_gold_line_ids:
                key = (
                    rec.date,
                    line.branch_id.id,
                    line.verified_purity_id.id
                )

                grouped.setdefault(key, {
                    'lines': [],
                    'grams': 0.0,
                    'amount': 0.0,
                })

                grouped[key]['lines'].append(line)
                grouped[key]['grams'] += line.verified_net_weight
                grouped[key]['amount'] += line.amount

        for (date, branch_id, verified_purity_id), data in grouped.items():

            branch = self.env['res.branch'].browse(branch_id)
            purity = self.env['gold.purity'].browse(verified_purity_id)

            seq_name = f"{branch.branch_code}/{date.strftime('%Y%m%d')}/{purity.name}"

            batch = Batch.create({
                'name': seq_name,
                'batch_date': date,
                'branch_id': branch_id,
                'purity_id': verified_purity_id,
                'total_grams': data['grams'],
                'total_purchase_amount': data['amount'],
            })

        ho_lines.write({'state': 'batched'})

        return {'type': 'ir.actions.act_window_close'}
