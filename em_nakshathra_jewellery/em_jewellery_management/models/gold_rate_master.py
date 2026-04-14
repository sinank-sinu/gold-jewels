from odoo import models, fields, api


class GoldRateMaster(models.Model):
    _name = 'gold.rate.master'
    _description = 'Gold Rate Master'
    _order = 'date desc'

    name = fields.Char(
        string='Reference',
        compute='_compute_name',
        store=True
    )
    rate_type = fields.Selection(
        [
            ('purchase', 'Purchase'),
            ('sale', 'Sale'),
            ('old_gold', 'Old Gold'),
        ],
        string='Rate Type',
        required=True,
        default='purchase'
    )

    date = fields.Date(
        string='Rate Date',
        required=True,
        default=fields.Date.context_today
    )

    rate_per_gram = fields.Float(
        string='Gold Rate / Gram',
        required=True
    )

    board_rate = fields.Float(
        string='Board Rate',
        required=True
    )

    active = fields.Boolean(
        string='Active',
        default=False
    )
    purity_id = fields.Many2one('gold.purity', string="Purity")
    product_label_id = fields.Many2one(
        'product.label',
        string='Product Label',
    )
    # from jafar side
    fine_rate = fields.Float(string="Fine Rate")

    @api.onchange('fine_rate')
    def _onchange_fine_rate(self):
        for record in self:
            if record.active:
                labels = self.env['product.label'].search([
                    ('purity_id', '=', record.purity_id.id),
                    ('active', '=', True)
                ])
                for label in labels:
                    label.purchase_price_per_gram = record.fine_rate



    @api.depends('date', 'rate_per_gram')
    def _compute_name(self):
        for rec in self:
            rec.name = f"Gold Rate {rec.date} - {rec.rate_per_gram}"


    def action_set_active_rate(self):
        self.ensure_one()
        self.search([('id', '!=', self.id),('purity_id','=',self.purity_id.id)]).write({'active': False})
        self.active = True

    def action_log_rate_update(self):
        self.ensure_one()
        self.env['gold.rate.update.log'].create({
            'rate_per_gram': self.rate_per_gram,
            'board_rate': self.board_rate,
            'purity_id': self.purity_id.id,
            'master_id': self.id,
        })


class GoldRateUpdateLog(models.Model):
    _name = 'gold.rate.update.log'
    _description = 'Gold Rate Update Log'
    _order = 'rate_datetime desc'

    rate_datetime = fields.Datetime(
        string='Updated At',
        default=fields.Datetime.now,
        required=True
    )

    rate_per_gram = fields.Float(required=True)
    board_rate = fields.Float(required=True)

    purity_id = fields.Many2one('gold.purity', required=True)
    master_id = fields.Many2one(
        'gold.rate.master',
        string='Gold Rate'
    )
    rate_type = fields.Selection(
        [
            ('purchase', 'Purchase'),
            ('sale', 'Sale'),
            ('old_gold', 'Old Gold'),
        ],
        string='Rate Type',
        required=True,
        default='purchase'
    )




