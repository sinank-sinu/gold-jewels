from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class OldGoldSmithTransferWizard(models.TransientModel):
    _name = 'old.gold.smith.transfer.wizard'
    _description = 'Old Gold Smith Transfer Wizard'

    batch_id = fields.Many2one('old.gold.batch', string="Old Gold Batch", readonly=True)
    batch_ids = fields.Many2many('old.gold.batch', string="Old Gold Batches", readonly=True)
    purchase_id = fields.Many2one('old.gold.purchase', string="Old Gold Purchase", readonly=True)
    location_dest_id = fields.Many2one('stock.location', string="Destination Location", required=True)
    
    line_ids = fields.One2many('old.gold.smith.transfer.wizard.line', 'wizard_id', string="Transfer Lines")

    @api.model
    def default_get(self, fields_list):
        res = super(OldGoldSmithTransferWizard, self).default_get(fields_list)
        active_id = self._context.get('active_id')
        active_ids = self._context.get('active_ids')
        active_model = self._context.get('active_model')

        if active_model == 'old.gold.batch' and (active_ids or active_id):
            batch_ids = active_ids if active_ids else [active_id]
            batches = self.env['old.gold.batch'].browse(batch_ids).exists()
            if len(batches) == 1:
                res['batch_id'] = batches.id
            res['batch_ids'] = [(6, 0, batches.ids)]
            lines = []
            for batch in batches:
                if batch.total_grams <= 0:
                    continue
                batch_lines = []
                if batch.line_ids:
                    for line in batch.line_ids:
                        avail = line.remaining_weight if line.remaining_weight > 0 else line.verified_net_weight
                        if avail > 0:
                            batch_lines.append((0, 0, {
                                'batch_id': batch.id,
                                'purchase_line_id': line.id,
                                'purity_id': (line.verified_purity_id or line.purity_id).id,
                                'available_weight': avail,
                                'transfer_weight': 0.0,
                            }))
                if not batch_lines and batch.total_grams > 0:
                    avail = max(0.0, batch.total_grams)
                    batch_lines.append((0, 0, {
                        'batch_id': batch.id,
                        'purity_id': batch.purity_id.id,
                        'available_weight': avail,
                        'transfer_weight': 0.0,
                    }))
                lines.extend(batch_lines)
            res['line_ids'] = lines
        elif active_id and active_model == 'old.gold.purchase':
            purchase = self.env['old.gold.purchase'].browse(active_id)
            res['purchase_id'] = purchase.id
            lines = []
            for line in purchase.old_gold_line_ids:
                if line.remaining_weight > 0:
                    lines.append((0, 0, {
                        'purchase_line_id': line.id,
                        'purity_id': (line.verified_purity_id or line.purity_id).id,
                        'available_weight': line.remaining_weight,
                        'transfer_weight': 0.0,
                    }))
            res['line_ids'] = lines
        return res

    def action_fill_full_weights(self):
        self.ensure_one()
        for line in self.line_ids:
            line.transfer_weight = line.available_weight
        title = (
            _('Diamond Transfer')
            if self.batch_ids and all(b.is_diamond_og for b in self.batch_ids)
            else _('Transfer to Smith')
        )
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _get_internal_picking_type(self, company_id):
        picking_type = self.env['stock.picking.type'].sudo().search([
            ('code', '=', 'internal'),
            ('company_id', '=', company_id)
        ], limit=1)
        if not picking_type:
            picking_type = self.env.ref('stock.picking_type_internal').sudo()
        return picking_type

    def _get_transfer_product(self, record, company, is_diamond_og=False):
        company_id = company.id
        product = False
        if record and hasattr(record, '_get_old_gold_product'):
            product = record._get_old_gold_product(is_diamond_og=is_diamond_og)
        if not product:
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
            if not product:
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
        if not product:
            raise ValidationError(_("Old Gold product not configured for company %s.") % (company.name or ''))
        return product

    def _get_batch_source_location(self, batch, picking_type):
        source_location = False
        if batch:
            source_location = (
                batch.ho_location_id
                or batch.line_ids.mapped('old_gold_purchase_id.ho_location_id')[:1]
                or batch.branch_id.old_gold_location_id
            )
        if not source_location:
            source_location = picking_type.default_location_src_id
        if not source_location:
            raise ValidationError(_("Source Location is required for transfer."))
        return source_location

    def _create_picking_moves(self, picking, lines, company, fallback_record=False, fallback_batch=False, line_source_map=None):
        company_id = company.id
        default_product = self._get_transfer_product(fallback_record, company)
        default_uom = default_product.uom_id

        for line in lines:
            line_batch = line.batch_id or fallback_batch
            avail = line.available_weight
            if not avail:
                if line.purchase_line_id:
                    avail = line.purchase_line_id.remaining_weight or line.purchase_line_id.verified_net_weight
                elif line_batch:
                    avail = line_batch.total_grams
            purity = line.purity_id or (line_batch and line_batch.purity_id)
            if line.transfer_weight > (avail or 0.0):
                purity_label = purity.name if purity else ''
                raise ValidationError(_("Transfer weight for %s exceeds available weight.") % purity_label)

            is_diamond = (line.purchase_line_id and line.purchase_line_id.is_diamond_og) or (purity and purity.is_diamond_og)
            record_for_product = fallback_record or line_batch
            line_product = self._get_transfer_product(record_for_product, company, is_diamond_og=is_diamond) or default_product
            line_uom = line_product.uom_id or default_uom
            move_location = line_source_map.get(line.id, picking.location_id) if line_source_map else picking.location_id

            purity_name = purity.name if purity else ""
            self.env['stock.move'].sudo().create({
                'product_id': line_product.id,
                'name': f'Old Gold Transfer to Smith ({purity_name})',
                'purity_id': purity.id if purity else False,
                'product_uom_qty': line.transfer_weight,
                'product_uom': line_uom.id,
                'location_id': move_location.id,
                'location_dest_id': self.location_dest_id.id,
                'picking_id': picking.id,
                'company_id': company_id,
                'old_gold_line_id': line.purchase_line_id.id if line.purchase_line_id else False,
                'batch_id': line_batch.id if line_batch else False,
            })

    def action_transfer(self):
        self.ensure_one()
        valid_lines = self.line_ids.filtered(lambda l: l.transfer_weight > 0)
        if not valid_lines:
            raise ValidationError(_("Please enter weights to transfer."))

        batches = self.batch_ids or self.batch_id
        purchase = self.purchase_id

        if batches:
            companies = batches.mapped('company_id')
            if len(companies) > 1:
                raise ValidationError(_("Selected batches must belong to the same company."))
            company = companies[:1] or self.env.company
            company_id = company.id
            picking_type = self._get_internal_picking_type(company_id)

            lines_by_branch_source = {}
            for line in valid_lines:
                line_batch = line.batch_id or self.batch_id or (line.purchase_line_id.batch_id if line.purchase_line_id else False)
                source_location = self._get_batch_source_location(line_batch, picking_type)
                branch = line_batch.branch_id if line_batch else self.env['res.branch']
                key = (branch, source_location)
                lines_by_branch_source.setdefault(key, self.env['old.gold.smith.transfer.wizard.line'])
                lines_by_branch_source[key] |= line

            created_pickings = self.env['stock.picking']
            all_transfer_batches = self.env['old.gold.batch']
            for (branch, source_location), group_lines in lines_by_branch_source.items():
                group_batches = group_lines.mapped('batch_id') or (self.batch_id if self.batch_id else batches[:1])
                all_transfer_batches |= group_batches
                origin_name = ", ".join(group_batches.mapped('name'))
                picking_vals = {
                    'picking_type_id': picking_type.id,
                    'location_id': source_location.id,
                    'location_dest_id': self.location_dest_id.id,
                    'origin': origin_name,
                    'is_old_gold': True,
                    'is_multiple_transfer': False,
                    'company_id': company_id,
                    'batch_ids': [(6, 0, group_batches.ids)],
                }
                if branch and 'branch_id' in self.env['stock.picking']._fields:
                    picking_vals['branch_id'] = branch.id
                if len(group_batches) == 1:
                    picking_vals['batch_id'] = group_batches.id

                picking = self.env['stock.picking'].sudo().create(picking_vals)
                self._create_picking_moves(
                    picking,
                    group_lines,
                    company,
                    fallback_batch=group_batches[:1],
                )
                picking.sudo().action_confirm()
                created_pickings |= picking

            title = _('Diamond Transfers') if all(b.is_diamond_og for b in all_transfer_batches) else _('Old Gold Transfers')
            action = {
                'name': title,
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'target': 'current',
            }
            if len(created_pickings) == 1:
                action['view_mode'] = 'form'
                action['res_id'] = created_pickings.id
            else:
                action['view_mode'] = 'tree,form'
                action['domain'] = [('id', 'in', created_pickings.ids)]
            return action

        company = (purchase and purchase.company_id) or self.env.company
        company_id = company.id
        picking_type = self._get_internal_picking_type(company_id)

        source_location = (purchase and purchase.ho_location_id) or picking_type.default_location_src_id
        if not source_location:
            raise ValidationError(_("Source Location is required for transfer."))

        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': source_location.id,
            'location_dest_id': self.location_dest_id.id,
            'origin': (purchase and purchase.name) or '',
            'is_old_gold': True,
            'company_id': company_id,
        }
        if purchase and purchase.sale_id:
            picking_vals['sale_old_id'] = purchase.sale_id.id

        picking = self.env['stock.picking'].sudo().create(picking_vals)
        self._create_picking_moves(picking, valid_lines, company, fallback_record=purchase)
        picking.sudo().action_confirm()
        return {'type': 'ir.actions.act_window_close'}


