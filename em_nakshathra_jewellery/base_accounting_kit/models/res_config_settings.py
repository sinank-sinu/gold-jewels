# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    customer_credit_limit = fields.Boolean(string="Customer Credit Limit")

    use_anglo_saxon_accounting = fields.Boolean(
        string="Use Anglo-Saxon accounting", readonly=False,
        related='company_id.anglo_saxon_accounting')

    property_account_receivable_id = fields.Many2one(
        'account.account',
        string="Default Account Receivable",
        domain="[('account_type', '=', 'asset_receivable'), ('deprecated', '=', False), ('company_id', '=', company_id)]"
    )

    property_account_payable_id = fields.Many2one(
        'account.account',
        string="Default Account Payable",
        domain="[('account_type', '=', 'liability_payable'), ('deprecated', '=', False), ('company_id', '=', company_id)]"
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        params = self.env['ir.config_parameter'].sudo()
        customer_credit_limit = params.get_param('customer_credit_limit',
                                                 default=False)
        
        # Fetch default properties
        company = self.env.company
        Prop = self.env['ir.property'].sudo()
        receivable_prop = Prop.search([('name', '=', 'property_account_receivable_id'), ('company_id', 'in', [company.id, False]), ('res_id', '=', False)], limit=1)
        payable_prop = Prop.search([('name', '=', 'property_account_payable_id'), ('company_id', 'in', [company.id, False]), ('res_id', '=', False)], limit=1)
        
        receivable_id = False
        payable_id = False
        if receivable_prop and receivable_prop.value_reference and receivable_prop.value_reference.startswith('account.account,'):
            receivable_id = int(receivable_prop.value_reference.split(',')[1])
        if payable_prop and payable_prop.value_reference and payable_prop.value_reference.startswith('account.account,'):
            payable_id = int(payable_prop.value_reference.split(',')[1])

        res.update(
            customer_credit_limit=customer_credit_limit,
            property_account_receivable_id=receivable_id,
            property_account_payable_id=payable_id,
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        self.env['ir.config_parameter'].sudo().set_param(
            "customer_credit_limit",
            self.customer_credit_limit)
        
        company = self.env.company
        Prop = self.env['ir.property'].sudo()
        
        for field_name, value in [('property_account_receivable_id', self.property_account_receivable_id), 
                                  ('property_account_payable_id', self.property_account_payable_id)]:
            prop = Prop.search([('name', '=', field_name), ('company_id', '=', company.id), ('res_id', '=', False)], limit=1)
            if value:
                val = f"account.account,{value.id}"
                if prop:
                    prop.write({'value_reference': val})
                else:
                    field = self.env['ir.model.fields'].search([('model', '=', 'res.partner'), ('name', '=', field_name)], limit=1)
                    if field:
                        Prop.create({
                            'name': field_name,
                            'fields_id': field.id,
                            'value_reference': val,
                            'company_id': company.id,
                            'type': 'many2one',
                        })
            else:
                if prop:
                    prop.unlink()
