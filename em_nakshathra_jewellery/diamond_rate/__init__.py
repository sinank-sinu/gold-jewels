# -*- coding: utf-8 -*-
from odoo import fields
from . import models

def post_init_hook(env):
    """Seed initial diamond rate matching 22CT(92) if none exists."""
    purity = env['gold.purity'].search([('name', '=', '22CT(92)')], limit=1)
    if not env['diamond.rate.master'].search([]):
        env['diamond.rate.master'].create({
            'date': fields.Date.context_today(env['diamond.rate.master']),
            'rate_type': 'sale',
            'rate_per_carat': 50000.0,
            'purity_id': purity.id if purity else False,
            'active': True,
        })

