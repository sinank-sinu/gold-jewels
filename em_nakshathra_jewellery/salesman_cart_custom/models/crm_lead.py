from odoo import models, api, fields, _

class CrmLeadInherit(models.Model):
    _inherit = 'crm.lead'

    def action_sale_quotations_new(self):
        """Hijack the New Quotation button to launch the Salesman Tablet UI instead"""
        self.ensure_one()
        
        # 1. Look for an existing open draft tray for this salesperson
        active_cart = self.env['salesman.cart'].search([
            ('state', '=', 'draft'),
            ('salesman_id', '=', self.env.user.id)
        ], limit=1)

        # 2. If no open tray exists, initialize a brand new clean one
        if not active_cart:
            active_cart = self.env['salesman.cart'].create({
                'salesman_id': self.env.user.id,
                'partner_id': self.partner_id.id if self.partner_id else False,
                'opportunity_id': self.id,
            })
        else:
            # If an active tray was already open, ensure it assigns this CRM customer 
            vals = {}
            if self.partner_id and not active_cart.partner_id:
                vals['partner_id'] = self.partner_id.id
            if not active_cart.opportunity_id:
                vals['opportunity_id'] = self.id
            if vals:
                active_cart.write(vals)
                # active_cart.write({'partner_id': self.partner_id.id})

        # 3. Return a standard client action that forcefully switches the user's view
        # directly into your custom responsive showroom dashboard screen.
        return {
            'type': 'ir.actions.client',
            'tag': 'salesman_cart_dashboard_tags', # Triggers your custom OWL component registration tag
            'name': _('Salesman Tablet Cart'),
            'target': 'current',
        }