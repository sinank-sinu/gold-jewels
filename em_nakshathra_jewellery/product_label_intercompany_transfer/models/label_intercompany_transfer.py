# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LabelIntercompanyTransfer(models.Model):
    _name = 'label.intercompany.transfer'
    _description = 'Inter-Company Product Label Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string="Transfer Reference",
        required=True,
        copy=False,
        readonly=True,
        default='New',
        tracking=True
    )
    source_company_id = fields.Many2one(
        'res.company',
        string="Source Company",
        required=True,
        default=lambda self: self.env.company,
        tracking=True
    )
    source_branch_id = fields.Many2one(
        'res.branch',
        string="Source Branch",
        default=lambda self: self.env.user.branch_id or self.env['res.branch'].search([
            ('company_id', '=', self.env.company.id)
        ], limit=1),
        domain="[('company_id', '=', source_company_id)]",
        tracking=True
    )
    source_location_id = fields.Many2one(
        'stock.location',
        string="Source Location",
        domain="[('company_id', 'in', [source_company_id, False]), ('usage', '=', 'internal')]"
    )
    dest_company_id = fields.Many2one(
        'res.company',
        string="Destination Company",
        required=True,
        domain="[('id', '!=', source_company_id)]",
        tracking=True
    )
    dest_branch_id = fields.Many2one(
        'res.branch',
        string="Destination Branch",
        required=True,
        domain="[('company_id', '=', dest_company_id)]",
        tracking=True
    )
    dest_location_id = fields.Many2one(
        'stock.location',
        string="Destination Location",
        required=True,
        domain="[('company_id', 'in', [dest_company_id, False]), ('usage', '=', 'internal')]"
    )
    transfer_date = fields.Date(
        string="Transfer Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True
    )
    user_id = fields.Many2one(
        'res.users',
        string="Responsible",
        default=lambda self: self.env.user,
        tracking=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('transferred', 'Transferred'),
        ('cancel', 'Cancelled'),
    ], string="Status", default='draft', readonly=True, copy=False, tracking=True)

    scan_barcode = fields.Char(
        string="Scan / Enter Barcode",
        copy=False,
        help="Scan or type a label barcode or label number and press Enter to add it to the transfer lines."
    )
    line_ids = fields.One2many(
        'label.intercompany.transfer.line',
        'transfer_id',
        string="Labels to Transfer",
        copy=True
    )

    # Computed Totals
    total_labels = fields.Integer(
        string="Total Labels",
        compute="_compute_totals",
        store=True
    )
    total_gross_weight = fields.Float(
        string="Total Gross Wt (g)",
        digits=(16, 3),
        compute="_compute_totals",
        store=True
    )
    total_net_weight = fields.Float(
        string="Total Net Wt (g)",
        digits=(16, 3),
        compute="_compute_totals",
        store=True
    )
    total_fine_weight = fields.Float(
        string="Total Fine Wt (g)",
        digits=(16, 3),
        compute="_compute_totals",
        store=True
    )
    total_cost = fields.Float(
        string="Total Taxable Value",
        digits=(16, 2),
        compute="_compute_totals",
        store=True
    )
    total_tax = fields.Float(
        string="Total Tax",
        digits=(16, 2),
        compute="_compute_totals",
        store=True
    )
    total_amount_with_tax = fields.Float(
        string="Total Transfer Value",
        digits=(16, 2),
        compute="_compute_totals",
        store=True
    )
    is_interstate = fields.Boolean(
        string="Is Inter-State Transfer",
        compute="_compute_is_interstate",
        store=True
    )
    sale_tax_id = fields.Many2one(
        'account.tax',
        string="Sales Tax (Source)",
        default=lambda self: self.env.company.account_sale_tax_id,
        domain="[('company_id', '=', source_company_id), ('type_tax_use', '=', 'sale')]",
        help="Tax applied to the Source Sale Order and Customer Invoice."
    )
    purchase_tax_id = fields.Many2one(
        'account.tax',
        string="Purchase Tax (Destination)",
        domain="[('company_id', '=', dest_company_id), ('type_tax_use', '=', 'purchase')]",
        help="Tax applied to the Destination Purchase Order and Vendor Bill."
    )

    # Generated Documents
    result_so_id = fields.Many2one(
        'sale.order',
        string="Source Sale Order",
        readonly=True,
        copy=False
    )
    result_invoice_id = fields.Many2one(
        'account.move',
        string="Source Customer Invoice",
        readonly=True,
        copy=False
    )
    result_po_id = fields.Many2one(
        'purchase.order',
        string="Destination Purchase Order",
        readonly=True,
        copy=False
    )
    result_bill_id = fields.Many2one(
        'account.move',
        string="Destination Vendor Bill",
        readonly=True,
        copy=False
    )
    transferred_label_ids = fields.Many2many(
        'product.label',
        'label_intercompany_doc_transferred_rel',
        'transfer_id',
        'label_id',
        string="Transferred Labels (Destination)",
        readonly=True,
        copy=False
    )
    notes = fields.Text(string="Notes")
    transporter_name = fields.Char(string="Transporter / Custodian Staff", tracking=True)
    vehicle_number = fields.Char(string="Vehicle / Courier Docket No.", tracking=True)
    eway_bill_number = fields.Char(string="E-Way Bill Number", tracking=True)

    def action_print_challan(self):
        self.ensure_one()
        return self.env.ref('product_label_intercompany_transfer.action_report_intercompany_delivery_challan').report_action(self)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            seq = self.env['ir.sequence'].next_by_code('label.intercompany.transfer')
            vals['name'] = seq or 'New'
        if not vals.get('source_branch_id') and vals.get('source_company_id'):
            branch = self.env['res.branch'].search([
                ('company_id', '=', vals['source_company_id'])
            ], limit=1)
            if branch:
                vals['source_branch_id'] = branch.id
        if not vals.get('sale_tax_id') and vals.get('source_company_id'):
            src_comp = self.env['res.company'].browse(vals['source_company_id'])
            dest_comp = self.env['res.company'].browse(vals['dest_company_id']) if vals.get('dest_company_id') else False
            is_interstate = bool(src_comp and dest_comp and src_comp.state_id != dest_comp.state_id)
            taxes = self._get_intercompany_taxes(src_comp, 'sale', is_interstate)
            if taxes:
                vals['sale_tax_id'] = taxes[0].id
        if not vals.get('purchase_tax_id') and vals.get('dest_company_id'):
            dest_comp = self.env['res.company'].browse(vals['dest_company_id'])
            src_comp = self.env['res.company'].browse(vals['source_company_id']) if vals.get('source_company_id') else False
            is_interstate = bool(src_comp and dest_comp and src_comp.state_id != dest_comp.state_id)
            taxes = self._get_intercompany_taxes(dest_comp, 'purchase', is_interstate)
            if taxes:
                vals['purchase_tax_id'] = taxes[0].id
        return super().create(vals)

    @api.depends('source_company_id', 'dest_company_id')
    def _compute_is_interstate(self):
        for rec in self:
            rec.is_interstate = bool(
                rec.source_company_id and rec.dest_company_id and
                rec.source_company_id.state_id != rec.dest_company_id.state_id
            )

    @api.depends('line_ids', 'line_ids.gross_weight', 'line_ids.net_weight', 'line_ids.fine_weight', 'line_ids.subtotal', 'sale_tax_id', 'purchase_tax_id')
    def _compute_totals(self):
        for rec in self:
            lines = rec.line_ids
            rec.total_labels = len(lines)
            rec.total_gross_weight = round(sum(lines.mapped('gross_weight')), 3)
            rec.total_net_weight = round(sum(lines.mapped('net_weight')), 3)
            rec.total_fine_weight = round(sum(lines.mapped('fine_weight')), 3)
            taxable = round(sum(lines.mapped('subtotal')), 2)
            rec.total_cost = taxable
            tax_rec = rec.sale_tax_id or rec.purchase_tax_id
            if tax_rec:
                tax_res = tax_rec.compute_all(taxable, currency=rec.source_company_id.currency_id, quantity=1.0)
                rec.total_tax = round(tax_res['total_included'] - tax_res['total_excluded'], 2)
            else:
                rec.total_tax = round(taxable * 0.03, 2)
            rec.total_amount_with_tax = rec.total_cost + rec.total_tax

    def _get_active_gold_rate(self, purity, date=None):
        """Retrieve active gold board rate for a given purity on or before transfer date."""
        if not purity:
            return 0.0
        domain = [
            ('purity_id', '=', purity.id),
            ('active', '=', True),
        ]
        if date:
            domain.append(('date', '<=', date))
        rate_rec = self.env['gold.rate.master'].search(domain, order='date desc, id desc', limit=1)
        if not rate_rec:
            rate_rec = self.env['gold.rate.master'].search([
                ('purity_id', '=', purity.id)
            ], order='date desc, id desc', limit=1)
        return rate_rec.rate_per_gram if rate_rec else 0.0

    def _get_intercompany_taxes(self, company, tax_use, is_interstate):
        """Find appropriate 3% GST taxes:
        If intra-state: use company default configured tax from Accounting Settings (Sales Tax / Purchase Tax 3% GST).
        If inter-state: use 3% IGST tax for the company.
        """
        if not is_interstate:
            if tax_use == 'sale' and company.account_sale_tax_id:
                return company.account_sale_tax_id
            elif tax_use == 'purchase' and company.account_purchase_tax_id:
                return company.account_purchase_tax_id

            tax = self.env['account.tax'].sudo().with_company(company).search([
                ('company_id', '=', company.id),
                ('type_tax_use', '=', tax_use),
                ('name', '=', '3% GST'),
            ], limit=1)
            if tax:
                return tax
            taxes = self.env['account.tax'].sudo().with_company(company).search([
                ('company_id', '=', company.id),
                ('type_tax_use', '=', tax_use),
                ('name', 'ilike', '1.5%')
            ])
            if len(taxes) < 2:
                taxes = self.env['account.tax'].sudo().with_company(company).search([
                    ('company_id', '=', company.id),
                    ('type_tax_use', '=', tax_use),
                    ('amount', '=', 1.5)
                ])
            return taxes
        else:
            tax = self.env['account.tax'].sudo().with_company(company).search([
                ('company_id', '=', company.id),
                ('type_tax_use', '=', tax_use),
                ('name', 'ilike', '3% IGST')
            ], limit=1)
            if not tax:
                tax = self.env['account.tax'].sudo().with_company(company).search([
                    ('company_id', '=', company.id),
                    ('type_tax_use', '=', tax_use),
                    ('amount', '=', 3.0)
                ], limit=1)
            if tax:
                return tax
            if tax_use == 'sale' and company.account_sale_tax_id:
                return company.account_sale_tax_id
            elif tax_use == 'purchase' and company.account_purchase_tax_id:
                return company.account_purchase_tax_id
            return self.env['account.tax']

    @api.onchange('source_company_id')
    def _onchange_source_company_id(self):
        self.source_branch_id = False
        self.source_location_id = False
        if self.source_company_id:
            taxes = self._get_intercompany_taxes(self.source_company_id, 'sale', self.is_interstate)
            self.sale_tax_id = taxes[0].id if taxes else False
            branch = self.env['res.branch'].search([
                ('company_id', '=', self.source_company_id.id),
                ('branch_code', '!=', False)
            ], limit=1)
            if branch:
                self.source_branch_id = branch.id
                loc = self.env['stock.location'].search([
                    ('company_id', '=', self.source_company_id.id),
                    ('branch_id', '=', branch.id),
                    ('usage', '=', 'internal')
                ], limit=1)
                self.source_location_id = loc.id if loc else False

    @api.onchange('dest_company_id')
    def _onchange_dest_company_id(self):
        self.dest_branch_id = False
        self.dest_location_id = False
        if self.dest_company_id:
            taxes = self._get_intercompany_taxes(self.dest_company_id, 'purchase', self.is_interstate)
            self.purchase_tax_id = taxes[0].id if taxes else False
            branch = self.env['res.branch'].search([
                ('company_id', '=', self.dest_company_id.id),
                ('branch_code', '!=', False)
            ], limit=1)
            if branch:
                self.dest_branch_id = branch.id
                self._onchange_dest_branch_id()

    @api.onchange('dest_branch_id')
    def _onchange_dest_branch_id(self):
        self.dest_location_id = False
        if self.dest_branch_id and self.dest_company_id:
            loc = self.env['stock.location'].search([
                ('company_id', '=', self.dest_company_id.id),
                ('branch_id', '=', self.dest_branch_id.id),
                ('usage', '=', 'internal')
            ], limit=1)
            if not loc:
                loc = self.env['stock.location'].search([
                    ('company_id', '=', self.dest_company_id.id),
                    ('usage', '=', 'internal')
                ], limit=1)
            if loc:
                self.dest_location_id = loc.id

    @api.onchange('scan_barcode')
    def _onchange_scan_barcode(self):
        if not self.scan_barcode:
            return

        code = self.scan_barcode.strip()
        self.scan_barcode = False

        if not self.source_company_id:
            return {
                'warning': {
                    'title': _('Source Company Missing'),
                    'message': _('Please select the Source Company before scanning labels.')
                }
            }

        domain = [
            ('company_id', '=', self.source_company_id.id),
            '|', ('barcode', '=', code), ('name', '=', code),
            ('active', '=', True)
        ]
        label = self.env['product.label'].search(domain, limit=1)

        if not label:
            return {
                'warning': {
                    'title': _('Label Not Found'),
                    'message': _('No active label with barcode or number "%s" found in %s.') % (
                        code, self.source_company_id.name
                    )
                }
            }

        if label.is_transferred:
            return {
                'warning': {
                    'title': _('Label Already Transferred'),
                    'message': _('Label %s has already been transferred to another company.') % label.name
                }
            }

        existing_label_ids = self.line_ids.mapped('label_id.id')
        if label.id in existing_label_ids:
            return {
                'warning': {
                    'title': _('Duplicate Label'),
                    'message': _('Label %s is already added to this transfer.') % label.name
                }
            }

        new_line = self.env['label.intercompany.transfer.line'].new({
            'transfer_id': self.id,
            'label_id': label.id,
        })
        self.line_ids += new_line

    def action_cancel(self):
        for rec in self:
            if rec.state == 'transferred':
                raise UserError(_("Cannot cancel an already completed transfer."))
            rec.state = 'cancel'

    def action_draft(self):
        for rec in self:
            if rec.state == 'transferred':
                raise UserError(_("Cannot reset a completed transfer to draft."))
            rec.state = 'draft'

    def action_transfer(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only draft transfers can be processed."))

        if not self.line_ids:
            raise UserError(_("Please add at least one label to transfer."))

        if not self.dest_company_id:
            raise UserError(_("Please select a Destination Company."))

        if not self.dest_branch_id:
            raise UserError(_("Please select a Destination Branch."))

        if not self.dest_location_id:
            raise UserError(_("Please select a Destination Location."))

        if self.source_company_id == self.dest_company_id:
            raise UserError(_("Source and Destination Companies must be different."))

        source_company = self.source_company_id
        source_branch = self.source_branch_id
        source_location = self.source_location_id
        dest_company = self.dest_company_id
        dest_branch = self.dest_branch_id
        dest_location = self.dest_location_id
        transfer_date = self.transfer_date or fields.Date.context_today(self)
        labels = self.line_ids.mapped('label_id')

        # 1. Source Company: Create & Confirm Sale Order, Validate Delivery, and Post Customer Invoice
        so, invoice = self._create_source_sale_order(
            source_company=source_company,
            source_branch=source_branch,
            source_location=source_location,
            dest_company=dest_company,
            labels=labels,
            transfer_date=transfer_date
        )

        # 2. Archive Source Labels
        for label in labels:
            label.sudo().write({
                'active': False,
                'is_transferred': True,
                'transfer_dest_company_id': dest_company.id,
                'transfer_date': transfer_date,
                'transfer_notes': f"Transferred via {self.name} (SO: {so.name if so else 'N/A'}) to {dest_company.name} ({dest_branch.name})",
            })

        # 3. Destination Company: Find or create Vendor Partner representing Source Company
        supplier_partner = self._get_or_create_intercompany_partner(source_company, dest_company)

        # 4. Destination Company: Create and Confirm Purchase Order
        po = self._create_destination_purchase_order(
            source_company=source_company,
            dest_company=dest_company,
            dest_branch=dest_branch,
            supplier_partner=supplier_partner,
            labels=labels,
            transfer_date=transfer_date,
            so=so
        )

        # 5. Destination Company: Validate Incoming Stock Picking
        self._validate_destination_picking(po, dest_company, dest_location, transfer_date)

        # 6. Destination Company: Generate and Post Approved Vendor Bill
        bill = self._create_destination_vendor_bill(po, dest_company, supplier_partner, transfer_date)

        # 7. Destination Company: Create Product Labels linked to PO with EXACT SAME NAME & BARCODE
        created_labels = self._create_destination_labels(
            po=po,
            dest_company=dest_company,
            dest_branch=dest_branch,
            dest_location=dest_location,
            labels=labels
        )

        # 8. Map created labels back to transfer lines & source labels
        label_map = {l.name: l for l in created_labels}
        for line in self.line_ids:
            if line.label_id.name in label_map:
                dest_lbl = label_map[line.label_id.name]
                line.dest_label_id = dest_lbl.id
                line.label_id.sudo().write({'transfer_dest_label_id': dest_lbl.id})

        # 9. Update Document State & References
        self.write({
            'state': 'transferred',
            'result_so_id': so.id if so else False,
            'result_invoice_id': invoice.id if invoice else False,
            'result_po_id': po.id,
            'result_bill_id': bill.id if bill else False,
            'transferred_label_ids': [(6, 0, created_labels.ids)],
        })

        self.message_post(body=_(
            "Successfully transferred %d labels to %s (%s).<br/>"
            "Source Sale Order: <b>%s</b> | Invoice: <b>%s</b><br/>"
            "Destination Purchase Order: <b>%s</b> | Bill: <b>%s</b>"
        ) % (
            len(created_labels), dest_company.name, dest_branch.name,
            so.name if so else 'N/A', invoice.name if invoice else 'N/A',
            po.name, bill.name if bill else 'N/A'
        ))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Successful!'),
                'message': _('%d labels transferred to %s. SO: %s | PO: %s') % (
                    len(created_labels), dest_company.name, so.name if so else 'N/A', po.name
                ),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'label.intercompany.transfer',
                    'res_id': self.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                }
            }
        }

    def _create_source_sale_order(self, source_company, source_branch, source_location, dest_company, labels, transfer_date):
        """Create and confirm a Sale Order in Source Company for the Destination Company, validate delivery, and post invoice."""
        # 1. Resolve Customer Partner representing Destination Company in Source Company
        customer_partner = self.env['res.partner'].sudo().with_company(source_company).search([
            ('name', '=ilike', dest_company.name.strip()),
            '|', ('company_id', '=', source_company.id), ('company_id', '=', False)
        ], limit=1)

        if not customer_partner:
            customer_partner = self.env['res.partner'].sudo().with_company(source_company).search([
                ('name', 'ilike', 'NAKSHATHRA'),
                ('name', 'ilike', dest_company.name[:10]),
                '|', ('company_id', '=', source_company.id), ('company_id', '=', False)
            ], limit=1)

        if not customer_partner:
            customer_partner = self.env['res.partner'].sudo().with_company(source_company).create({
                'name': dest_company.name,
                'company_type': 'company',
                'is_company': True,
                'customer_rank': 1,
                'company_id': source_company.id,
            })

        so_vals = {
            'partner_id': customer_partner.id,
            'company_id': source_company.id,
            'date_order': transfer_date,
            'origin': f"Inter-Company Transfer {self.name} to {dest_company.name}",
        }
        if source_branch:
            so_vals['branch_id'] = source_branch.id

        so = self.env['sale.order'].sudo().with_company(source_company).create(so_vals)

        is_interstate = (source_company.state_id != dest_company.state_id)
        sale_taxes = self.sale_tax_id or self._get_intercompany_taxes(source_company, 'sale', is_interstate)

        for label in labels:
            gross_wt = label.sale_gross_weight or label.purchase_gross_weight or 1.0
            net_wt = label.sale_net_weight or label.purchase_net_weight or gross_wt
            purity = label.purity_id or label.sale_purity_id
            rate = self._get_active_gold_rate(purity, transfer_date)
            if not rate:
                rate = label.purchase_price_per_gram or label.sale_price_per_gram or label.purchase_metal_rate or 0.0

            stone_rate = label.sale_stone_rate or label.purchase_stone_rate or 0.0
            diamond_rate = label.sale_diamond_rate or label.purchase_diamond_rate or 0.0
            metal_val = round(net_wt * rate, 2)
            total_item_val = metal_val + stone_rate + diamond_rate
            unit_price = round(total_item_val / gross_wt, 4) if gross_wt else rate

            line_vals = {
                'order_id': so.id,
                'product_id': label.product_id.id,
                'label_id': label.id,
                'product_uom_qty': gross_wt,
                'price_unit': unit_price,
            }
            if sale_taxes:
                line_vals['tax_id'] = [(6, 0, sale_taxes.ids)]
            if label.purity_id and 'purity_id' in self.env['sale.order.line']._fields:
                line_vals['purity_id'] = label.purity_id.id
            if source_branch and 'branch_id' in self.env['sale.order.line']._fields:
                line_vals['branch_id'] = source_branch.id
            if 'gold_rate' in self.env['sale.order.line']._fields:
                line_vals['gold_rate'] = rate
            if 'net_weight' in self.env['sale.order.line']._fields:
                line_vals['net_weight'] = net_wt
            if 'sale_stone_rate' in self.env['sale.order.line']._fields:
                line_vals['sale_stone_rate'] = stone_rate
            if 'sale_diamond_rate' in self.env['sale.order.line']._fields:
                line_vals['sale_diamond_rate'] = diamond_rate
            if 'mc_percent_actual' in self.env['sale.order.line']._fields:
                line_vals['mc_percent_actual'] = 0.0
            if 'mc_amount_actual' in self.env['sale.order.line']._fields:
                line_vals['mc_amount_actual'] = 0.0
            if 'price_subtotal' in self.env['sale.order.line']._fields:
                line_vals['price_subtotal'] = total_item_val

            self.env['sale.order.line'].sudo().with_company(source_company).create(line_vals)

        if sale_taxes:
            so.order_line.sudo().write({'tax_id': [(6, 0, sale_taxes.ids)]})

        try:
            so.action_confirm()
        except Exception as e:
            _logger.warning("Could not auto-confirm sale order %s: %s", so.name, e)

        # Validate delivery pickings
        for picking in so.picking_ids:
            if picking.state in ['done', 'cancel']:
                continue
            for move in picking.move_ids:
                if move.label_id and move.label_id.branch_location_id:
                    picking.sudo().with_company(source_company).write({'location_id': move.label_id.branch_location_id.id})
                    move.sudo().with_company(source_company).write({
                        'location_id': move.label_id.branch_location_id.id,
                        'quantity': move.product_uom_qty,
                    })
                elif source_location:
                    picking.sudo().with_company(source_company).write({'location_id': source_location.id})
                    move.sudo().with_company(source_company).write({
                        'location_id': source_location.id,
                        'quantity': move.product_uom_qty,
                    })
                else:
                    move.sudo().with_company(source_company).write({
                        'quantity': move.product_uom_qty,
                    })
            try:
                picking.button_validate()
                picking.write({'date_done': transfer_date})
            except Exception as e:
                _logger.warning("Auto-validate source sale delivery picking note: %s", e)

        # Create and post Customer Invoice in Source Company
        invoice = False
        try:
            invoices = so._create_invoices()
            if invoices:
                invoice = invoices[0]
                invoice_vals = {
                    'invoice_date': transfer_date,
                    'date': transfer_date,
                }
                if 'is_approved' in invoice._fields:
                    invoice_vals['is_approved'] = True
                invoice.sudo().with_company(source_company).write(invoice_vals)
                invoice.sudo().with_company(source_company).action_post()
        except Exception as e:
            _logger.warning("Auto customer invoice note: %s", e)

        return so, invoice

    def _relieve_source_stock(self, source_company, dest_company, labels, transfer_date):
        """Create outgoing stock move from source company branch location to transit location."""
        transit_loc = self.env['stock.location'].sudo().search([
            ('usage', '=', 'transit'),
            ('company_id', 'in', [source_company.id, False])
        ], limit=1)

        picking_type = self.env['stock.picking.type'].sudo().search([
            ('code', '=', 'outgoing'),
            ('company_id', '=', source_company.id)
        ], limit=1)

        if not picking_type:
            picking_type = self.env['stock.picking.type'].sudo().search([
                ('company_id', '=', source_company.id)
            ], limit=1)

        if not picking_type or not transit_loc:
            _logger.warning("Could not find transit location or picking type for source stock relief.")
            return

        moves_data = {}
        for l in labels:
            src_loc = l.branch_location_id or l.source_location_id or picking_type.default_location_src_id
            if not src_loc:
                continue
            key = (src_loc.id, l.product_id.id)
            if key not in moves_data:
                moves_data[key] = {
                    'src_loc_id': src_loc.id,
                    'product_id': l.product_id.id,
                    'qty': 0.0,
                    'weight': 0.0,
                }
            moves_data[key]['qty'] += 1.0
            moves_data[key]['weight'] += (l.sale_gross_weight or l.purchase_gross_weight or 1.0)

        if not moves_data:
            return

        first_src_loc_id = list(moves_data.values())[0]['src_loc_id']
        try:
            picking = self.env['stock.picking'].sudo().with_company(source_company).create({
                'picking_type_id': picking_type.id,
                'location_id': first_src_loc_id,
                'location_dest_id': transit_loc.id,
                'origin': f"Inter-Company Transfer {self.name} to {dest_company.name}",
                'company_id': source_company.id,
                'scheduled_date': transfer_date,
            })

            for item in moves_data.values():
                prod = self.env['product.product'].browse(item['product_id'])
                move = self.env['stock.move'].sudo().with_company(source_company).create({
                    'name': f"Transfer to {dest_company.name}",
                    'product_id': prod.id,
                    'product_uom_qty': item['weight'] if prod.uom_id.name in ['g', 'Gram', 'Grams'] else item['qty'],
                    'product_uom': prod.uom_id.id,
                    'location_id': item['src_loc_id'],
                    'location_dest_id': transit_loc.id,
                    'picking_id': picking.id,
                    'company_id': source_company.id,
                })
                move.quantity = move.product_uom_qty

            picking.button_validate()
            picking.write({'date_done': transfer_date})
        except Exception as e:
            _logger.warning("Stock relief picking note: %s", e)

    def _get_or_create_intercompany_partner(self, source_company, dest_company):
        """Find or create a res.partner for the source company in destination company."""
        partner = self.env['res.partner'].sudo().with_company(dest_company).search([
            ('name', '=ilike', source_company.name.strip()),
            '|', ('company_id', '=', dest_company.id), ('company_id', '=', False)
        ], limit=1)

        if not partner:
            partner = self.env['res.partner'].sudo().with_company(dest_company).search([
                ('name', 'ilike', 'NAKSHATHRA'),
                ('name', 'ilike', source_company.name[:10]),
                '|', ('company_id', '=', dest_company.id), ('company_id', '=', False)
            ], limit=1)

        if not partner:
            partner = self.env['res.partner'].sudo().with_company(dest_company).create({
                'name': source_company.name,
                'company_type': 'company',
                'is_company': True,
                'supplier_rank': 1,
                'company_id': dest_company.id,
            })
        return partner

    def _create_destination_purchase_order(self, source_company, dest_company, dest_branch, supplier_partner, labels, transfer_date, so=None):
        """Create and confirm purchase order in destination company matching exact amounts of the transfer/sale order."""
        po_vals = {
            'partner_id': supplier_partner.id,
            'company_id': dest_company.id,
            'date_order': transfer_date,
            'origin': f"Inter-Company Transfer {self.name} from {source_company.name}",
        }
        if dest_branch:
            po_vals['branch_id'] = dest_branch.id

        po = self.env['purchase.order'].sudo().with_company(dest_company).create(po_vals)

        is_interstate = (source_company.state_id != dest_company.state_id)
        purchase_taxes = self.purchase_tax_id or self._get_intercompany_taxes(dest_company, 'purchase', is_interstate)

        po_lines_commands = []
        if so and so.order_line:
            # Build PO lines directly from confirmed Sale Order lines to ensure 100% price parity
            for so_line in so.order_line:
                dest_prod = self._resolve_product_for_dest_company(so_line.product_id, dest_company)
                gross_wt = round(so_line.product_uom_qty, 3)
                unit_price = round(so_line.price_subtotal / gross_wt, 4) if gross_wt else so_line.price_unit
                line_val = {
                    'order_id': po.id,
                    'product_id': dest_prod.id,
                    'name': f"{dest_prod.name} (Transferred from {source_company.name})",
                    'product_qty': gross_wt,
                    'product_uom': dest_prod.uom_po_id.id or dest_prod.uom_id.id,
                    'price_unit': unit_price,
                    'date_planned': transfer_date,
                }
                if purchase_taxes:
                    line_val['taxes_id'] = [(6, 0, purchase_taxes.ids)]
                if 'gross_weight' in self.env['purchase.order.line']._fields:
                    line_val['gross_weight'] = gross_wt
                if 'net_weight' in self.env['purchase.order.line']._fields:
                    line_val['net_weight'] = getattr(so_line, 'net_weight', gross_wt)
                if 'purity_id' in self.env['purchase.order.line']._fields and getattr(so_line, 'purity_id', False):
                    line_val['purity_id'] = so_line.purity_id.id
                if dest_branch and 'branch_id' in self.env['purchase.order.line']._fields:
                    line_val['branch_id'] = dest_branch.id

                po_lines_commands.append((0, 0, line_val))
        else:
            # Fallback when so is not provided
            for l in labels:
                dest_prod = self._resolve_product_for_dest_company(l.product_id, dest_company)
                gross_wt = l.sale_gross_weight or l.purchase_gross_weight or 1.0
                net_wt = l.sale_net_weight or l.purchase_net_weight or gross_wt
                purity = l.purity_id or l.sale_purity_id
                rate = self._get_active_gold_rate(purity, transfer_date)
                if not rate:
                    rate = l.purchase_price_per_gram or l.purchase_metal_rate or l.sale_price_per_gram or 0.0
                stone_rate = l.sale_stone_rate or l.purchase_stone_rate or 0.0
                diamond_rate = l.sale_diamond_rate or l.purchase_diamond_rate or 0.0
                item_val = round(net_wt * rate, 2) + stone_rate + diamond_rate
                unit_price = round(item_val / gross_wt, 4) if gross_wt else rate

                line_val = {
                    'order_id': po.id,
                    'product_id': dest_prod.id,
                    'name': f"{dest_prod.name} (Transferred from {source_company.name})",
                    'product_qty': round(gross_wt, 3),
                    'product_uom': dest_prod.uom_po_id.id or dest_prod.uom_id.id,
                    'price_unit': unit_price,
                    'date_planned': transfer_date,
                }
                if purchase_taxes:
                    line_val['taxes_id'] = [(6, 0, purchase_taxes.ids)]
                if 'gross_weight' in self.env['purchase.order.line']._fields:
                    line_val['gross_weight'] = round(gross_wt, 3)
                if 'net_weight' in self.env['purchase.order.line']._fields:
                    line_val['net_weight'] = round(net_wt, 3)
                if 'purity_id' in self.env['purchase.order.line']._fields and purity:
                    line_val['purity_id'] = purity.id
                if dest_branch and 'branch_id' in self.env['purchase.order.line']._fields:
                    line_val['branch_id'] = dest_branch.id

                po_lines_commands.append((0, 0, line_val))

        po.write({'order_line': po_lines_commands})
        if purchase_taxes:
            for pline in po.order_line:
                pline.sudo().write({'taxes_id': [(6, 0, purchase_taxes.ids)]})
        po.button_confirm()
        return po

    def _validate_destination_picking(self, po, dest_company, dest_location, transfer_date):
        """Validate destination incoming stock receipt picking to destination location."""
        pickings = po.picking_ids
        for picking in pickings:
            if picking.state in ['done', 'cancel']:
                continue
            picking.sudo().with_company(dest_company).write({
                'location_dest_id': dest_location.id,
                'scheduled_date': transfer_date,
            })
            for move in picking.move_ids:
                move.sudo().with_company(dest_company).write({
                    'location_dest_id': dest_location.id,
                    'quantity': move.product_uom_qty,
                })
            try:
                picking.button_validate()
                picking.write({'date_done': transfer_date})
            except Exception as e:
                _logger.warning("Auto-validate destination picking note: %s", e)

    def _create_destination_vendor_bill(self, po, dest_company, supplier_partner, transfer_date):
        """Generate and post approved vendor bill in destination company."""
        bill = False
        try:
            res = po.sudo().with_company(dest_company).action_create_invoice()
            invoice_ids = res.get('res_id') or (res.get('domain') and [d[2] for d in res['domain'] if d[0] == 'id'])
            if invoice_ids:
                if isinstance(invoice_ids, list):
                    bill = self.env['account.move'].sudo().with_company(dest_company).browse(invoice_ids[0])
                else:
                    bill = self.env['account.move'].sudo().with_company(dest_company).browse(invoice_ids)
            if not bill and po.invoice_ids:
                bill = po.invoice_ids[0]

            if bill:
                bill_vals = {
                    'invoice_date': transfer_date,
                    'date': transfer_date,
                }
                if 'is_approved' in bill._fields:
                    bill_vals['is_approved'] = True
                bill.sudo().with_company(dest_company).write(bill_vals)
                is_interstate = (po.company_id.state_id != po.partner_id.state_id)
                purchase_taxes = self.purchase_tax_id or self._get_intercompany_taxes(dest_company, 'purchase', is_interstate)
                if purchase_taxes:
                    for bline in bill.invoice_line_ids:
                        bline.sudo().write({'tax_ids': [(6, 0, purchase_taxes.ids)]})
                bill.sudo().with_company(dest_company).action_post()
        except Exception as e:
            _logger.warning("Auto vendor bill note: %s", e)
        return bill

    def _create_destination_labels(self, po, dest_company, dest_branch, dest_location, labels):
        """Create new active product labels in destination company preserving exact label name and barcode."""
        dest_warehouse = self.env['stock.warehouse'].sudo().search([
            ('company_id', '=', dest_company.id)
        ], limit=1)
        dest_lot_stock = dest_warehouse.lot_stock_id or dest_location

        created_labels = self.env['product.label']
        for label in labels:
            dest_prod = self._resolve_product_for_dest_company(label.product_id, dest_company)
            gross_wt = label.sale_gross_weight or label.purchase_gross_weight or 0.0
            net_wt = label.sale_net_weight or label.purchase_net_weight or gross_wt
            purity = label.purity_id or label.sale_purity_id
            board_rate = self._get_active_gold_rate(purity, self.transfer_date)
            if not board_rate:
                board_rate = label.purchase_price_per_gram or label.purchase_metal_rate or label.sale_price_per_gram or 0.0
            metal_val = round(net_wt * board_rate, 2)
            stone_rate = label.sale_stone_rate or label.purchase_stone_rate or 0.0
            diamond_rate = label.sale_diamond_rate or label.purchase_diamond_rate or 0.0
            total_cost = metal_val + stone_rate + diamond_rate
            orig_vendor = label.original_vendor_id or label.partner_id

            label_vals = {
                'name': label.name,
                'company_id': dest_company.id,
                'branch_id': dest_branch.id if dest_branch else False,
                'product_id': dest_prod.id,
                'product_template_id': dest_prod.product_tmpl_id.id,
                'purchase_id': po.id,
                'original_vendor_id': orig_vendor.id if orig_vendor else False,
                'partner_id': orig_vendor.id if orig_vendor else False,
                'source_location_id': dest_lot_stock.id if dest_lot_stock else False,
                'branch_location_id': dest_location.id if dest_location else False,

                # Exact barcode retention
                'barcode': label.barcode,
                'barcode2': label.barcode2,

                # Image & Certificate
                'image': label.image,
                'diamond_certificate': label.diamond_certificate,
                'diamond_certificate_filename': label.diamond_certificate_filename,

                # Weights
                'tag_weight': label.tag_weight,
                'sale_gross_weight': gross_wt,
                'purchase_gross_weight': gross_wt,
                'sale_net_weight': net_wt,
                'purchase_net_weight': net_wt,

                # Purity
                'purity_id': label.purity_id.id if label.purity_id else False,
                'sale_purity_id': label.sale_purity_id.id if label.sale_purity_id else (label.purity_id.id if label.purity_id else False),

                # Stones & Diamonds
                'sale_stone_weight': label.sale_stone_weight,
                'purchase_stone_weight': label.purchase_stone_weight,
                'sale_diamond_weight': label.sale_diamond_weight,
                'purchase_diamond_weight': label.purchase_diamond_weight,
                'sale_diamond_weight_gm': label.sale_diamond_weight_gm,
                'sale_diamond_weight_ct': label.sale_diamond_weight_ct,
                'purchase_diamond_weight_gm': label.purchase_diamond_weight_gm,
                'purchase_diamond_weight_ct': label.purchase_diamond_weight_ct,
                'sale_stone_rate': label.sale_stone_rate,
                'purchase_stone_rate': stone_rate,
                'sale_diamond_rate': label.sale_diamond_rate,
                'purchase_diamond_rate': diamond_rate,

                # Other weights
                'other_weight_g': label.other_weight_g,
                'other_weight_amount': label.other_weight_amount,

                # Pricing & Rates (Board Rate Purchase in Destination Company)
                'purchase_price_per_gram': board_rate,
                'purchase_metal_rate': metal_val,
                'sale_price_per_gram': label.sale_price_per_gram or board_rate,
                'sale_metal_rate': label.sale_metal_rate or metal_val,

                # Retail Making charges
                'sale_making_charge_type': label.sale_making_charge_type,
                'sale_making_charge_value': label.sale_making_charge_value,
                'sale_making_charge_min': label.sale_making_charge_min,
                'sale_making_charge_amount': label.sale_making_charge_amount,
                'sale_making_charge_fixed_amount_max': label.sale_making_charge_fixed_amount_max,
                'sale_making_charge_fixed_amount_min': label.sale_making_charge_fixed_amount_min,
                'purchase_making_charge_type': label.purchase_making_charge_type,
                'purchase_making_charge_value': label.purchase_making_charge_value,
                'purchase_making_charge_amount': label.purchase_making_charge_amount,
            }

            new_label = self.env['product.label'].sudo().with_company(dest_company).create(label_vals)

            # Ensure exact label name, barcode, and original vendor
            update_vals = {}
            if new_label.name != label.name:
                update_vals['name'] = label.name
            if label.barcode and new_label.barcode != label.barcode:
                update_vals['barcode'] = label.barcode
            if label.barcode2 and new_label.barcode2 != label.barcode2:
                update_vals['barcode2'] = label.barcode2
            if orig_vendor and new_label.partner_id != orig_vendor:
                update_vals['partner_id'] = orig_vendor.id
                update_vals['original_vendor_id'] = orig_vendor.id
            if update_vals:
                new_label.sudo().write(update_vals)

            created_labels |= new_label

            # Trigger Stock In
            if new_label.source_location_id and new_label.branch_location_id and new_label.source_location_id != new_label.branch_location_id:
                try:
                    new_label.with_company(dest_company).action_stock_in()
                except Exception as stock_err:
                    _logger.warning("action_stock_in bypassed on label %s: %s", new_label.id, stock_err)
                    new_label.write({'is_stocked_in': True, 'active': True})
            else:
                new_label.write({'is_stocked_in': True, 'active': True})

        return created_labels

    def _resolve_product_for_dest_company(self, source_product, dest_company):
        """Map source product variant to corresponding variant in destination company."""
        if not source_product.company_id or source_product.company_id == dest_company:
            return source_product

        source_tmpl = source_product.product_tmpl_id
        tmpl_name = source_tmpl.name

        dest_tmpl = self.env['product.template'].sudo().with_company(dest_company).search([
            ('name', '=', tmpl_name),
            ('company_id', 'in', [dest_company.id, False])
        ], limit=1)

        if not dest_tmpl:
            dest_tmpl = self.env['product.template'].sudo().with_company(dest_company).search([
                ('name', '=ilike', tmpl_name.strip()),
                ('company_id', 'in', [dest_company.id, False])
            ], limit=1)

        if not dest_tmpl:
            raise UserError(_("Product Template '%s' does not exist in destination company '%s'.") % (
                tmpl_name, dest_company.name
            ))

        if len(dest_tmpl.product_variant_ids) == 1:
            return dest_tmpl.product_variant_ids[0]

        source_attr_vals = source_product.product_template_attribute_value_ids.mapped('product_attribute_value_id')
        for var in dest_tmpl.product_variant_ids:
            var_attr_vals = var.product_template_attribute_value_ids.mapped('product_attribute_value_id')
            if set(var_attr_vals.ids) == set(source_attr_vals.ids):
                return var

        return dest_tmpl.product_variant_ids[0]

    def action_view_created_so(self):
        self.ensure_one()
        if not self.result_so_id:
            return
        return {
            'name': _('Source Sale Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.result_so_id.id,
            'view_mode': 'form',
        }

    def action_view_created_invoice(self):
        self.ensure_one()
        if not self.result_invoice_id:
            return
        return {
            'name': _('Source Customer Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.result_invoice_id.id,
            'view_mode': 'form',
        }

    def action_view_created_labels(self):
        self.ensure_one()
        return {
            'name': _('Transferred Product Labels (%s)') % self.dest_company_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.transferred_label_ids.ids)],
            'context': {'active_test': False},
        }

    def action_view_created_po(self):
        self.ensure_one()
        if not self.result_po_id:
            return
        return {
            'name': _('Destination Purchase Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': self.result_po_id.id,
            'view_mode': 'form',
        }

    def action_view_created_bill(self):
        self.ensure_one()
        if not self.result_bill_id:
            return
        return {
            'name': _('Destination Vendor Bill'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.result_bill_id.id,
            'view_mode': 'form',
        }


class LabelIntercompanyTransferLine(models.Model):
    _name = 'label.intercompany.transfer.line'
    _description = 'Inter-Company Product Label Transfer Line'

    transfer_id = fields.Many2one(
        'label.intercompany.transfer',
        string="Transfer Reference",
        required=True,
        ondelete='cascade'
    )
    label_id = fields.Many2one(
        'product.label',
        string="Source Label",
        required=True,
        domain="[('company_id', '=', parent.source_company_id), ('is_transferred', '=', False), ('active', '=', True)]"
    )
    barcode = fields.Char(
        string="Barcode",
        related='label_id.barcode',
        readonly=True
    )
    product_id = fields.Many2one(
        'product.product',
        string="Product",
        related='label_id.product_id',
        readonly=True
    )
    categ_id = fields.Many2one(
        'product.category',
        string="Category",
        related='product_id.categ_id',
        readonly=True
    )
    purity_id = fields.Many2one(
        'gold.purity',
        string="Purity",
        related='label_id.purity_id',
        readonly=True
    )
    gross_weight = fields.Float(
        string="Gross Wt (g)",
        digits=(16, 3),
        compute="_compute_line_fields",
        store=True,
        readonly=True
    )
    net_weight = fields.Float(
        string="Net Wt (g)",
        digits=(16, 3),
        compute="_compute_line_fields",
        store=True,
        readonly=True
    )
    fine_weight = fields.Float(
        string="Fine Wt (g)",
        digits=(16, 3),
        compute="_compute_line_fields",
        store=True,
        readonly=True
    )
    rate_per_gram = fields.Float(
        string="Rate / g",
        digits=(16, 2),
        compute="_compute_line_fields",
        store=True,
        readonly=True
    )
    stone_diamond_amount = fields.Float(
        string="Stone/Dia Value (₹)",
        digits=(16, 2),
        compute="_compute_line_fields",
        store=True,
        readonly=True
    )
    subtotal = fields.Float(
        string="Estimated Value",
        digits=(16, 2),
        compute="_compute_line_fields",
        store=True,
        readonly=True
    )
    dest_label_id = fields.Many2one(
        'product.label',
        string="Created Destination Label",
        readonly=True,
        copy=False
    )

    @api.depends('label_id', 'transfer_id.transfer_date')
    def _compute_line_fields(self):
        for line in self:
            lbl = line.label_id
            if lbl:
                gross = lbl.sale_gross_weight or lbl.purchase_gross_weight or 1.0
                net = lbl.sale_net_weight or lbl.purchase_net_weight or gross
                fine = lbl.sale_fine_weight or lbl.purchase_fine_weight or 0.0
                purity = lbl.purity_id or lbl.sale_purity_id
                rate = line.transfer_id._get_active_gold_rate(purity, line.transfer_id.transfer_date) if line.transfer_id else 0.0
                if not rate:
                    rate = lbl.purchase_price_per_gram or lbl.purchase_metal_rate or lbl.sale_price_per_gram or 0.0
                stone_val = (lbl.sale_stone_rate or lbl.purchase_stone_rate or 0.0) + (lbl.sale_diamond_rate or lbl.purchase_diamond_rate or 0.0)
                metal_val = round(net * rate, 2)
                line.gross_weight = round(gross, 3)
                line.net_weight = round(net, 3)
                line.fine_weight = round(fine, 3)
                line.rate_per_gram = round(rate, 2)
                line.stone_diamond_amount = round(stone_val, 2)
                line.subtotal = round(metal_val + stone_val, 2)
            else:
                line.gross_weight = 0.0
                line.net_weight = 0.0
                line.fine_weight = 0.0
                line.rate_per_gram = 0.0
                line.stone_diamond_amount = 0.0
                line.subtotal = 0.0