class OldGoldSmithTransferWizardLine(models.TransientModel):
    _name = 'old.gold.smith.transfer.wizard.line'
    _description = 'Old Gold Smith Transfer Wizard Line'

    wizard_id = fields.Many2one('old.gold.smith.transfer.wizard')
    batch_id = fields.Many2one('old.gold.batch', string="Batch", readonly=True)
    branch_id = fields.Many2one('res.branch', related='batch_id.branch_id', string="Branch", readonly=True)
    purchase_line_id = fields.Many2one('sale.old.gold.line', string="Purchase Line")
    purity_id = fields.Many2one('gold.purity', string="Purity", compute="_compute_purity_id", store=True, readonly=False)
    available_weight = fields.Float(string="Available Weight", digits=(16, 3), compute="_compute_available_weight", store=True, readonly=False)
    transfer_weight = fields.Float(string="Transfer Weight", digits=(16, 3))

    @api.depends('wizard_id.batch_id', 'batch_id', 'purchase_line_id')
    def _compute_available_weight(self):
        for line in self:
            if line.purchase_line_id:
                line.available_weight = line.purchase_line_id.remaining_weight if line.purchase_line_id.remaining_weight > 0 else line.purchase_line_id.verified_net_weight
            elif line.batch_id:
                line.available_weight = line.batch_id.total_grams
            elif line.wizard_id.batch_id:
                line.available_weight = line.wizard_id.batch_id.total_grams
            elif not line.available_weight:
                line.available_weight = 0.0

    @api.depends('wizard_id.batch_id', 'batch_id', 'purchase_line_id')
    def _compute_purity_id(self):
        for line in self:
            if line.purchase_line_id:
                line.purity_id = (line.purchase_line_id.verified_purity_id or line.purchase_line_id.purity_id).id
            elif line.batch_id:
                line.purity_id = line.batch_id.purity_id.id
            elif line.wizard_id.batch_id:
                line.purity_id = line.wizard_id.batch_id.purity_id.id
            elif not line.purity_id:
                line.purity_id = False
