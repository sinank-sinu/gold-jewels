from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class JewelleryReceiveVoucher(models.Model):
    _inherit = 'jewellery.receive.voucher'

    @api.model
    def create(self, vals):
        if vals.get('name', "New") == "New" or vals.get('name', _('New')) == _('New'):
            branch = self.env['res.branch'].browse(vals.get('branch_id')) if vals.get('branch_id') else self.env.user.branch_id
            if not branch or not branch.branch_code:
                raise ValidationError("Branch code is missing!")
            seq = self.env['ir.sequence'].next_by_code('jewellery.receive.voucher')
            if not seq:
                seq_rec = self.env['ir.sequence'].sudo().search([('code', '=', 'jewellery.receive.voucher')], limit=1)
                if seq_rec:
                    seq = seq_rec.next_by_id()
                else:
                    seq = self.env['ir.sequence'].sudo().create({
                        'name': 'Jewellery Receive Voucher',
                        'code': 'jewellery.receive.voucher',
                        'prefix': 'RV/',
                        'padding': 5,
                        'company_id': False,
                    }).next_by_id()
            if not seq:
                raise ValidationError("Sequence not working!")
            vals['name'] = f"{branch.branch_code}/{seq}"
        res = super().create(vals)
        return res