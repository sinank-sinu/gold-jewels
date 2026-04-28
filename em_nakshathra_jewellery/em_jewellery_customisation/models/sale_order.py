from collections import defaultdict

from odoo import models, fields,api,_
from odoo.exceptions import UserError, ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'


    def _get_customer_scheme_records(self):
        self.ensure_one()
        return self.env['jewellery.scheme.enrollment'].search([
                ('partner_id', '=', self.partner_id.id),
                ('active', '=', True),
                # ('state', '=', 'running'),
                ('balance_amount', '=', 0)
            ])

    def action_apply_scheme(self):
        for order in self:
            if not order.partner_id:
                raise UserError(_("Select customer first."))

            # Prevent duplicate apply
            if order.scheme_line_id:
                raise UserError(_("Scheme already applied."))

            completed_schemes = order._get_customer_scheme_records().filtered(
                lambda s: s.state == 'completed'
            )

            if order.apply_scheme and completed_schemes:

                # pick lowest priority
                completed_schemes = order._get_customer_scheme_records().filtered(
                    lambda s: s.state == 'completed'
                ).sorted(key=lambda s: (s.priority, s.create_date))
            
                if not completed_schemes:
                    raise UserError(_("No completed scheme available for this customer."))
                
                # Take latest / first scheme
                scheme = completed_schemes[0]
               
                scheme_amount = scheme.total_paid

                if scheme_amount <= 0:
                    raise UserError(_("Invalid scheme amount."))

                quotation_total = order.amount_total

                if quotation_total <= 0:
                    raise UserError(_("Quotation total is zero."))

                redeem_amount = min(quotation_total, scheme_amount)

                # scheme_product = order._get_scheme_product()
                product_code = f"SCHEME-{scheme.id}"

                product = self.env['product.product'].search([
                    ('default_code', '=', product_code)
                ], limit=1)

                if not product:
                    product = self.env['product.product'].create({
                        'name': f"{scheme.name} - {order.partner_id.name}",
                        'type': 'service',
                        'list_price': 0.0,
                    })


                line = self.env['sale.order.line'].create({
                    'order_id': order.id,
                    'product_id': product.id,
                    'product_uom_qty': 1,
                    'product_uom': product.uom_id.id,
                    'name': f"{product.name} (Scheme Redemption)",
                    'is_scheme_line': True,
                    'price_unit': -redeem_amount,
                    'price_subtotal': -redeem_amount,
                })
                order.scheme_line_id = line
                scheme.write({
                    'state': 'redeemed'   
                })
                self.env['scheme.redemption'].create({
                    'scheme_id': scheme.id,
                    'sale_order_id': order.id,
                    'amount': redeem_amount,
                })

            else:
                schemes = order._get_customer_scheme_records()

                if not schemes:
                    raise UserError(_("No active scheme available for this customer."))

                total_mc = sum(order.order_line.mapped('mc_amount'))

                if total_mc <= 0:
                    raise UserError(_("No Making Charge found to apply scheme."))

                scheme_product = order._get_scheme_product()
               
                line = self.env['sale.order.line'].create({
                    'order_id': order.id,
                    'product_id': scheme_product.id,
                    'product_uom_qty': 1,
                    'product_uom': scheme_product.uom_id.id,
                    'name': f"{scheme_product.name} (MC Discount)",
                    'is_scheme_line': True,
                    'price_unit': -total_mc,
                    'price_subtotal': -total_mc,
                })

                order.scheme_line_id = line

                # deactivate schemes
                schemes.write({'active': False})

                # zero out MC
                for ol in order.order_line:
                    if hasattr(ol, 'mc_amount') and ol.mc_amount > 0:
                        ol.mc_amount = 0

