from odoo.exceptions import ValidationError

from odoo import models, fields,api,_


class OldGoldHOVerification(models.Model):
    _name = 'old.gold.ho.verification'
    _description = 'Old Gold HO Verification'

    def _get_branch_domain(self):
        """methode to get branch domain"""
        company = self.env.company
        branch_ids = self.env.user.branch_ids
        branch = branch_ids.filtered(
            lambda branch: branch.company_id == company)
        return [('id', 'in', branch.ids)]

    branch_id = fields.Many2one('res.branch', string='Branch', store=True,
                                domain=_get_branch_domain,
                                help='Leave this field empty if this account is'
                                     ' shared between all branches',
                                default=lambda self: self.env.user.branch_id.id, )

    name = fields.Char(
        default=lambda self: self.env['ir.sequence'].next_by_code('old.gold.ho.verification')
    )

    purchase_id = fields.Many2one(
        'old.gold.purchase',
        required=True,
        readonly=True
    )

    date = fields.Date(default=fields.Date.today)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('verified', 'Verified'),
        ('issued', 'Refinery Issued'),

    ], default='draft')

    line_ids = fields.One2many(
        'old.gold.ho.verification.line',
        'verification_id'
    )
    refinery_issue_id = fields.Many2one(
        'old.gold.refinery.issue',
        readonly=True
    )
    ho_location_id = fields.Many2one('stock.location')
    melting_location_id = fields.Many2one(
        'stock.location',
    )
    refinery_partner_id = fields.Many2one('res.partner')



    def action_verify(self):
        for rec in self:
            if rec.state != 'draft':
                continue

            # Safety check
            for line in rec.line_ids:
                if line.ho_received_weight <= 0:
                    raise ValidationError("HO received weight must be greater than zero.")

            rec.state = 'verified'
            rec.purchase_id.state = 'ho_verified'

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code(
                'old.gold.ho.verification'
            ) or 'New'
        return super().create(vals)

    def action_create_refinery_issue(self):
        StockPicking = self.env['stock.picking']
        StockMove = self.env['stock.move']

        refinery_location = self.env.ref('em_jewellery_management.loc_refinery')
        picking_type = self.env.ref('stock.picking_type_internal')
        product = self.env.ref('em_jewellery_management.product_old_gold')
        uom = self.env.ref('uom.product_uom_gram')

        for rec in self:
            if rec.state != 'verified':
                raise ValidationError(
                    _("Only verified records can be sent to refinery.")
                )

            if rec.refinery_issue_id:
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'old.gold.refinery.issue',
                    'view_mode': 'form',
                    'res_id': rec.refinery_issue_id.id,
                }

            # 1️⃣ Create Refinery Issue
            issue = self.env['old.gold.refinery.issue'].create({
                'verification_id': rec.id,
                'refinery_partner_id':rec.refinery_partner_id.id,
                'state': 'draft',
                'source_location_id':refinery_location.id,
                'line_ids': [
                    (0, 0, {
                        'purity_id': line.purity_id.id,
                        'issue_weight': line.ho_received_weight,
                    })
                    for line in rec.line_ids
                ]
            })

            # 2️⃣ Create Stock Picking
            picking = StockPicking.create({
                'picking_type_id': picking_type.id,
                'location_id': self.ho_location_id.id,
                'location_dest_id': refinery_location.id,
                'origin': issue.name,
                'is_old_gold': True,
            })

            # 3️⃣ Create Stock Moves (Purity-wise)
            for line in self.line_ids:
                self.env['stock.move'].create({
                    'product_id': product.id,
                    'name': 'Old Gold to Refinery',
                    'purity_id': line.purity_id.id,
                    'product_uom_qty': line.ho_received_weight,
                    'product_uom': uom.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'picking_id': picking.id,
                })

            # 4️⃣ Confirm & Validate Picking
            picking.action_confirm()
            picking.button_validate()

            # 5️⃣ Link records
            issue.picking_id = picking.id
            rec.refinery_issue_id = issue.id

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'old.gold.refinery.issue',
                'view_mode': 'form',
                'res_id': issue.id,
            }
    def action_view_og_issuse_transfers(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('ISSUE Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [
                ('origin', '=', self.name),
            ],

        }




class OldGoldHOVerificationLine(models.Model):
    _name = 'old.gold.ho.verification.line'
    _description = 'Old Gold HO Verification Line'

    verification_id = fields.Many2one(
        'old.gold.ho.verification',
        ondelete='cascade'
    )

    purity_id = fields.Many2one('gold.purity', required=True)

    branch_net_weight = fields.Float(
        string="Branch Net Weight",
        readonly=True,digits=(16, 3)
    )

    ho_received_weight = fields.Float(
        string="HO Received Weight",
        required=True,digits=(16, 3)
    )

    difference = fields.Float(
        compute='_compute_difference',
        store=True,digits=(16, 3)
    )

    @api.depends('branch_net_weight', 'ho_received_weight')
    def _compute_difference(self):
        for r in self:
            r.difference = r.ho_received_weight - r.branch_net_weight

