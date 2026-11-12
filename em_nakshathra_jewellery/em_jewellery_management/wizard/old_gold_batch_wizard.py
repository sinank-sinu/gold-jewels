from odoo import models, fields, _
from odoo.exceptions import ValidationError


class OldGoldBatchWizard(models.TransientModel):
    _name = 'old.gold.batch.wizard'
    _description = 'Old Gold Batch Creation Wizard'

    branch_id = fields.Many2one(
        'res.branch',
        string="Branch",
        default=lambda self: self.env.user.branch_id.id,
    )
    start_date = fields.Datetime(string="Start Date & Time", required=True)
    end_date = fields.Datetime(string="End Date & Time", required=True)

    def action_create_batches(self):
        self.ensure_one()

        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError(_("From (Date & Time) cannot be after To (Date & Time)."))

        Batch = self.env['old.gold.batch']

        domain = [
            ('date', '>=', self.start_date),
            ('date', '<=', self.end_date),
            ('state', '=', 'done'),
        ]
        if self.branch_id:
            domain.append(('branch_id', '=', self.branch_id.id))

        ho_lines = self.env['old.gold.purchase'].search(domain)

        grouped = {}
        for rec in ho_lines:
            for line in rec.old_gold_line_ids:
                batch_date = rec.date.date() if hasattr(rec.date, 'date') else rec.date
                branch_rec = line.branch_id or rec.branch_id or self.branch_id or self.env.user.branch_id
                key = (
                    batch_date,
                    branch_rec.id if branch_rec else False,
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

        if not grouped:
            raise ValidationError(_("No verified old gold purchases found for the selected criteria."))

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
                'line_ids': [(6, 0, [l.id for l in data['lines']])],
            })

        ho_lines.write({'state': 'batched'})

        return {'type': 'ir.actions.act_window_close'}
