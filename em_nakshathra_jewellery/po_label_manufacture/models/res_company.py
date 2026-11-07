from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    transfer_manufacture_location_ids = fields.Many2many(
        'stock.location',
        'res_company_stock_location_transfer_mfg_rel',
        'company_id',
        'location_id',
        string="Transfer Manufacture Locations",
        domain="[('usage', '=', 'internal')]",
        help="Locations used for manufacturing orders created from internal transfers."
    )
