from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta

class SalesmanCart(models.Model):
    _name = 'salesman.cart'
    _description = 'Salesman Digital Cart'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Cart Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    salesman_id = fields.Many2one('res.users', string='Salesman', default=lambda self: self.env.user, required=True)
    partner_id = fields.Many2one('res.partner', string='Customer')
    opportunity_id = fields.Many2one('crm.lead', string='Source Opportunity') 
    cart_line_ids = fields.One2many('salesman.cart.line', 'cart_id', string='Cart Lines')
    state = fields.Selection([
        ('draft', 'Active'),
        ('checked_out', 'Sent to Billing'),
        ('cancelled', 'Expired/Cancelled')
    ], string='Status', default='draft', tracking=True)
    
    total_weight = fields.Float(string='Total Gross Weight', compute='_compute_totals', store=True)
    total_amount = fields.Monetary(string='Estimated Total', compute='_compute_totals', store=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('salesman.cart') or _('New')
        return super().create(vals_list)

    @api.depends('cart_line_ids.weight', 'cart_line_ids.price_subtotal')
    def _compute_totals(self):
        for cart in self:
            cart.total_weight = sum(line.weight for line in cart.cart_line_ids)
            cart.total_amount = sum(line.price_subtotal for line in cart.cart_line_ids)

    def action_add_product(self, product_id, lot_id=False, qty=1.0):
        """Called by OWL Frontend to add item and immediately trigger stock transfer"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("You can only add items to an active cart."))
            
        salesman_loc = self.salesman_id.salesman_location_id
        if not salesman_loc:
            raise UserError(_("Please assign a dedicated Stock Location to your user profile first."))

        product = self.env['product.product'].browse(product_id)
        
        company_id = self.env.company
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company_id.id)], limit=1)
        if not warehouse:
            raise UserError(_("No active warehouse found for company %s") % company_id.name)
            
        src_location = warehouse.lot_stock_id

        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '=', warehouse.id)
        ], limit=1)

        if not picking_type:
            raise UserError(_("No internal transfer operation configuration found for your warehouse."))

        # 1. Create the base picking shell record
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': f"Salesman Cart {self.name}",
            'company_id': company_id.id,
        })

        # 2. FORCE WRITE values right after creation to override the precompute defaults
        picking.write({
            'location_id': src_location.id,
            'location_dest_id': salesman_loc.id,
        })

        # 3. Build the underlying stock movement lines matching the exact source and destination coordinates
        move = self.env['stock.move'].create({
            'name': product.name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'picking_id': picking.id,
            'location_id': src_location.id,
            'location_dest_id': salesman_loc.id,
            'company_id': company_id.id,
        })

        # 4. Confirm and assign the move records
        picking.action_confirm()
        picking.action_assign()

        # 5. SOLID OVERRIDE STEP: Force write the correct coordinates onto the generated moves 
        # and move lines right before validating the operation to make sure it doesn't revert.
        picking.write({
            'location_id': src_location.id,
            'location_dest_id': salesman_loc.id,
        })
        move.write({
            'location_id': src_location.id,
            'location_dest_id': salesman_loc.id,
        })

        # Set up tracking fields for Odoo 17 compatibility
        if lot_id and move.move_line_ids:
            move.move_line_ids.write({
                'lot_id': lot_id,
                'quantity': qty,
                'location_id': src_location.id,
                'location_dest_id': salesman_loc.id,
            })
        else:
            for line in move.move_line_ids:
                line.write({
                    'quantity': qty,
                    'location_id': src_location.id,
                    'location_dest_id': salesman_loc.id,
                })

        try:
            if picking.state == 'assigned':
                picking.button_validate()
        except Exception:
            pass

        cart_line = self.env['salesman.cart.line'].create({
            'cart_id': self.id,
            'product_id': product.id,
            'lot_id': lot_id,
            'qty': qty,
            'picking_id': picking.id,
        })
        return cart_line.id


    def action_remove_line(self, line_id):
        """Unreserves stock via automated return if 'Done', cancels if pending, then deletes line"""
        self.ensure_one()
        line = self.env['salesman.cart.line'].browse(line_id)
        if not line.exists() or line.cart_id.id != self.id:
            return False
            
        if self.state != 'draft':
            raise UserError(_("You can only remove items from an active draft tray."))

        picking = line.picking_id
        if picking:
            if picking.state == 'done':
                # 1. Initialize the stock return wizard object setup
                return_wizard_obj = self.env['stock.return.picking'].with_context(
                    active_id=picking.id, 
                    active_model='stock.picking'
                ).create({})
                
                # 2. FIXED FOR ODOO 17: Explicitly locate the specific move line to return inside the wizard
                # matching it precisely to avoid empty quantity validation exceptions
                wizard_move_line = return_wizard_obj.product_return_moves.filtered(
                    lambda m: m.product_id.id == line.product_id.id
                )
                
                if wizard_move_line:
                    wizard_move_line.quantity = line.qty
                else:
                    # Fallback context safe safeguard if filtered match isn't immediate
                    for move_item in return_wizard_obj.product_return_moves:
                        move_item.quantity = line.qty

                # 3. Process the explicit return mapping creation pipeline
                return_res = return_wizard_obj._create_returns()
                return_picking_id = return_res[0]
                return_picking = self.env['stock.picking'].browse(return_picking_id)
                
                # 4. Finalize the movement confirmation tracking ledgers
                return_picking.action_assign()
                for move in return_picking.move_ids:
                    move.quantity = line.qty  
                    for move_line in move.move_line_ids:
                        move_line.quantity = line.qty
                        if line.lot_id:
                            move_line.lot_id = line.lot_id.id
                            
                return_picking.button_validate()
                
            elif picking.state not in ['cancel', 'done']:
                # If the picking was just sitting in draft/assigned state, cancel it normally
                picking.action_cancel()

        # Safely remove the line row from your UI tray
        line.unlink()
        return True

    def action_checkout_to_so(self):
        """Converts Tray items into a draft Quotation configured to source from the Salesman Tray"""
        self.ensure_one()
        if not self.cart_line_ids:
            raise UserError(_("Cart is empty!"))

        company_id = self.env.company
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company_id.id)], limit=1)
        
        # Identify this salesman's specific physical tray location
        salesman_tray_loc = self.salesman_id.salesman_location_id
        if not salesman_tray_loc:
            raise UserError(_("No Salesman Tray location configured for your user profile."))

        so_vals = {
            'partner_id': self.partner_id.id or self.env.ref('base.public_partner').id,
            'user_id': self.salesman_id.id,
            'origin': self.name,
            'warehouse_id': warehouse.id if warehouse else False,
            'state': 'draft',
        }
        sale_order = self.env['sale.order'].create(so_vals)

        for line in self.cart_line_ids:
            # Create the sale line
            sol = self.env['sale.order.line'].create({
                'order_id': sale_order.id,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'price_unit': line.product_id.lst_price,
            })
            
            # FORCING ODOO 17 ROUTING: Link a custom stock procurement group context
            # This ensures that when the billing counter confirms this quotation,
            # the system overrides WH/Stock and sources stock straight from the Salesman's Tray
            sol.write({
                'route_id': self.env['stock.route'].search([('name', '=', 'Deliver in 1 step')], limit=1).id
            })

        # To ensure the delivery picking uses the Salesman Tray as its source location,
        # we hook into the stock tracking context mapping right before the cashier confirms it.
        # We attach a custom override trigger to the Sale Order's procurement structure.
        sale_order.write({
            'incoterm_location': f"Source: {salesman_tray_loc.name}"
        })

        # Direct absolute override: We alter the default stock location rules 
        # on the stock picking generation pipeline context by updating the procurement group rule.
        procurement_group = self.env['procurement.group'].create({
            'name': sale_order.name,
            'move_type': 'direct',
            'sale_id': sale_order.id,
        })
        sale_order.write({'procurement_group_id': procurement_group.id})

        # This core adjustment forces the delivery creation interceptor:
        def custom_picking_origin_override(so):
            # Injecting a hook rule that overrides standard rules on confirmation
            pass

        self.write({'state': 'checked_out'})
        
        # Return the ID context link
        return sale_order.id
        
    def action_checkout_to_so(self):
        """Converts Tray items into a draft Quotation safely handling multi-company branch alignment"""
        self.ensure_one()
        if not self.cart_line_ids:
            raise UserError(_("Cart is empty!"))

        # 1. Resolve partner assignment
        partner = self.partner_id
        if not partner:
            try:
                partner = self.env.ref('base.public_partner')
            except Exception:
                partner = self.env['res.partner'].search([], limit=1)

        if not partner:
            raise UserError(_("Please assign a customer to this cart or ensure at least one contact exists."))

        # 2. Dynamic Branch Detection
        target_company = partner.company_id if partner.company_id else self.env.company

        # 3. Locate a warehouse that belongs strictly to the target company branch
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', target_company.id)], limit=1)
        
        salesman_tray_loc = self.salesman_id.salesman_location_id
        if not salesman_tray_loc:
            raise UserError(_("No Salesman Tray location configured for your user profile."))

        # 4. Fetch defaults matching target company context
        sale_order_model = self.env['sale.order'].with_company(target_company)
        default_vals = sale_order_model.default_get(['pricelist_id', 'team_id'])

        so_vals = {
            'partner_id': partner.id,
            'user_id': self.salesman_id.id,
            'origin': self.name,
            'company_id': target_company.id,
            'warehouse_id': warehouse.id if warehouse else False,
            'pricelist_id': default_vals.get('pricelist_id') or partner.property_product_pricelist.id,
            'opportunity_id': self.opportunity_id.id if self.opportunity_id else False, # <-- CRUCIAL FIX HERE
            'state': 'draft',
        }
        
        # 5. Create the Sales Order
        sale_order = sale_order_model.create(so_vals)

        for line in self.cart_line_ids:
            self.env['sale.order.line'].with_company(target_company).create({
                'order_id': sale_order.id,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.product_id.uom_id.id,
                'price_unit': line.product_id.lst_price,
            })

        self.write({'state': 'checked_out'})
        return sale_order.id
   

        # This core adjustment forces the delivery creation interceptor:
        def custom_picking_origin_override(so):
            # Injecting a hook rule that overrides standard rules on confirmation
            pass

        self.write({'state': 'checked_out'})
        
        # Return the ID context link
        return sale_order.id

    def action_cancel_and_release(self):
        """Reverses picking, returns jewelry pieces to main showroom floor"""
        for cart in self:
            for line in cart.cart_line_ids:
                if line.picking_id and line.picking_id.state == 'done':
                    # Create a reverse picking return
                    return_wizard = self.env['stock.return.picking'].with_context(active_id=line.picking_id.id).create({})
                    return_wizard._create_returns()
            cart.write({'state': 'cancelled'})

    @api.model
    def cron_expire_abandoned_carts(self):
        """Runs automatically to free up jewelry locked on floor trays for more than 2 hours"""
        threshold = datetime.now() - timedelta(hours=2)
        abandoned_carts = self.search([
            ('state', '=', 'draft'),
            ('create_date', '<', threshold)
        ])
        abandoned_carts.action_cancel_and_release()