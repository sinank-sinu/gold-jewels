from odoo import models, fields,api,_
from odoo.exceptions import ValidationError, UserError


class OldGoldPurchase(models.Model):
    _name = 'old.gold.purchase'


    partner_id = fields.Many2one('res.partner', required=True)
    name = fields.Char("name")
    date = fields.Date("date")
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    old_gold_line_ids = fields.One2many('sale.old.gold.line', 'old_gold_purchase_id')
    state = fields.Selection([
    ('draft','Draft'),('ho_transfer','HO Transfer'),('done','Verified'),('batched','Batched')
    ], default='draft')
    branch_location_id = fields.Many2one('stock.location')
    ho_location_id = fields.Many2one('stock.location')
    sale_id = fields.Many2one('sale.order', ondelete='cascade')
    branch_id = fields.Many2one("res.branch", string='Branch',
                                default=lambda self: self.env.user.branch_id.id)
    is_smith_transfer = fields.Boolean(string="Smith Transfer Required")
    smith_transferred = fields.Boolean(string="Smith Transferred", default=False)

    total_gross_weight = fields.Float(string="Total Gross Weight", compute="_compute_totals", store=True)
    total_net_weight = fields.Float(string="Total Weight Verified", compute="_compute_totals", store=True)
    total_verified_net_weight = fields.Float(string="Total Weight", compute="_compute_totals", store=True)
    add_less = fields.Float(string="Add / Less", compute="_compute_add_less", store=True)
    add_less_location_id = fields.Many2one('stock.location',"Add/Less Location")
    add_less_transferred = fields.Boolean(
        string="Add/Less Transferred",
        default=False,
        help="Indicates if the Add/Less transfer has already been done"
    )
    total_amount = fields.Float(string="Total Amount", compute="_compute_totals", store=True)
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Source Purchase Order',

    )
    purchase_per_rate = fields.Float(string="Purchase/gram", compute="_compute_per_gram", store=True)

    total_transferred_weight = fields.Float(string="Total Transferred to Smith", compute="_compute_smith_totals", store=True, digits=(16, 3))

    @api.depends('old_gold_line_ids.transferred_weight', 'total_verified_net_weight')
    def _compute_smith_totals(self):
        for record in self:
            record.total_transferred_weight = sum(record.old_gold_line_ids.mapped('transferred_weight'))

    @api.depends('old_gold_line_ids.verified_net_weight', 'old_gold_line_ids.net_weight',
                 'old_gold_line_ids.gross_weight', 'old_gold_line_ids.verified_gross_weight',
                 'old_gold_line_ids.amount')
    def _compute_totals(self):
        for record in self:
            record.total_gross_weight = sum(record.old_gold_line_ids.mapped('gross_weight'))
            record.total_net_weight = sum(record.old_gold_line_ids.mapped('net_weight'))
            record.total_verified_net_weight = sum(record.old_gold_line_ids.mapped('verified_net_weight'))
            record.total_amount = sum(record.old_gold_line_ids.mapped('amount'))

    @api.depends('total_net_weight', 'total_verified_net_weight')
    def _compute_add_less(self):
        for record in self:
            record.add_less = record.total_verified_net_weight - record.total_net_weight

    @api.depends('total_amount', 'total_verified_net_weight')
    def _compute_per_gram(self):
        for record in self:
            record.purchase_per_rate = (
                record.total_amount / record.total_verified_net_weight
                if record.total_verified_net_weight
                else 0.0
            )
    def action_confirm(self):
        for rec in self:
            rec.state = 'done'

    def _get_old_gold_product(self, is_diamond_og=False):
        self.ensure_one()
        company_id = self.company_id.id or self.branch_id.company_id.id or self.env.company.id
        Product = self.env['product.product'].sudo()

        if is_diamond_og:
            product = Product.search([
                ('is_diamond_og', '=', True),
                ('company_id', '=', company_id)
            ], limit=1) or Product.search([
                ('name', 'ilike', 'Diamond OG'),
                ('company_id', '=', company_id)
            ], limit=1) or Product.search([
                ('is_diamond_og', '=', True),
                ('company_id', 'in', [company_id, False])
            ], limit=1)
            if product:
                return product

        product = Product.search([
            ('is_old_gold', '=', True),
            ('company_id', '=', company_id)
        ], limit=1) or Product.search([
            ('name', '=ilike', 'Old Gold'),
            ('company_id', '=', company_id)
        ], limit=1) or Product.search([
            ('is_old_gold', '=', True),
            ('name', 'not ilike', 'Scrap'),
            ('company_id', 'in', [company_id, False])
        ], limit=1) or self.env.ref('em_jewellery_management.product_old_gold', raise_if_not_found=False)

        return product

    def action_transfer_to_ho(self,source_id=False,destination_id=False):
        if not source_id and not destination_id:
            source_id = self.branch_location_id
            destination_id = self.ho_location_id

        for rec in self:
            rec.branch_location_id = source_id.id
            rec.ho_location_id = destination_id.id
            company_id = rec.company_id.id or source_id.company_id.id or self.env.company.id
            picking_type = self.env['stock.picking.type'].sudo().search([
                ('code', '=', 'internal'),
                ('company_id', '=', company_id)
            ], limit=1)
            if not picking_type:
                picking_type = self.env.ref('stock.picking_type_internal').sudo()

            picking = self.env['stock.picking'].sudo().create({
                'picking_type_id': picking_type.id,
                'location_id': source_id.id,
                'location_dest_id': destination_id.id,
                'origin': rec.name,
                'sale_old_id': rec.sale_id.id,
                'is_old_gold': True,
                'company_id': company_id,
            })

            default_product = rec._get_old_gold_product()
            default_uom = default_product.uom_id if default_product else False

            for line in rec.old_gold_line_ids:
                line_product = rec._get_old_gold_product(is_diamond_og=line.is_diamond_og) or default_product
                uom = line_product.uom_id or default_uom
                self.env['stock.move'].sudo().create({
                    'product_id': line_product.id,
                    'name': f'Old Gold ({line.purity_id.name})',
                    'purity_id': line.purity_id.id,
                    'product_uom_qty': line.net_weight,
                    'product_uom': uom.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'picking_id': picking.id,
                    'company_id': company_id,
                })

            picking.sudo().action_confirm()
            # picking.button_validate()
            rec.state = 'ho_transfer'


    def action_view_old_gold_transfers(self):
        self.ensure_one()

        domain = [('is_old_gold', '=', True)]
        if self.name and self.sale_id:
            domain += ['|', ('origin', '=', self.name), ('sale_old_id', '=', self.sale_id.id)]
        elif self.name:
            domain += [('origin', '=', self.name)]
        elif self.sale_id:
            domain += [('sale_old_id', '=', self.sale_id.id)]
        else:
            domain += [('id', '=', False)]

        pickings = self.env['stock.picking'].search(domain)
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Old Gold Transfers'),
            'res_model': 'stock.picking',
            'domain': domain,
            'context': {
                'default_origin': self.name,
                'default_sale_old_id': self.sale_id.id if self.sale_id else False,
                'default_is_old_gold': True,
            },
        }

        if len(pickings) == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = pickings.id
        else:
            action['views'] = [(False, 'tree'), (False, 'form')]

        return action

    def action_view_ho_verified(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('HO Verified'),
            'res_model': 'old.gold.ho.verification',
            'view_mode': 'tree,form',
            'domain': [
                ('purchase_id', '=', self.id),
            ],
        }

    def action_create_ho_verification(self):
        Verification = self.env['old.gold.ho.verification']

        for rec in self:
            if rec.state != 'ho_transfer':
                raise ValidationError("Gold must be transferred to HO first.")

            # Group by purity
            purity_map = {}
            for line in rec.old_gold_line_ids:
                purity_map.setdefault(line.purity_id, 0.0)
                purity_map[line.purity_id] += line.net_weight

            verification = Verification.create({
                'purchase_id': rec.id,
                'ho_location_id':rec.ho_location_id.id,
            })

            for purity, weight in purity_map.items():
                self.env['old.gold.ho.verification.line'].create({
                    'verification_id': verification.id,
                    'purity_id': purity.id,
                    'branch_net_weight': weight,
                    'ho_received_weight': weight,  # default same, editable
                })

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'old.gold.ho.verification',
                'res_id': verification.id,
                'view_mode': 'form',
            }

    def action_open_smith_transfer_wizard(self):
        self.ensure_one()
        return {
            'name': _('Transfer to Smith'),
            'type': 'ir.actions.act_window',
            'res_model': 'old.gold.smith.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'active_model': 'old.gold.purchase',
            }
        }

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            company_id = vals.get('company_id') or self.env.company.id
            vals['name'] = self.env['ir.sequence'].with_company(company_id).next_by_code(
                'old.gold.purchase'
            ) or _('New')
        return super().create(vals)

    def action_transfer_add_less(self):
        for record in self:
            if not record.add_less or record.add_less == 0:
                raise UserError("No Add/Less difference to transfer.")

            qty = abs(record.add_less)

            # # Determine source and destination
            source_location = record.ho_location_id.id
            dest_location = record.add_less_location_id.id
            #
            # # Reverse transfer if less gold
            if record.add_less < 0:
                source_location, dest_location = dest_location, source_location

            # Determine source and destination location objects to get company
            src_loc_obj = self.env['stock.location'].browse(source_location)
            company_id = record.company_id.id or src_loc_obj.company_id.id or self.env.company.id

            product = record._get_old_gold_product()
            if not product:
                raise ValidationError(_("Old Gold product not configured for company %s.") % (record.company_id.name or ''))
            uom = product.uom_id
            
            picking_type = self.env['stock.picking.type'].sudo().search([
                ('code', '=', 'internal'),
                ('company_id', '=', company_id)
            ], limit=1)
            if not picking_type:
                picking_type = self.env.ref('stock.picking_type_internal').sudo()

            # Create stock move using the fixed Add/Less product
            picking = self.env['stock.picking'].sudo().create({
                'picking_type_id': picking_type.id,
                'location_id': source_location,
                'location_dest_id': dest_location,
                'origin':self.name,
                'sale_old_id': self.sale_id.id,
                'is_old_gold': True,
                'company_id': company_id,
            })

            self.env['stock.move'].sudo().create({
                'description_picking': f"Add/Less Transfer for {record.name}",
                'name': f"Add/Less Transfer for {record.name}",
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'location_id': source_location,
                'location_dest_id': dest_location,
                'picking_id': picking.id,
            })
            self.add_less_transferred = True


