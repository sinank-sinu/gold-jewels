from odoo.exceptions import ValidationError

from odoo import models, fields,api,_

class OldGoldBatch(models.Model):
    _name = 'old.gold.batch'
    _description = 'Old Gold Batch'

    name = fields.Char(readonly=True)
    batch_date = fields.Date(required=True)

    branch_id = fields.Many2one(
        'res.branch',
        required=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='branch_id.company_id',
        store=True,
        readonly=True,
    )

    purity_id = fields.Many2one(
        'gold.purity',
        required=True
    )

    total_grams = fields.Float(digits=(16, 3))
    total_purchase_amount = fields.Float(readonly=True)
    is_smith_transfer = fields.Boolean(string="Smith Transfer Required")
    smith_transferred = fields.Boolean(string="Smith Transferred", default=False)
    is_diamond_og = fields.Boolean(
        string="Is Diamond OG",
        compute="_compute_is_diamond_og",
        store=True,
    )
    transferred_weight = fields.Float(
        string="Transferred Weight",
        digits=(16, 3),
        readonly=True,
        copy=False,
    )
    total_transferred_weight = fields.Float(
        string="Total Transferred to Smith",
        compute="_compute_smith_totals",
        store=True,
        digits=(16, 3)
    )
    ho_location_id = fields.Many2one(
        'stock.location',
        string="Source Location",
        compute="_compute_ho_location_id",
        store=True,
        readonly=False
    )
    current_location_id = fields.Many2one(
        'stock.location',
        string="Current Location",
        compute="_compute_current_location_id",
        store=True,
        readonly=True,
    )
    refinery_issue_id = fields.Many2one(
            'old.gold.refinery.issue',
            string="Refinery Issue",
            readonly=True
        )
    transfer_picking_ids = fields.Many2many(
        'stock.picking',
        'stock_picking_old_gold_batch_rel',
        'batch_id',
        'picking_id',
        string="Transfer References",
        readonly=True,
        copy=False,
    )
    mo_id = fields.Many2one('mrp.production', string="Manufacturing Order", readonly=True)
    line_ids = fields.One2many('sale.old.gold.line', 'batch_id', string="Lines")

    @api.depends('purity_id', 'purity_id.is_diamond_og')
    def _compute_is_diamond_og(self):
        for batch in self:
            is_dog = bool(
                (batch.purity_id and batch.purity_id.is_diamond_og) or
                (batch.purity_id and '18KTD' in (batch.purity_id.name or ''))
            )
            batch.is_diamond_og = is_dog
            if is_dog and not batch.is_smith_transfer:
                batch.is_smith_transfer = True

    @api.depends('transferred_weight', 'line_ids.transferred_weight')
    def _compute_smith_totals(self):
        for record in self:
            if record.line_ids:
                record.total_transferred_weight = sum(record.line_ids.mapped('transferred_weight'))
            else:
                record.total_transferred_weight = record.transferred_weight or 0.0

    @api.depends('line_ids.old_gold_purchase_id.ho_location_id', 'branch_id')
    def _compute_ho_location_id(self):
        for record in self:
            ho_loc = record.line_ids.mapped('old_gold_purchase_id.ho_location_id')[:1]
            if ho_loc:
                record.ho_location_id = ho_loc.id
            elif record.branch_id.old_gold_location_id:
                record.ho_location_id = record.branch_id.old_gold_location_id.id
            elif not record.ho_location_id:
                company = record.company_id or self.env.company
                loc = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('company_id', '=', company.id)
                ], limit=1)
                record.ho_location_id = loc.id if loc else False

    @api.depends(
        'ho_location_id',
        'branch_id.old_gold_location_id',
        'total_grams',
        'smith_transferred',
        'transfer_picking_ids.state',
        'transfer_picking_ids.location_dest_id',
        'refinery_issue_id.state',
        'refinery_issue_id.source_location_id',
        'refinery_issue_id.received_location_id',
        'mo_id.state',
        'mo_id.location_dest_id',
    )
    def _compute_current_location_id(self):
        StockPicking = self.env['stock.picking'].sudo()
        for record in self:
            location = False
            if (record.total_grams or 0.0) <= 0.0001:
                done_pickings = record.transfer_picking_ids.filtered(lambda p: p.state == 'done')
                if not done_pickings and record.id:
                    done_pickings = StockPicking.search([
                        ('state', '=', 'done'),
                        '|',
                        ('batch_id', '=', record.id),
                        ('batch_ids', 'in', [record.id]),
                    ])
                if done_pickings:
                    latest_picking = done_pickings.sorted(
                        key=lambda p: (p.date_done or p.create_date or fields.Datetime.now(), p.id),
                        reverse=True,
                    )[:1]
                    location = latest_picking.location_dest_id

            if not location and record.refinery_issue_id:
                if record.refinery_issue_id.state in ('melting', 'issued', 'received') and record.refinery_issue_id.received_location_id:
                    location = record.refinery_issue_id.received_location_id
                elif record.refinery_issue_id.source_location_id:
                    location = record.refinery_issue_id.source_location_id

            if not location and record.mo_id and record.mo_id.state == 'done' and record.mo_id.location_dest_id:
                location = record.mo_id.location_dest_id

            if not location:
                location = record.ho_location_id or record.branch_id.old_gold_location_id

            record.current_location_id = location.id if location else False

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

    def action_open_smith_transfer_wizard(self):
        if not self:
            return False
        companies = self.mapped('company_id')
        if len(companies) > 1:
            raise ValidationError(_(
                "Selected batches belong to different companies (%s). "
                "Please select batches from the same company."
            ) % ", ".join(companies.mapped('name')))

        pending_picking = self.env['stock.picking'].search([
            ('state', 'not in', ('done', 'cancel')),
            '|',
            ('batch_id', 'in', self.ids),
            ('batch_ids', 'in', self.ids),
        ], limit=1)
        if pending_picking:
            pending_batches = (pending_picking.batch_id | pending_picking.batch_ids) & self
            batch_names = ", ".join(pending_batches.mapped('name')) or self[:1].name
            raise ValidationError(_(
                "A transfer (%s) is already in progress for batch(es): %s. "
                "Please validate or cancel it before creating a new transfer."
            ) % (pending_picking.name, batch_names))

        title = _('Diamond Transfer') if all(b.is_diamond_og for b in self) else _('Transfer to Smith')
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'old.gold.smith.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self[0].id,
                'active_ids': self.ids,
                'active_model': 'old.gold.batch',
            }
        }

    def action_open_diamond_transfer_wizard(self):
        diamond_batches = self.filtered(lambda b: b.is_diamond_og)
        if not diamond_batches:
            raise ValidationError(_(
                "None of the selected batches have 18KTD(75.5) / Diamond OG purity."
            ))
        transferable_batches = diamond_batches.filtered(lambda b: b.total_grams > 0)
        if not transferable_batches:
            raise ValidationError(_(
                "Selected 18KTD(75.5) batch(es) have no remaining weight to transfer."
            ))
        return transferable_batches.action_open_smith_transfer_wizard()

    def action_view_transfers(self):
        self.ensure_one()
        domain = [
            ('is_old_gold', '=', True),
            '|', '|',
            ('batch_id', '=', self.id),
            ('batch_ids', 'in', [self.id]),
            ('origin', '=', self.name),
        ]
        pickings = self.env['stock.picking'].search(domain)
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Old Gold Transfers'),
            'res_model': 'stock.picking',
            'domain': domain,
            'context': {
                'default_origin': self.name,
                'default_batch_id': self.id,
                'default_is_old_gold': True,
            },
        }

        if len(pickings) == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = pickings.id
        else:
            action['views'] = [(False, 'tree'), (False, 'form')]

        return action


    def action_create_refinery_issue(self):
        RefineryIssue = self.env['old.gold.refinery.issue']
        RefineryIssueLine = self.env['old.gold.refinery.issue.line']

        if not self:
            return True

        # Validation: Check if 18KTD / Diamond OG batches are present
        diamond_batches = self.filtered(
            lambda b: b.is_diamond_og or (b.purity_id and (b.purity_id.is_diamond_og or '18KTD' in (b.purity_id.name or '')))
        )
        if diamond_batches:
            raise ValidationError(
                _("Cannot create melting: Batch(es) (%s) with purity 18KTD(75.5) cannot go for melting. "
                  "18KTD(75.5) should only be transferred by clicking Diamond Transfer. "
                  "Please unselect these batches to proceed.")
                % ", ".join(diamond_batches.mapped('name'))
            )

        batches = self

        # Validation: Check if batches from different companies are selected together
        companies = batches.mapped('branch_id.company_id')
        if len(companies) > 1:
            raise ValidationError(
                _("Cannot create melting: Selected batches belong to different companies (%s). "
                  "Please remove batches belonging to other companies and choose batches from the same company branches.")
                % ", ".join(companies.mapped('name'))
            )

        # Validation: Check if chosen batches belong to another company than active company
        current_company = self.env.company
        other_company_batches = batches.filtered(lambda b: b.branch_id.company_id != current_company)
        if other_company_batches:
            other_branches = ", ".join(set(other_company_batches.mapped('branch_id.name')))
            other_companies = ", ".join(set(other_company_batches.mapped('branch_id.company_id.name')))
            raise ValidationError(
                _("Cannot create melting: Batches from another company branch were chosen (%s - %s). "
                  "Please remove them and choose batches from the same company branches (%s).")
                % (other_branches, other_companies, current_company.name)
            )
        target_company = companies[0]
        user_branch = self.env.user.branch_id
        issue_branch = user_branch if user_branch and user_branch.company_id == target_company else batches[0].branch_id

        # Create single refinery issue
        issue = RefineryIssue.create({
            'issue_date': fields.Date.context_today(self),
            'branch_id': issue_branch.id,
            'company_id': target_company.id,
        })

        # Group by purity (weight + purchase amount)
        purity_map = {}

        for batch in batches:
            purity_id = batch.purity_id.id

            if purity_id not in purity_map:
                purity_map[purity_id] = {
                    'weight': 0.0,
                    'amount': 0.0,
                }

            purity_map[purity_id]['weight'] += batch.total_grams
            purity_map[purity_id]['amount'] += batch.total_purchase_amount

        # Create refinery issue lines
        for purity_id, values in purity_map.items():
            purity = self.env['gold.purity'].browse(purity_id)
            is_diamond = purity.is_diamond_og if purity else False
            product = RefineryIssueLine._get_company_old_gold_product(
                target_company.id, is_diamond_og=is_diamond
            )
            RefineryIssueLine.create({
                'issue_id': issue.id,
                'purity_id': purity_id,
                'product_id': product.id if product else False,
                'issue_weight': values['weight'],
                'purchase_amount': values['amount'],  # 👈 make sure field exists
            })

        # Link processed batches
        batches.write({'refinery_issue_id': issue.id})

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'old.gold.refinery.issue',
            'view_mode': 'form',
            'res_id': issue.id,
        }
