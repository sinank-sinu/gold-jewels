# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class DiamondRateMaster(models.Model):
    _name = 'diamond.rate.master'
    _description = 'Diamond Rate Master'
    _order = 'date desc, id desc'

    @api.model
    def _default_purity_id(self):
        purity = self.env['gold.purity'].search([('name', '=', '18KTD(75.5)')], limit=1)
        return purity.id if purity else False

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
        default='sale'
    )
    date = fields.Date(
        string='Rate Date',
        required=True,
        default=fields.Date.context_today
    )
    rate_per_carat = fields.Float(
        string='Diamond Rate / Carat',
        required=True,
        digits=(16, 2)
    )
    board_rate = fields.Float(
        string='Board Rate',
        default=0.0
    )
    active = fields.Boolean(
        string='Active',
        default=True
    )
    purity_id = fields.Many2one(
        'gold.purity',
        string="Purity",
        default=_default_purity_id,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )
    log_ids = fields.One2many(
        'diamond.rate.update.log',
        'master_id',
        string='Rate Updates'
    )
    log_count = fields.Integer(
        string='Updates',
        compute='_compute_log_count'
    )

    @api.depends('log_ids')
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.log_ids)

    @api.depends('date', 'rate_per_carat', 'rate_type', 'purity_id')
    def _compute_name(self):
        for rec in self:
            purity_name = f" - {rec.purity_id.name}" if rec.purity_id else ""
            rec.name = f"Diamond Rate {rec.date} - {rec.rate_per_carat}{purity_name}"

    def action_set_active_rate(self):
        self.ensure_one()
        domain = [('id', '!=', self.id), ('rate_type', '=', self.rate_type)]
        if self.purity_id:
            domain.append(('purity_id', '=', self.purity_id.id))
        else:
            domain.append(('purity_id', '=', False))
        self.search(domain).write({'active': False})
        self.active = True

    def action_log_rate_update(self):
        self.ensure_one()
        self.env['diamond.rate.update.log'].create({
            'master_id': self.id,
            'rate_per_carat': self.rate_per_carat,
            'board_rate': self.board_rate,
            'rate_type': self.rate_type,
            'purity_id': self.purity_id.id if self.purity_id else False,
            'rate_datetime': fields.Datetime.now(),
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Diamond Rate Updated'),
                'message': _('Diamond rate of %s has been logged.') % self.rate_per_carat,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_update_logs(self):
        self.ensure_one()
        return {
            'name': _('Rate Updates'),
            'type': 'ir.actions.act_window',
            'res_model': 'diamond.rate.update.log',
            'view_mode': 'tree,form',
            'domain': [('master_id', '=', self.id)],
            'context': {'default_master_id': self.id},
        }


class DiamondRateUpdateLog(models.Model):
    _name = 'diamond.rate.update.log'
    _description = 'Diamond Rate Update Log'
    _order = 'rate_datetime desc'

    rate_datetime = fields.Datetime(
        string='Updated At',
        default=fields.Datetime.now,
        required=True
    )
    rate_per_carat = fields.Float(
        string='Diamond Rate / Carat',
        required=True,
        digits=(16, 2)
    )
    board_rate = fields.Float(
        string='Board Rate',
        default=0.0
    )
    purity_id = fields.Many2one('gold.purity', string='Purity')
    master_id = fields.Many2one(
        'diamond.rate.master',
        string='Diamond Rate',
        ondelete='cascade'
    )
    rate_type = fields.Selection(
        [
            ('purchase', 'Purchase'),
            ('sale', 'Sale'),
            ('old_gold', 'Old Gold'),
        ],
        string='Rate Type',
        required=True,
        default='sale'
    )
    user_id = fields.Many2one(
        'res.users',
        string='Updated By',
        default=lambda self: self.env.user
    )