class SaleOldGoldLine(models.Model):
    _name = 'sale.old.gold.line'
    _description = 'Old Gold Purchase Line'
    _order = 'date desc, id desc'

    sale_id = fields.Many2one('sale.order')
    old_gold_purchase_id = fields.Many2one('old.gold.purchase', string="Old Gold Purchase", ondelete='cascade')
    is_smith_transfer = fields.Boolean(related='old_gold_purchase_id.is_smith_transfer', string="Smith Transfer Required")
    batch_id = fields.Many2one('old.gold.batch', string="Batch")

    partner_id = fields.Many2one(
        related='old_gold_purchase_id.partner_id',
        string='Partner',
        store=True,
    )
    date = fields.Date(
        related='old_gold_purchase_id.date',
        string='Date',
        store=True,
    )
    company_id = fields.Many2one(
        related='old_gold_purchase_id.company_id',
        string='Company',
        store=True,
    )
    state = fields.Selection(
        related='old_gold_purchase_id.state',
        string='Status',
        store=True,
    )

    purity_id = fields.Many2one('gold.purity', required=True)
    is_diamond_og = fields.Boolean(
        string="Is Diamond OG",
        compute='_compute_is_diamond_og',
        store=True,
        readonly=False,
    )
    location_id = fields.Many2one(
        'stock.location',
        string="Destination Location",
        compute='_compute_location_id',
        store=True,
    )

    def action_view_old_gold_purchase(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Old Gold Purchase'),
            'res_model': 'old.gold.purchase',
            'view_mode': 'form',
            'res_id': self.old_gold_purchase_id.id,
            'target': 'current',
        }

    @api.depends('purity_id', 'purity_id.is_diamond_og', 'diamond_amount')
    def _compute_is_diamond_og(self):
        for line in self:
            if line.purity_id and line.purity_id.is_diamond_og:
                line.is_diamond_og = True
            elif line.diamond_amount and line.diamond_amount > 0:
                line.is_diamond_og = True
            elif not line.is_diamond_og:
                line.is_diamond_og = False

    def _resolve_dest_location(self, is_dmd, branch):
        if is_dmd:
            if self.sale_id and hasattr(self.sale_id, '_get_diamond_og_location'):
                return self.sale_id._get_diamond_og_location(branch)
            if branch and branch.diamond_og_location_id:
                return branch.diamond_og_location_id
            return (branch and branch.old_gold_location_id) or False
        else:
            if self.sale_id and hasattr(self.sale_id, '_get_regular_og_location'):
                return self.sale_id._get_regular_og_location(branch) or self.sale_id.branch_location_id
            if branch and branch.old_gold_location_id:
                return branch.old_gold_location_id
            return False

    @api.depends('is_diamond_og', 'sale_id.branch_id', 'branch_id', 'old_gold_purchase_id.branch_id', 'diamond_amount', 'purity_id')
    def _compute_location_id(self):
        for line in self:
            branch = line.sale_id.branch_id or line.branch_id or (line.old_gold_purchase_id and line.old_gold_purchase_id.branch_id) or self.env.user.branch_id
            is_dmd = line.is_diamond_og or (line.diamond_amount and line.diamond_amount > 0) or (line.purity_id and line.purity_id.is_diamond_og)
            loc = line._resolve_dest_location(is_dmd, branch)
            line.location_id = loc.id if loc else False

    @api.onchange('purity_id', 'diamond_amount', 'is_diamond_og')
    def _onchange_purity_id_set_location(self):
        for line in self:
            branch = line.sale_id.branch_id or line.branch_id or self.env.user.branch_id
            is_dmd = line.is_diamond_og or (line.diamond_amount and line.diamond_amount > 0) or (line.purity_id and line.purity_id.is_diamond_og)
            if is_dmd:
                line.is_diamond_og = True
            loc = line._resolve_dest_location(is_dmd, branch)
            line.location_id = loc.id if loc else False

    gross_weight = fields.Float(required=True,digits=(16, 3))
    stone_weight = fields.Float(digits=(16, 3))
    net_weight = fields.Float(compute='_compute_net', store=True,digits=(16, 3))


    rate = fields.Float()
    diamond_amount = fields.Float(string="Diamond Amount")

    amount = fields.Float(string="Amount", compute='_compute_amount', store=True, readonly=False)


    stock_move_id = fields.Many2one('stock.move', readonly=True)
    ho_transfer_id = fields.Many2one('stock.picking', readonly=True)
    branch_id = fields.Many2one(related='old_gold_purchase_id.branch_id', string='Branch',
                                store=True)

    verified_purity_id = fields.Many2one('gold.purity', string="Verified Purity")
    verified_gross_weight = fields.Float(string="Verified Gross Weight", digits=(16, 3))
    verified_stone_weight = fields.Float(string="Verified Stone Weight", digits=(16, 3))
    verified_net_weight = fields.Float(compute='_compute_verified_net', store=True, digits=(16, 3))
    fine = fields.Float(string="Fine", compute="_compute_fine_total", store=True)
    fine_verified = fields.Float(string="Fine verified", compute="_compute_fine_total_verified", store=True)

    transferred_weight = fields.Float(string="Transferred Weight", digits=(16, 3))
    remaining_weight = fields.Float(string="Remaining Weight", compute="_compute_remaining_weight", store=True, digits=(16, 3))

    @api.depends('verified_net_weight', 'transferred_weight')
    def _compute_remaining_weight(self):
        for line in self:
            line.remaining_weight = line.verified_net_weight - line.transferred_weight

    @api.depends('net_weight','purity_id')
    def _compute_fine_total(self):
        for line in self:
            if line.purity_id and line.purity_id.percentage:
                line.fine = line.net_weight * (line.purity_id.percentage /100)

    @api.depends('verified_net_weight', 'verified_purity_id')
    def _compute_fine_total_verified(self):
        for line in self:
            if line.verified_purity_id and line.verified_purity_id.percentage:
                line.fine_verified = line.verified_net_weight * (line.verified_purity_id.percentage / 100)

    @api.depends('verified_gross_weight', 'verified_stone_weight')
    def _compute_verified_net(self):
        for r in self:
            r.verified_net_weight = r.verified_gross_weight - r.verified_stone_weight


    @api.depends('gross_weight', 'stone_weight')
    def _compute_net(self):
        for r in self:
            r.net_weight = r.gross_weight - r.stone_weight


    @api.depends('net_weight', 'rate', 'diamond_amount')
    def _compute_amount(self):
        for rec in self:
            if not self.env.context.get('skip_old_gold_amount_compute'):
                rec.amount = (rec.net_weight * rec.rate) + rec.diamond_amount
            elif not rec.amount:
                rec.amount = (rec.net_weight * rec.rate) + rec.diamond_amount

    @api.onchange('purity_id')
    def _onchange_purity(self):
        for r in self:
            today = fields.Date.today()
            gold_rate_rec = self.env['gold.rate.master'].search([
                ('purity_id', '=', r.purity_id.id),
                ('date', '<=', today),
                ('active', '=', True),
                ('rate_type', '=', 'old_gold')
            ], order='date desc', limit=1)
            gold_rate = gold_rate_rec.board_rate
            self.rate = gold_rate



