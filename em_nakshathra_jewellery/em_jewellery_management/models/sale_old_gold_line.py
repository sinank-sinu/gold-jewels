from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.osv import expression


class OldGoldPurchase(models.Model):
    _name = 'old.gold.purchase'


    partner_id = fields.Many2one('res.partner', required=True)
    name = fields.Char("name")
    date = fields.Datetime("Date", default=fields.Datetime.now)
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

    def action_transfer_to_ho(self, source_id=False, destination_id=False):
        for rec in self:
            src_loc = source_id or rec.branch_location_id
            dest_loc = destination_id or rec.ho_location_id
            if not src_loc or not dest_loc:
                raise ValidationError(_("Please configure both Source Location and HO Location before transferring."))

            rec.branch_location_id = src_loc.id
            rec.ho_location_id = dest_loc.id
            company_id = rec.company_id.id or src_loc.company_id.id or self.env.company.id
            picking_type = self.env['stock.picking.type'].sudo().search([
                ('code', '=', 'internal'),
                ('company_id', '=', company_id)
            ], limit=1)
            if not picking_type:
                picking_type = self.env.ref('stock.picking_type_internal').sudo()

            picking = self.env['stock.picking'].sudo().create({
                'picking_type_id': picking_type.id,
                'location_id': src_loc.id,
                'location_dest_id': dest_loc.id,
                'origin': rec.name,
                'branch_id': rec.branch_id.id if rec.branch_id else False,
                'sale_old_id': rec.sale_id.id,
                'is_old_gold': True,
                'company_id': company_id,
            })

            default_product = rec._get_old_gold_product()
            for line in rec.old_gold_line_ids:
                line_product = rec._get_old_gold_product(is_diamond_og=line.is_diamond_og) or default_product
                if not line_product:
                    raise ValidationError(_("Old Gold product not configured for company %s.") % (rec.company_id.name or ''))
                self.env['stock.move'].sudo().create({
                    'product_id': line_product.id,
                    'name': f'Old Gold ({line.purity_id.name})',
                    'purity_id': line.purity_id.id,
                    'old_gold_line_id': line.id,
                    'product_uom_qty': line.net_weight,
                    'product_uom': line_product.uom_id.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'picking_id': picking.id,
                    'company_id': company_id,
                })
                line.ho_transfer_id = picking.id

            picking.sudo().action_confirm()
            # picking.button_validate()
            rec.state = 'ho_transfer'


    def action_view_old_gold_transfers(self):
        self.ensure_one()

        picking_ids = self.old_gold_line_ids.mapped('ho_transfer_id').ids
        conditions = []
        if picking_ids:
            conditions.append([('id', 'in', picking_ids)])
        if self.name:
            conditions.append([('origin', '=', self.name)])
        if self.sale_id:
            conditions.append([('sale_old_id', '=', self.sale_id.id)])

        if conditions:
            domain = expression.AND([[('is_old_gold', '=', True)], expression.OR(conditions)])
        else:
            domain = [('id', '=', False)]

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


    sale_id = fields.Many2one('sale.order')
    old_gold_purchase_id = fields.Many2one('old.gold.purchase')
    is_smith_transfer = fields.Boolean(
        string="Smith Transfer Required",
        compute='_compute_is_smith_transfer',
        store=True,
    )


    batch_id = fields.Many2one('old.gold.batch', string="Batch")


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

    @api.depends('batch_id.is_smith_transfer', 'old_gold_purchase_id.is_smith_transfer')
    def _compute_is_smith_transfer(self):
        for line in self:
            line.is_smith_transfer = (
                line.batch_id.is_smith_transfer if line.batch_id
                else (line.old_gold_purchase_id.is_smith_transfer if line.old_gold_purchase_id else False)
            )

    def _get_effective_source_location(self):
        self.ensure_one()
        if self.location_id:
            return self.location_id
        branch = self.branch_id or (self.old_gold_purchase_id and self.old_gold_purchase_id.branch_id)
        if self.is_diamond_og and branch and branch.diamond_og_location_id:
            return branch.diamond_og_location_id
        if self.old_gold_purchase_id and self.old_gold_purchase_id.branch_location_id:
            return self.old_gold_purchase_id.branch_location_id
        return branch.old_gold_location_id if branch else False

    def _validate_ho_transfer_lines(self):
        """Validate that selected pieces can be transferred together to HO."""
        if not self:
            raise ValidationError(_("Please select at least one Old Gold piece to transfer."))

        missing_purchase = self.filtered(lambda l: not l.old_gold_purchase_id)
        if missing_purchase:
            raise ValidationError(_("Only Old Gold Purchase pieces can be transferred to HO."))

        invalid_state = self.filtered(lambda l: l.state != 'draft' or l.ho_transfer_id)
        if invalid_state:
            names = ", ".join(dict.fromkeys(
                l.old_gold_purchase_id.name or str(l.id) for l in invalid_state
            ))
            raise ValidationError(_(
                "HO transfer is allowed only for Draft pieces without an existing HO transfer.\n"
                "Invalid piece(s) from: %s"
            ) % names)

        zero_weight = self.filtered(lambda l: (l.net_weight or 0.0) <= 0.0)
        if zero_weight:
            names = ", ".join(dict.fromkeys(
                l.old_gold_purchase_id.name or str(l.id) for l in zero_weight
            ))
            raise ValidationError(_(
                "Net weight must be greater than zero for HO transfer.\n"
                "Invalid piece(s) from: %s"
            ) % names)

        branches = self.mapped('branch_id')
        if not branches or len(branches) > 1 or any(not l.branch_id for l in self):
            branch_names = ", ".join(branches.mapped('name')) or _("Unknown")
            raise ValidationError(_(
                "All selected pieces must belong to the same branch.\n"
                "Selected branches: %s"
            ) % branch_names)

        companies = self.mapped('company_id')
        if len(companies) > 1:
            raise ValidationError(_(
                "All selected pieces must belong to the same company.\n"
                "Selected companies: %s"
            ) % ", ".join(companies.mapped('name')))

        source_locations = self.env['stock.location']
        missing_loc = False
        for line in self:
            loc = line._get_effective_source_location()
            if loc:
                source_locations |= loc
            else:
                missing_loc = True
        if not source_locations or len(source_locations) > 1 or missing_loc:
            loc_names = ", ".join(source_locations.mapped('display_name')) or _("Unknown")
            raise ValidationError(_(
                "All selected pieces must belong to the same location.\n"
                "Selected locations: %s"
            ) % loc_names)

        target_location = source_locations[0]
        purchases = self.mapped('old_gold_purchase_id')
        selected_ids = set(self.ids)
        incomplete_purchases = purchases.filtered(
            lambda p: not set(
                p.old_gold_line_ids.filtered(
                    lambda l: l._get_effective_source_location() == target_location
                ).ids
            ).issubset(selected_ids)
        )
        if incomplete_purchases:
            details = []
            for purchase in incomplete_purchases:
                missing_lines = purchase.old_gold_line_ids.filtered(
                    lambda l: l._get_effective_source_location() == target_location and l.id not in selected_ids
                )
                missing_purities = ", ".join(dict.fromkeys(
                    l.purity_id.name for l in missing_lines if l.purity_id
                ))
                purity_info = f" ({missing_purities})" if missing_purities else ""
                details.append(f"{purchase.name}: missing {len(missing_lines)} piece(s){purity_info}")
            raise ValidationError(_(
                "All pieces/purities of an Old Gold Purchase in %s must be selected together for HO transfer.\n"
                "Please select the remaining piece(s) for:\n- %s"
            ) % (target_location.display_name, "\n- ".join(details)))

    def action_open_ho_transfer_wizard(self):
        self._validate_ho_transfer_lines()
        return {
            'name': _('HO Transfer'),
            'type': 'ir.actions.act_window',
            'res_model': 'old.gold.ho.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'sale.old.gold.line',
                'active_ids': self.ids,
                'active_id': self[0].id,
            },
        }

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
    amount_rounding = fields.Float(
        string="Round Off",
        default=0.0,
        help="Enter a signed adjustment, for example -5.50 to reduce the OG amount by 5.50.",
    )

    amount = fields.Float(string="Amount", compute='_compute_amount', store=True, readonly=False)


    stock_move_id = fields.Many2one('stock.move', readonly=True)
    ho_transfer_id = fields.Many2one('stock.picking', readonly=True)
    branch_id = fields.Many2one(related='old_gold_purchase_id.branch_id', string='Branch',
                                store=True)
    partner_id = fields.Many2one(related='old_gold_purchase_id.partner_id', string='Customer', store=True)
    date = fields.Datetime(related='old_gold_purchase_id.date', string='Date', store=True)
    company_id = fields.Many2one(related='old_gold_purchase_id.company_id', string='Company', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ho_transfer', 'HO Transfer'),
        ('done', 'Verified'),
        ('batched', 'Batched'),
    ], string='Status', compute='_compute_state', store=True)

    @api.depends('old_gold_purchase_id.state', 'ho_transfer_id')
    def _compute_state(self):
        for line in self:
            purchase_state = line.old_gold_purchase_id.state if line.old_gold_purchase_id else False
            if purchase_state in ('done', 'batched'):
                line.state = purchase_state
            elif line.ho_transfer_id:
                line.state = 'ho_transfer'
            else:
                line.state = purchase_state or 'draft'

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


    @api.depends('net_weight', 'rate', 'diamond_amount', 'amount_rounding')
    def _compute_amount(self):
        for rec in self:
            if not self.env.context.get('skip_old_gold_amount_compute'):
                rec.amount = (rec.net_weight * rec.rate) + rec.diamond_amount + rec.amount_rounding
            elif not rec.amount:
                rec.amount = (rec.net_weight * rec.rate) + rec.diamond_amount + rec.amount_rounding

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



