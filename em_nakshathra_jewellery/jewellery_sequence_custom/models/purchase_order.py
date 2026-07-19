from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Check if it's a new draft order getting a sequence
            if vals.get('name', _('New')) == _('New'):
                # Fetch branch based on vals or fallback to current user's branch
                branch_id = vals.get('branch_id')
                branch = self.env['res.branch'].browse(branch_id) if branch_id else self.env.user.branch_id
                
                if not branch or not branch.branch_code:
                    raise ValidationError("Branch code is missing for this Purchase Order!")
                
                # Fetch target company
                company_id = vals.get('company_id') or self.env.company.id
                company = self.env['res.company'].browse(company_id)
                
                # Search for a sequence specifically for this company
                sequence = self.env['ir.sequence'].search([
                    ('code', '=', 'purchase.order'),
                    ('company_id', '=', company.id)
                ], limit=1)
                
                # Fetch name of existing purchase orders for this company to calculate max sequence number used
                existing_orders = self.env['purchase.order'].search_read([
                    ('company_id', '=', company.id),
                    ('name', '!=', 'New'),
                    ('name', '!=', False)
                ], ['name'])
                
                next_number = 1
                for order in existing_orders:
                    name = order.get('name')
                    if name:
                        parts = name.split('/')
                        seq_part = parts[-1] if parts else ''
                        digits = ''.join(c for c in seq_part if c.isdigit())
                        if digits:
                            num = int(digits)
                            if num >= next_number:
                                next_number = num + 1
                
                if not sequence:
                    # If it doesn't exist for the company, we copy the global fallback one (company_id = False)
                    global_sequence = self.env['ir.sequence'].search([
                        ('code', '=', 'purchase.order'),
                        ('company_id', '=', False)
                    ], limit=1)
                    
                    if global_sequence:
                        sequence = global_sequence.copy({
                            'company_id': company.id,
                            'name': f"Purchase Order - {company.name}",
                            'number_next': next_number
                        })
                    else:
                        sequence = self.env['ir.sequence'].create({
                            'name': f"Purchase Order - {company.name}",
                            'code': 'purchase.order',
                            'company_id': company.id,
                            'prefix': 'P',
                            'padding': 5,
                            'number_next': next_number,
                            'number_increment': 1
                        })
                else:
                    if sequence.number_next < next_number:
                        sequence.write({'number_next': next_number})
                
                # Retrieve the next sequence from this company-specific record
                standard_sequence = sequence.next_by_id() or _('New')
                
                # Combine them to get 'KNR/P00123'
                vals['name'] = f"{branch.branch_code}/{standard_sequence}"
                
        return super(PurchaseOrder, self).create(vals_list)